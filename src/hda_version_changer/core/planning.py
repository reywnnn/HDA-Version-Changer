"""Rules for versions, target paths, node names, renamed and ignored parameters and the status of an upgraded node.

The rules work without Maya, so the Maya modules only carry them out.
"""



import copy
import re
from .config import AssetFamily, UpgradeConfig
from .model import ApplyResult, NodePlan, NodeStatus, UpgradeTarget



OBSOLETE_SUFFIX = " (obsolete)"



def expand_project_path(otl_path: str, token: str, project_path: str) -> str:
    """Replace the project path token in an otlFilePath value with the project folder.
    Backslashes become forward slashes, and a path without the token only gets normalized."""
    path = otl_path.replace("\\", "/")
    if token not in path:
        return path
    root = project_path.replace("\\", "/").rstrip("/") + "/"
    return path.replace(token + "/", root).replace(token, root)


def display_path(otl_path: str, root: str) -> str:
    """Return an otlFilePath value without root and with backslashes, such as \\scs_industrial\\hda\\a.hda.
    A path that does not start with root is returned whole, only with backslashes."""
    path = otl_path.replace("\\", "/")
    root = root.replace("\\", "/").rstrip("/")
    if root and path.lower().startswith(root.lower() + "/"):
        path = path[len(root):]
    return path.replace("/", "\\")


def version_from_file_name(file_name: str, prefix: str) -> str | None:
    """Return the version in an HDA file name such as jandv.dev.silo_gen.1.1.hda.
    Returns None if the name does not start with prefix or the rest is not a version."""
    match = re.fullmatch(re.escape(prefix) + r"(\d+(?:\.\d+)*)\.hda", file_name, re.IGNORECASE)
    return match.group(1) if match else None


def version_from_asset_name(asset_name: str) -> str | None:
    """Return the version at the end of an operator name such as jandv.dev::Object/silo_gen::1.1.
    Returns None if the name does not end in a version."""
    match = re.fullmatch(r".*::(\d+(?:\.\d+)*)", asset_name)
    return match.group(1) if match else None


def version_key(version: str) -> tuple[int, ...]:
    """Return the numbers of a version, so that 1.10 sorts after 1.2 and 1.2.0 after 1.1."""
    return tuple(int(part) for part in version.split("."))


def sort_versions(versions: list[str]) -> list[str]:
    """Return the versions from the newest to the oldest, comparing them number by number."""
    return sorted(versions, key=version_key, reverse=True)


def find_family_versions(families: tuple[AssetFamily, ...], file_names: list[str]) -> dict[str, AssetFamily]:
    """Return every version the HDA file names offer and the family whose file holds it.
    Raises ValueError if files of two families have the same version."""
    found = {}
    for file_name in file_names:
        for family in families:
            version = version_from_file_name(file_name, family.file_prefix)
            if version is None:
                continue
            if found.get(version, family) != family:
                raise ValueError("Version %s has an HDA file of both %s and %s." % (version, found[version].name, family.name))
            found[version] = family
    return found


def version_label(version: str, newest: str) -> str:
    """Return the version as the version menu shows it, with (obsolete) after every version but the newest."""
    return version if version == newest else version + OBSOLETE_SUFFIX


def make_target(config: UpgradeConfig, family: AssetFamily, version: str, project_path: str) -> UpgradeTarget:
    asset = "%s::%s" % (family.name, version)
    file_name = "%s%s.hda" % (family.file_prefix, version)
    otl_path = config.hda_folder.rstrip("/") + "/" + file_name
    return UpgradeTarget(
        version=version,
        asset=asset,
        file_name=file_name,
        otl_path=otl_path,
        otl_path_abs=expand_project_path(otl_path, config.project_path_token, project_path),
        ignored_parms=dict(config.ignored_parms.get(asset, {})),
    )


def is_in_family(asset_name: str, families: tuple[AssetFamily, ...]) -> bool:
    """Check if the operator name is a version of one of the families."""
    return any(asset_name.startswith(family.name + "::") for family in families)


def is_older(asset_name: str, version: str) -> bool:
    """Check if the operator name ends in a lower version than the given one.
    Returns False if the operator name does not end in a version."""
    current = version_from_asset_name(asset_name)
    return current is not None and version_key(current) < version_key(version)


