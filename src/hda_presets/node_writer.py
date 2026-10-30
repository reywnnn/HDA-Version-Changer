"""Read, apply and compare presets on Houdini Engine asset nodes in a running Maya session.

Attributes are sorted with the rules in attribute_rules, the same ones scene_reader uses for
saved files.
"""



import re
import maya.cmds as cmds
import maya.mel as mel
from . import core
from .core import ApplyResult, values_equal
from .attribute_rules import (
    FOLDER, IGNORED, PARM_PREFIX, TUPLE, UNSUPPORTED,
    attr_name, classify_attr, convert_value, parm_name, parse_enum_names,
)



AFFECTS_OTHERS_CATEGORY = "hapiParm_affectsOthers"
_READABLE_TYPES = {"bool", "long", "short", "byte", "char", "enum",
                   "float", "double", "doubleLinear", "doubleAngle", "time"}


# ==== Reading ==============================================================


def read_node_preset(node: str) -> dict:
    """Build a preset from the values the node holds in Maya memory right now."""
    parms, labels, skipped = {}, {}, {}

    for attr, kind, reason in _walk_attrs(node):
        parm = parm_name(attr)
        if kind == UNSUPPORTED:
            skipped[parm] = reason
            continue
        try:
            if kind == TUPLE:
                parms[parm] = [_read_leaf(node, child) for child in _children(node, attr)]
                continue
            parms[parm] = _read_leaf(node, attr)
        except TypeError as e:
            skipped[parm] = str(e)
            continue
        if _query(node, attr, attributeType=True) == "enum":
            label = _enum_names(node, attr).get(cmds.getAttr(_plug(node, attr)))
            if label is not None:
                labels[parm] = label

    return core.make_preset(
        parms,
        hda_name=cmds.getAttr(_plug(node, "assetName")) or "",
        hda_library=cmds.getAttr(_plug(node, "otlFilePath")) or "",
        source_app="maya",
        source_app_version=cmds.about(version=True),
        source_file=cmds.file(query=True, sceneName=True) or "",
        source_node=node.split("|")[-1],
        source_node_uuid=(cmds.ls(node, uuid=True) or [""])[0],
        menu_labels=labels,
        skipped=skipped,
    )


def _walk_attrs(node: str, parent: str = PARM_PREFIX):
    """Yield (attribute, kind, reason) for every value, tuple and unsupported attribute in order.
    Folders are entered and ignored attributes are left out."""
    if not cmds.objExists(_plug(node, parent)):
        return
    for attr in _children(node, parent):
        kind, reason = classify_attr(
            attr,
            _query(node, attr, attributeType=True),
            _children(node, attr),
            bool(_query(node, attr, multi=True)),
        )
        if kind == FOLDER:
            yield from _walk_attrs(node, attr)
        elif kind != IGNORED:
            yield attr, kind, reason


def _read_leaf(node: str, attr: str):
    """Return the value of a single attribute converted to the preset type.
    Raises TypeError for data types that the format cannot hold."""
    plug = _plug(node, attr)
    attr_type = cmds.getAttr(plug, type=True)
    if attr_type == "string":
        return cmds.getAttr(plug) or ""
    if attr_type in _READABLE_TYPES:
        return convert_value(attr_type, cmds.getAttr(plug))
    raise TypeError("data type %s" % attr_type)


# ==== Applying =============================================================


def apply_preset(node: str, preset: dict, max_passes: int = 4) -> ApplyResult:
    """Write the preset values to the node, controlling parameters first, then in repeated passes.
    The node is synced after every write that changed something."""
    core.validate(preset)
    parms = preset["parameters"]
    labels = preset.get("menu_labels") or {}
    result = ApplyResult()
    written = set()

    for parm in _controlling_parms(node):
        if parm not in parms:
            continue
        changed, _, _ = _write_pass(node, {parm: parms[parm]}, labels)
        if changed:
            written.update(changed)
            sync(node)

    for attempt in range(1, max(1, max_passes) + 1):
        changed, result.missing, result.problems = _write_pass(node, parms, labels)
        result.passes = attempt
        written.update(changed)
        if not changed:
            break
        sync(node)

    result.written = sorted(written)
    result.mismatched = mismatches(node, preset)
    return result


def _controlling_parms(node: str) -> list[str]:
    """Return the parameters whose attribute has the hapiParm_affectsOthers category, in attribute order."""
    result = []
    for attr, kind, _ in _walk_attrs(node):
        if kind == UNSUPPORTED:
            continue
        categories = cmds.addAttr(_plug(node, attr), query=True, category=True) or []
        if AFFECTS_OTHERS_CATEGORY in categories:
            result.append(parm_name(attr))
    return result


