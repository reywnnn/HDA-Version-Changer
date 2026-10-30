"""Folder, file names, writing and reading of the JSON backups taken before an upgrade.

A backup is an hda_presets preset of one node with the optional fields source.node_uuid and
upgrade, so reapply() can find the node again after it was renamed.
"""



import os
from hda_presets import core
from .model import NodePlan



def default_backup_dir(scene_path: str, local_app_data: str) -> str:
    return os.path.join(local_app_data, "hda_version_changer", "backups", _scene_stem(scene_path))


def backup_path(folder: str, scene_path: str, node_name: str, taken: set[str] = frozenset(), exists=os.path.exists) -> str:
    """Return a free backup file path for a node.
    If the file exists or the path is in taken, the suffix __2, __3 and so on is added."""
    stem = "%s__%s" % (_scene_stem(scene_path), node_name.split("|")[-1].replace(":", "_"))
    path = os.path.join(folder, stem + core.FILE_SUFFIX)
    number = 2
    while exists(path) or path in taken:
        path = os.path.join(folder, "%s__%d%s" % (stem, number, core.FILE_SUFFIX))
        number += 1
    return path


def backup_preset(plan: NodePlan, target_asset: str) -> dict:
    """Return the preset of the plan extended by the upgrade object that describes the plan."""
    preset = dict(plan.preset)
    preset["upgrade"] = {
        "target_asset": target_asset,
        "target_library": plan.target_otl,
        "new_node_name": plan.new_name,
    }
    return core.validate(preset)


def write_backup(plan: NodePlan, target_asset: str) -> str:
    return core.save(backup_preset(plan, target_asset), plan.backup_path)


def read_backup(path: str) -> dict:
    """Load a backup and check that it identifies its node by UUID.
    Raises ValueError if the backup has no source.node_uuid."""
    preset = core.load(path)
    if not (preset.get("source") or {}).get("node_uuid"):
        raise ValueError("The backup %s has no source.node_uuid." % path)
    return preset


def _scene_stem(scene_path: str) -> str:
    return os.path.splitext(os.path.basename(scene_path))[0]
