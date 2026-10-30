"""Check the open Maya scene, find its Houdini Engine asset nodes, list and load HDA libraries."""



import os
import maya.cmds as cmds
import maya.mel as mel



def scene_path() -> str:
    """Return the path of the open scene.
    Raises RuntimeError if the scene is not saved as a Maya ASCII file."""
    path = cmds.file(query=True, sceneName=True)
    if not path or not path.lower().endswith(".ma"):
        raise RuntimeError("The scene must be saved as a Maya ASCII (.ma) file first (scene: %s)." % (path or "not saved"))
    return path


def has_unsaved_changes() -> bool:
    return bool(cmds.file(query=True, modified=True))


def environment_path(variable: str) -> str:
    """Return the value of an environment variable that holds a folder.
    Raises RuntimeError if the variable is not set."""
    value = os.environ.get(variable)
    if not value:
        raise RuntimeError("The environment variable %s is not set." % variable)
    return value


def find_asset_nodes() -> list[str]:
    """Return the long names of all houdiniAsset nodes."""
    return cmds.ls(type="houdiniAsset", long=True) or []


def list_hda_files(folder: str) -> list[str]:
    """Return the names of the .hda files directly in the folder, without subfolders.
    Returns an empty list if the folder does not exist."""
    if not os.path.isdir(folder):
        return []
    return [name for name in os.listdir(folder)
            if name.lower().endswith(".hda") and os.path.isfile(os.path.join(folder, name))]


def long_name(node: str) -> str:
    """Return the long name of the node.
    Raises RuntimeError if no node or more than one node has the name."""
    found = cmds.ls(node, long=True) or []
    if len(found) != 1:
        raise RuntimeError("%d node(s) are named %s." % (len(found), node))
    return found[0]


def nodes_by_uuid(uuid: str) -> list[str]:
    return cmds.ls(uuid, long=True) or []


def node_uuid(node: str) -> str:
    """Return the UUID of the node, or an empty string if the node does not exist."""
    return (cmds.ls(node, uuid=True) or [""])[0]


def node_asset_name(node: str) -> str:
    return cmds.getAttr(node + ".assetName") or ""


def node_otl_path(node: str) -> str:
    return cmds.getAttr(node + ".otlFilePath") or ""


def short_name(node: str) -> str:
    return node.split("|")[-1]


def taken_short_names() -> set[str]:
    return {short_name(node) for node in cmds.ls(long=True) or []}


def load_hda_library(path: str) -> list[str]:
    """Load an .hda file into the Houdini Engine session and return the operator names it defines.
    Raises RuntimeError if Houdini Engine cannot read the file."""
    operators = cmds.houdiniAsset(listAssets=path) or []
    try:
        mel.eval('houdiniEngineAssetLibraryManager_addLoadedFile("%s");' % path)
    except RuntimeError:
        pass
    return operators
