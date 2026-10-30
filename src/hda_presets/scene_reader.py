"""Read Houdini Engine asset nodes and their parameter values from a saved Maya ASCII file.

The module runs without Maya. A .ma file stores a dynamic attribute value only if it differs
from the attribute default, so a value that is not stored comes from `addAttr -dv`, or is 0 if
the attribute has no default.
"""



import re
from dataclasses import dataclass, field
from . import core
from .attribute_rules import (
    NUMERIC_COMPOUND_TYPES, PARM_PREFIX, TUPLE, UNSUPPORTED, VALUE,
    classify_attr, convert_value, parm_name, parse_enum_names,
)



_SETATTR_FLAGS_WITH_ARG = {"-l", "-k", "-cb", "-type", "-s", "-ch", "-cl"}
_ADDATTR_FLAGS_NO_ARG = {"-m", "-im", "-uaf", "-k"}
_NODE_BLOCK_COMMANDS = {"createNode", "rename", "addAttr", "setAttr", "lockNode"}
_BOOL_WORDS = {"yes": 1, "on": 1, "true": 1, "no": 0, "off": 0, "false": 0}
_CREATE_ASSET_NODE = re.compile(r'^createNode houdiniAsset\b[^\n]*?-n "([^"]+)"', re.MULTILINE)


@dataclass(frozen=True)
class AssetNodeInfo:
    name: str
    uuid: str
    asset_name: str
    otl_path: str


@dataclass
class _ParsedNode:
    uuid: str = ""
    asset_name: str = ""
    otl_path: str = ""
    attrs: dict = field(default_factory=dict)
    order: list = field(default_factory=list)
    values: dict = field(default_factory=dict)


# ==== Public reading functions =============================================


def list_asset_nodes(ma_path: str) -> list[AssetNodeInfo]:
    """Return every houdiniAsset node in the file, in file order.
    The UUID is an empty string if the file does not store one."""
    nodes = []
    for name, block in _asset_blocks(_read_text(ma_path)):
        parsed = _parse_block(block)
        nodes.append(AssetNodeInfo(name, parsed.uuid, parsed.asset_name, parsed.otl_path))
    return nodes


def read_presets(ma_path: str, node_names: list[str]) -> dict[str, dict]:
    """Read the presets of several houdiniAsset nodes in one pass over the file.
    Raises ValueError if a node is missing or if more than one node has its name."""
    blocks = {}
    for name, block in _asset_blocks(_read_text(ma_path)):
        blocks.setdefault(name, []).append(block)

    presets = {}
    for name in node_names:
        found = blocks.get(name, [])
        if not found:
            raise ValueError("houdiniAsset node %r was not found in %s." % (name, ma_path))
        if len(found) > 1:
            raise ValueError("%d houdiniAsset nodes are named %r in %s." % (len(found), name, ma_path))
        presets[name] = _build_preset(ma_path, name, _parse_block(found[0]))
    return presets


# ==== File and block parsing ===============================================