def _write_pass(node: str, parms: dict, labels: dict) -> tuple[list[str], list[str], dict[str, str]]:
    """Write every value once with the node's sync scriptJobs suspended.
    Returns the changed parameters, the parameters without an attribute and the failed ones."""
    suspend_sync_jobs(node)
    changed, missing, problems = [], [], {}
    for parm, value in parms.items():
        if not cmds.objExists(_plug(node, attr_name(parm))):
            missing.append(parm)
            continue
        try:
            targets = _targets(node, parm, value, labels.get(parm))
            if any([_set_plug(node, attr, target) for attr, target in targets]):
                changed.append(parm)
        except Exception as e:
            problems[parm] = str(e)
    return changed, sorted(missing), problems


def _targets(node: str, parm: str, value, label: str | None) -> list[tuple[str, object]]:
    """Return the leaf attributes and values that one preset value is written to.
    Raises ValueError if a tuple has a different number of components on the node."""
    attr = attr_name(parm)
    if isinstance(value, list):
        children = _children(node, attr)
        if len(children) != len(value):
            raise ValueError("expected %d components, the node has %d" % (len(value), len(children)))
        return list(zip(children, value))
    if cmds.getAttr(_plug(node, attr), type=True) == "enum":
        return [(attr, _enum_index(node, attr, value, label))]
    return [(attr, value)]


def _enum_index(node: str, attr: str, value, label: str | None) -> int:
    """Return the enum index for the label, or the stored index if the menu has no such label."""
    for index, name in _enum_names(node, attr).items():
        if label is not None and name == label:
            return index
    return int(value)


def _set_plug(node: str, attr: str, value) -> bool:
    """Write a value to one attribute and return True if the value changed.
    Raises RuntimeError if an incoming connection drives the attribute."""
    plug = _plug(node, attr)
    if values_equal(cmds.getAttr(plug), value):
        return False
    if cmds.listConnections(plug, source=True, destination=False):
        raise RuntimeError("the attribute is connected")

    was_locked = cmds.getAttr(plug, lock=True)
    try:
        if was_locked:
            cmds.setAttr(plug, lock=False)
        if cmds.getAttr(plug, type=True) == "string":
            cmds.setAttr(plug, value, type="string")
        else:
            cmds.setAttr(plug, value)
    finally:
        if was_locked:
            try:
                cmds.setAttr(plug, lock=True)
            except RuntimeError:
                pass
    return True


# ==== Comparing ============================================================


def mismatches(node: str, preset: dict) -> list[tuple[str, object, object]]:
    """Return (parameter, preset value, node value) for every preset value the node does not hold.
    Parameters without an attribute on the node are left out."""
    labels = preset.get("menu_labels") or {}
    result = []
    for parm, value in preset["parameters"].items():
        if not cmds.objExists(_plug(node, attr_name(parm))):
            continue
        try:
            targets = _targets(node, parm, value, labels.get(parm))
        except Exception:
            continue
        for attr, wanted in targets:
            actual = cmds.getAttr(_plug(node, attr))
            if not values_equal(actual, wanted):
                result.append((parm, value, actual))
                break
    return result


# ==== Sync =================================================================


def sync(node: str) -> None:
    """Sync the node with Houdini Engine after suspending its sync scriptJobs."""
    suspend_sync_jobs(node)
    mel.eval('houdiniEngine_syncAsset("%s");' % node)


def suspend_sync_jobs(node: str) -> int:
    """Kill the Attribute Editor scriptJobs that sync this node after an attribute change.
    Returns the number of killed jobs. The Attribute Editor creates them again after a sync."""
    short_name = node.split("|")[-1]
    pattern = re.compile(r"(?<![\w:])%s(?!\w)" % re.escape(short_name))
    killed = 0
    for job in cmds.scriptJob(listJobs=True) or []:
        if "attributeChange" not in job or "houdiniEngine_syncAsset" not in job:
            continue
        if not pattern.search(job):
            continue
        try:
            cmds.scriptJob(kill=int(job.split(":", 1)[0]), force=True)
            killed += 1
        except (ValueError, RuntimeError):
            pass
    return killed


# ==== Maya queries =========================================================


def _plug(node: str, attr: str) -> str:
    return "%s.%s" % (node, attr)


def _query(node: str, attr: str, **flags):
    return cmds.attributeQuery(attr, node=node, **flags)


def _children(node: str, attr: str) -> list[str]:
    return _query(node, attr, listChildren=True) or []


def _enum_names(node: str, attr: str) -> dict[int, str]:
    return parse_enum_names((_query(node, attr, listEnum=True) or [""])[0])