def find_duplicate_names(names: list[str]) -> list[str]:
    seen, duplicates = set(), set()
    for name in names:
        (duplicates if name in seen else seen).add(name)
    return sorted(duplicates)


def unique_node_name(base: str, taken: set[str]) -> str:
    """Return base, or the next name with a higher number that is not taken.
    A trailing number counts up with the same padding (silo_gen_002), otherwise 1, 2 … is appended (dev1)."""
    if base not in taken:
        return base
    prefix, number, width = _split_number(base)
    number += 1
    while "%s%0*d" % (prefix, width, number) in taken:
        number += 1
    return "%s%0*d" % (prefix, width, number)


def new_node_names(base: str, count: int, taken: set[str]) -> list[str]:
    """Return count new names built from base that differ from each other and from taken."""
    taken = set(taken)
    names = []
    for _ in range(count):
        name = unique_node_name(base, taken)
        taken.add(name)
        names.append(name)
    return names


def is_upgraded_name(name: str, base: str) -> bool:
    """Check if the name is one that unique_node_name builds from base."""
    prefix, _, width = _split_number(base)
    return name == base or re.fullmatch(re.escape(prefix) + r"\d{%d,}" % max(width, 1), name) is not None


def rename_parms(preset: dict, renamed_parms: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Return a copy of the preset with old parameter names replaced by new ones, and the names it replaced.
    An old name stays if the preset already holds the new name."""
    result = copy.deepcopy(preset)
    parameters = result["parameters"]
    labels = result.get("menu_labels") or {}
    renamed = {}
    for old, new in renamed_parms.items():
        if old not in parameters or new in parameters:
            continue
        parameters[new] = parameters.pop(old)
        if old in labels:
            labels[new] = labels.pop(old)
        renamed[old] = new
    return result, renamed


def prepare_preset(preset: dict, renamed_parms: dict[str, str], ignored_parms: dict[str, str]) -> tuple[dict, dict[str, str], dict[str, str]]:
    """Return the preset as it is written to the target, the parameters renamed in it and the ignored ones it held.
    Old names are replaced first, so ignored_parms name parameters of the target version."""
    renamed_preset, renamed = rename_parms(preset, renamed_parms)
    cleaned, ignored = split_ignored(renamed_preset, ignored_parms)
    return cleaned, renamed, ignored


def split_ignored(preset: dict, ignored_parms: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Return a copy of the preset without the ignored parameters, and the ignored parameters it held.
    The second value maps each ignored parameter to the reason it is ignored."""
    result = copy.deepcopy(preset)
    found = {}
    for parm in list(result["parameters"]):
        if parm in ignored_parms:
            del result["parameters"][parm]
            (result.get("menu_labels") or {}).pop(parm, None)
            found[parm] = ignored_parms[parm]
    return result, found


def status_after_upgrade(apply: ApplyResult, renamed: bool) -> NodeStatus:
    """Return the status of a node whose version switch succeeded."""
    if apply.missing or apply.problems or apply.mismatched or not renamed:
        return NodeStatus.UPGRADED_WITH_PROBLEMS
    return NodeStatus.UPGRADED


def build_plans(
    nodes: list,
    presets: dict[str, dict],
    target: UpgradeTarget,
    new_node_name: str,
    taken_names: set[str],
    backup_paths: dict[str, str],
) -> list[NodePlan]:
    """Plan the upgrade of every node and give each node a new name that no other node has.
    Each item of nodes needs the attributes name, uuid and otl_path."""
    names = new_node_names(new_node_name, len(nodes), taken_names)
    return [
        NodePlan(
            uuid=node.uuid,
            original_name=node.name,
            source_otl=node.otl_path,
            target_otl=target.otl_path,
            target_otl_abs=target.otl_path_abs,
            preset=presets[node.name],
            backup_path=backup_paths[node.name],
            new_name=new_name,
        )
        for node, new_name in zip(nodes, names)
    ]


def _split_number(base: str) -> tuple[str, int, int]:
    """Return the base without its trailing number, the number and its digit count.
    Returns the whole base, 0 and 0 if the base does not end in a number."""
    match = re.fullmatch(r"(.*?)(\d+)", base)
    if not match:
        return base, 0, 0
    return match.group(1), int(match.group(2)), len(match.group(2))