def _read_text(ma_path: str) -> str:
    with open(ma_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _asset_blocks(text: str) -> list[tuple[str, str]]:
    """Split out the text of every houdiniAsset node, from its createNode line to the next one."""
    blocks = []
    for match in _CREATE_ASSET_NODE.finditer(text):
        end = text.find("\ncreateNode ", match.end())
        blocks.append((match.group(1), text[match.start():end if end != -1 else len(text)]))
    return blocks


def _parse_block(block: str) -> _ParsedNode:
    parsed = _ParsedNode()
    short_to_long = {}

    for tokens in _iter_statements(block):
        command = tokens[0][1]
        if command not in _NODE_BLOCK_COMMANDS:
            break

        if command == "rename":
            words = [word for _, word in tokens]
            if "-uid" in words and words.index("-uid") + 1 < len(words):
                parsed.uuid = words[words.index("-uid") + 1]

        elif command == "addAttr":
            options, flags = _parse_addattr(tokens)
            long_name = options.get("-ln") or options.get("-sn")
            if not long_name or not long_name.startswith(PARM_PREFIX):
                continue
            short_to_long[options.get("-sn", long_name)] = long_name
            parent = options.get("-p")
            parsed.attrs[long_name] = {
                "at": options.get("-at"), "dt": options.get("-dt"), "dv": options.get("-dv"),
                "en": options.get("-en"), "parent": parent, "multi": "-m" in flags, "children": [],
            }
            parsed.order.append(long_name)
            if parent in parsed.attrs:
                parsed.attrs[parent]["children"].append(long_name)

        elif command == "setAttr":
            plug, type_name, args = _parse_setattr(tokens)
            if not plug or not args:
                continue
            name = plug.lstrip(".")
            if name == "assetName":
                parsed.asset_name = args[0]
            elif name == "otlFilePath":
                parsed.otl_path = args[0]
            elif "[" not in name:
                long_name = short_to_long.get(name.split(".")[-1], name.split(".")[-1])
                if long_name.startswith(PARM_PREFIX):
                    parsed.values[long_name] = _raw_value(type_name, args)

    _spread_compound_values(parsed)
    return parsed


def _raw_value(type_name: str | None, args: list[str]):
    """Return the value that a setAttr command writes.
    Returns ("unsupported", type) for data types that the format cannot hold."""
    if type_name == "string":
        return args[0]
    if type_name and type_name not in NUMERIC_COMPOUND_TYPES:
        return ("unsupported", type_name)
    numbers = [_to_number(word) for word in args]
    return numbers[0] if len(numbers) == 1 else numbers


def _spread_compound_values(parsed: _ParsedNode) -> None:
    """Move a list value written on a numeric compound to the compound's children."""
    for name in list(parsed.values):
        info = parsed.attrs.get(name)
        if info and info["children"] and isinstance(parsed.values[name], list):
            for child, value in zip(info["children"], parsed.values.pop(name)):
                parsed.values.setdefault(child, value)


def _build_preset(ma_path: str, node_name: str, parsed: _ParsedNode) -> dict:
    parms, labels, skipped = {}, {}, {}
    tuple_children = set()

    for long_name in parsed.order:
        info = parsed.attrs[long_name]
        if long_name == PARM_PREFIX or long_name in tuple_children or _is_under_multi(parsed, long_name):
            continue
        kind, reason = classify_attr(long_name, info["at"], info["children"], info["multi"])
        parm = parm_name(long_name)

        if kind == UNSUPPORTED:
            skipped[parm] = reason
        elif kind == TUPLE:
            tuple_children.update(info["children"])
            try:
                parms[parm] = [_leaf_value(parsed, child) for child in info["children"]]
            except (TypeError, ValueError) as e:
                skipped[parm] = str(e)
        elif kind == VALUE:
            try:
                parms[parm] = _leaf_value(parsed, long_name)
            except (TypeError, ValueError) as e:
                skipped[parm] = str(e)
                continue
            if info["at"] == "enum":
                label = parse_enum_names(info["en"]).get(parms[parm])
                if label is not None:
                    labels[parm] = label

    return core.make_preset(
        parms,
        hda_name=parsed.asset_name,
        hda_library=parsed.otl_path,
        source_app="maya",
        source_file=ma_path,
        source_node=node_name,
        source_node_uuid=parsed.uuid,
        menu_labels=labels,
        skipped=skipped,
    )


def _leaf_value(parsed: _ParsedNode, long_name: str):
    """Return the stored value of an attribute, or its default if the file stores none.
    Raises TypeError for data types that the format cannot hold."""
    info = parsed.attrs[long_name]
    if long_name in parsed.values:
        value = parsed.values[long_name]
    elif info["dt"]:
        value = ""
    else:
        value = _to_number(info["dv"]) if info["dv"] is not None else 0

    if isinstance(value, tuple):
        raise TypeError("data type %s" % value[1])
    if info["dt"]:
        if info["dt"] != "string":
            raise TypeError("data type %s" % info["dt"])
        return value
    return convert_value(info["at"], value)


def _is_under_multi(parsed: _ParsedNode, long_name: str) -> bool:
    parent = parsed.attrs[long_name]["parent"]
    while parent in parsed.attrs:
        if parsed.attrs[parent]["multi"]:
            return True
        parent = parsed.attrs[parent]["parent"]
    return False


# ==== MEL tokens ===========================================================


def _iter_statements(text: str):
    """Yield the MEL commands of the text as lists of (kind, word) tokens.
    The kind is "str" for a quoted string and "word" for everything else."""
    tokens, buffer, i, length = [], [], 0, len(text)

    def flush():
        if buffer:
            tokens.append(("word", "".join(buffer)))
            buffer.clear()

    while i < length:
        char = text[i]
        if char == '"':
            flush()
            i += 1
            chars = []
            while i < length and text[i] != '"':
                if text[i] == "\\" and i + 1 < length:
                    chars.append({"n": "\n", "t": "\t", "r": "\r"}.get(text[i + 1], text[i + 1]))
                    i += 2
                    continue
                chars.append(text[i])
                i += 1
            tokens.append(("str", "".join(chars)))
            i += 1
        elif char == ";":
            flush()
            if tokens:
                yield tokens
            tokens = []
            i += 1
        elif char.isspace():
            flush()
            i += 1
        else:
            buffer.append(char)
            i += 1
    flush()
    if tokens:
        yield tokens


def _is_flag(kind: str, word: str) -> bool:
    return kind == "word" and word.startswith("-") and not _looks_numeric(word)


def _parse_addattr(tokens: list) -> tuple[dict, set]:
    options, flags = {}, set()
    i = 1
    while i < len(tokens):
        kind, word = tokens[i]
        if not _is_flag(kind, word):
            i += 1
            continue
        flags.add(word)
        next_is_flag = i + 1 >= len(tokens) or _is_flag(*tokens[i + 1])
        if word in _ADDATTR_FLAGS_NO_ARG and next_is_flag:
            i += 1
            continue
        if i + 1 < len(tokens):
            options.setdefault(word, tokens[i + 1][1])
        i += 2
    return options, flags


def _parse_setattr(tokens: list) -> tuple[str | None, str | None, list[str]]:
    plug, type_name, args = None, None, []
    i = 1
    while i < len(tokens):
        kind, word = tokens[i]
        if _is_flag(kind, word):
            if word in _SETATTR_FLAGS_WITH_ARG and i + 1 < len(tokens):
                if word == "-type":
                    type_name = tokens[i + 1][1]
                i += 2
            else:
                i += 1
            continue
        if plug is None:
            plug = word
        else:
            args.append(word)
        i += 1
    return plug, type_name, args


def _looks_numeric(word: str) -> bool:
    try:
        float(word)
        return True
    except ValueError:
        return False


def _to_number(word: str):
    """Convert a MEL word to int or float.
    The words yes, on and true become 1; no, off and false become 0."""
    lowered = word.lower()
    if lowered in _BOOL_WORDS:
        return _BOOL_WORDS[lowered]
    try:
        return int(word)
    except ValueError:
        return float(word)
