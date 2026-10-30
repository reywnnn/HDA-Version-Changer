"""Map the attributes of a Houdini Engine asset node in Maya to preset parameters.

scene_reader and node_writer sort attributes with these rules, so a preset read from a node and
a preset read from its saved scene have the same parameters. The module runs without Maya.

Houdini Engine for Maya names the attributes of an asset node like this:

    houdiniAssetParm_<parm>                      parameter <parm>
    houdiniAssetParm_<name>__folder (compound)   folder without a value
    numeric compound, or a compound whose
    children all start with its own name         parm tuple, the value is a list
    multi, __multiSize, __ramp, __node           not supported, listed under "skipped"
    sepparm, spacer, __button, __dummy__         no value, ignored
"""



PARM_PREFIX = "houdiniAssetParm"
ATTR_PREFIX = PARM_PREFIX + "_"
VALUE = "value"
TUPLE = "tuple"
FOLDER = "folder"
IGNORED = "ignored"
UNSUPPORTED = "unsupported"
NUMERIC_COMPOUND_TYPES = {"float2", "float3", "double2", "double3", "long2", "long3", "short2", "short3"}
INT_TYPES = {"long", "short", "byte", "char", "enum"}
FLOAT_TYPES = {"float", "double", "doubleLinear", "doubleAngle", "time"}


def parm_name(attr: str) -> str:
    return attr[len(ATTR_PREFIX):] if attr.startswith(ATTR_PREFIX) else attr


def attr_name(parm: str) -> str:
    return ATTR_PREFIX + parm


def classify_attr(attr: str, attr_type: str | None, children: list, multi: bool) -> tuple[str, str]:
    """Return the kind of a houdiniAssetParm attribute and the reason for UNSUPPORTED.
    The reason is an empty string for every other kind."""
    if "sepparm" in attr or "spacer" in attr or "__dummy__" in attr or attr.endswith("__button"):
        return IGNORED, ""
    if attr.endswith("__multiSize"):
        return UNSUPPORTED, "multiparm (not supported)"
    if attr.endswith("__ramp"):
        return UNSUPPORTED, "ramp (not supported)"
    if attr.endswith("__node"):
        return UNSUPPORTED, "input node (not transferred)"
    if multi:
        return IGNORED, ""
    if attr_type in NUMERIC_COMPOUND_TYPES:
        return TUPLE, ""
    if (attr_type == "compound" and not attr.endswith("__folder") and children
            and all(child.startswith(attr) for child in children)):
        return TUPLE, ""
    if attr_type == "compound" or children:
        return FOLDER, ""
    return VALUE, ""


def convert_value(attr_type: str | None, value):
    """Convert a raw attribute value to the preset type for the Maya attribute type.
    Values of other attribute types are returned unchanged."""
    if attr_type == "bool":
        return bool(value)
    if attr_type in INT_TYPES:
        return int(round(float(value)))
    if attr_type in FLOAT_TYPES:
        return float(value)
    return value


def parse_enum_names(enum_string: str | None) -> dict[int, str]:
    """Map enum indices to labels, for example 'a:b=5:c' to {0: 'a', 5: 'b', 6: 'c'}."""
    result, index = {}, 0
    for item in (enum_string or "").split(":"):
        label, separator, number = item.partition("=")
        if separator:
            try:
                index = int(number)
            except ValueError:
                pass
        result[index] = label
        index += 1
    return result
