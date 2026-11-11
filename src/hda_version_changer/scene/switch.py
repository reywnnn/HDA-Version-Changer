"""Switch a Houdini Engine asset node to another HDA definition and rename it."""



import maya.cmds as cmds
from hda_presets import node_writer



def switch_version(node: str, asset_name: str, otl_path: str) -> None:
    """Point the node to another HDA definition and sync it.
    If the sync fails, the node gets its old assetName and otlFilePath back and RuntimeError is raised."""
    old_asset_name = cmds.getAttr(node + ".assetName") or ""
    old_otl_path = cmds.getAttr(node + ".otlFilePath") or ""

    node_writer.suspend_sync_jobs(node)
    _point_to(node, asset_name, otl_path)
    try:
        node_writer.sync(node)
    except Exception as error:
        _point_to(node, old_asset_name, old_otl_path)
        try:
            node_writer.sync(node)
        except Exception:
            pass
        raise RuntimeError("The sync with %s failed and the node points to %s again: %s"
                           % (asset_name, old_asset_name, error)) from error

    current = cmds.getAttr(node + ".assetName") or ""
    if current != asset_name:
        raise RuntimeError("After the sync the node reports assetName %r instead of %r." % (current, asset_name))


def rename_node(node: str, new_name: str) -> str:
    """Rename the node and return the name Maya gave it.
    Maya adds a number if another node already has new_name."""
    return cmds.rename(node, new_name).split("|")[-1]


def _point_to(node: str, asset_name: str, otl_path: str) -> None:
    """Set the node's operator and HDA file, so that Houdini Engine creates the asset only once, from the right file.
    Houdini Engine creates the asset again after each of the two values changes, unless assetName is empty."""
    cmds.setAttr(node + ".assetName", "", type="string")
    cmds.setAttr(node + ".otlFilePath", otl_path, type="string")
    cmds.setAttr(node + ".assetName", asset_name, type="string")
