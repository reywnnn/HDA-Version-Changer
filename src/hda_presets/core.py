"""Create, validate, save, load and compare parameter presets.

A preset is a plain dict with the parameter values of one Houdini Engine asset node. It looks
the same in every application, so this module imports nothing from Maya or Houdini.
"""



import datetime
import getpass
import json
import os
from dataclasses import dataclass, field



FORMAT_NAME = "hda_presets"
FORMAT_VERSION = 1
FILE_SUFFIX = ".hda_presets.json"
FLOAT_TOLERANCE = 1e-5


@dataclass
class ApplyResult:
    written: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    problems: dict[str, str] = field(default_factory=dict)
    mismatched: list[tuple[str, object, object]] = field(default_factory=list)
    passes: int = 0


def make_preset(
    parms: dict,
    hda_name: str = "",
    hda_library: str = "",
    source_app: str = "",
    source_app_version: str = "",
    source_file: str = "",
    source_node: str = "",
    source_node_uuid: str = "",
    menu_labels: dict | None = None,
    skipped: dict | None = None,
    upgrade: dict | None = None,
) -> dict:
    source = {
        "app": source_app,
        "app_version": str(source_app_version),
        "file": source_file,
        "node": source_node,
    }
    if source_node_uuid:
        source["node_uuid"] = source_node_uuid
    source["created"] = datetime.datetime.now().isoformat(timespec="seconds")
    source["user"] = _user()

    preset = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "hda": {"name": hda_name, "library": hda_library},
        "source": source,
    }
    if upgrade:
        preset["upgrade"] = dict(upgrade)
    preset["parameters"] = {name: _normalize(parms[name]) for name in sorted(parms)}
    if menu_labels:
        preset["menu_labels"] = {name: menu_labels[name] for name in sorted(menu_labels) if name in parms}
    if skipped:
        preset["skipped"] = {name: skipped[name] for name in sorted(skipped)}
    return preset


def validate(preset: dict) -> dict:
    """Raise ValueError if the preset breaks the format, otherwise return it unchanged."""
    if not isinstance(preset, dict):
        raise ValueError("A preset must be a JSON object.")
    if preset.get("format") != FORMAT_NAME:
        raise ValueError("Unknown format %r, expected %r." % (preset.get("format"), FORMAT_NAME))
    version = preset.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool) or version > FORMAT_VERSION:
        raise ValueError("Unsupported format version %r, the newest known is %d." % (version, FORMAT_VERSION))
    parms = preset.get("parameters")
    if not isinstance(parms, dict):
        raise ValueError("The preset has no 'parameters' object.")
    for name, value in parms.items():
        if not _is_valid_value(value):
            raise ValueError("Parameter %r has an unsupported value %r." % (name, value))
    if "upgrade" in preset and not isinstance(preset["upgrade"], dict):
        raise ValueError("'upgrade' must be a JSON object.")
    return preset


def diff_parms(old_preset: dict, new_preset: dict) -> tuple[dict, list]:
    """Compare the parameter names of two presets.
    Returns the added parameters with their new values and a sorted list of removed names."""
    def names(preset):
        return set(preset["parameters"]) | set(preset.get("skipped") or {})

    old_names, new_names = names(old_preset), names(new_preset)
    new_skipped = new_preset.get("skipped") or {}
    added = {
        name: new_preset["parameters"].get(name, new_skipped.get(name))
        for name in sorted(new_names - old_names)
    }
    return added, sorted(old_names - new_names)


def values_equal(a, b) -> bool:
    """Compare two parameter values, numbers with the tolerance FLOAT_TOLERANCE."""
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        a, b = list(a or []), list(b or [])
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, str) or isinstance(b, str):
        return (a or "") == (b or "")
    try:
        return abs(float(a) - float(b)) <= FLOAT_TOLERANCE
    except (TypeError, ValueError):
        return a == b


def save(preset: dict, path: str) -> str:
    """Validate the preset and write it to path, replacing the file in one step."""
    validate(preset)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(preset, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(temp_path, path)
    return path


def load(path: str) -> dict:
    """Read a preset from a JSON file and validate it."""
    with open(path, "r", encoding="utf-8") as f:
        return validate(json.load(f))


def _normalize(value):
    """Convert a value to a type the format allows.
    Tuples become lists, other numbers become float and anything else becomes str."""
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _is_valid_value(value, nested: bool = False) -> bool:
    if isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list) and not nested:
        return all(_is_valid_value(item, nested=True) for item in value)
    return False


def _user() -> str:
    """Return the login name of the current user, or an empty string if it cannot be read."""
    try:
        return getpass.getuser()
    except Exception:
        return ""
