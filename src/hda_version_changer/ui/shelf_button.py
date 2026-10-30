"""Add the Maya shelf button that opens the dialog, and read the version of the installed build.

The button goes on the shelf tab that is open and points back at the folder it was installed
from. Installing again replaces the button in place, so a code change never leaves two buttons
behind. In the development folder the button drops the imported modules of the tool before it
opens the dialog, so every click runs the code as it is on disk.
"""



import os
import re
import maya.cmds as cmds
import maya.mel as mel



MARKER = "# hda_version_changer shelf button"

BUTTON_LABEL = "HDA Version Changer"

BUTTON_ANNOTATION = "HDA Version Changer - switch a silo_gen node to another HDA version and keep its parameter values"

ICON_FILENAME = "hda_version_changer.svg"

_FALLBACK_ICON = "commandButton.png"

PACKAGES = ("hda_version_changer", "hda_presets")

_PACKAGE_DEPTH = 4

_MODULE_VERSION_RE = re.compile(r'^MODULE_VERSION = "([^"]*)"', re.MULTILINE)


def get_repository_root() -> str:
    path = os.path.abspath(__file__)
    for _ in range(_PACKAGE_DEPTH):
        path = os.path.dirname(path)
    return path


def get_source_dir() -> str:
    """Return the folder that has to be on sys.path for the tool to import."""
    return os.path.join(get_repository_root(), "src")


def get_icon_path(filename: str | None = None) -> tuple[str, bool]:
    """Return the icon's path and check if the file exists."""
    path = os.path.join(get_repository_root(), "icons", filename or ICON_FILENAME).replace("\\", "/")
    return path, os.path.isfile(path)


def is_development_checkout() -> bool:
    """Check if the tool runs from the development folder, not from an installed build."""
    return os.path.isdir(os.path.join(get_repository_root(), "tests"))


def get_installed_version(root: str | None = None) -> str | None:
    """Return the build stamp of the installed build, such as '0.1.3.046'.
    Returns None if the folder has no install.py, as the development folder has none."""
    path = os.path.join(root or get_repository_root(), "install.py")
    try:
        with open(path, "r", encoding="utf-8") as f:
            match = _MODULE_VERSION_RE.search(f.read())
    except (IOError, OSError, UnicodeDecodeError):
        return None
    return match.group(1) if match is not None else None


def build_button_command(dev_reload: bool | None = None) -> str:
    """Return what the shelf button runs, which puts the tool first on sys.path and opens the dialog.
    In the development folder, the button also drops the imported modules of the tool first."""
    if dev_reload is None:
        dev_reload = is_development_checkout()

    lines = [
        MARKER,
        "import sys",
        "SRC = r\"%s\"" % get_source_dir(),
        "if SRC in sys.path:",
        "    sys.path.remove(SRC)",
        "sys.path.insert(0, SRC)",
    ]
    if dev_reload:
        lines += [
            "for name in [name for name in sys.modules if name.split('.')[0] in %r]:" % (PACKAGES,),
            "    del sys.modules[name]",
        ]
    lines += [
        "",
        "import hda_version_changer",
        "hda_version_changer.show()",
        "",
    ]
    return "\n".join(lines)


def get_current_shelf() -> tuple[str | None, str]:
    """Find the shelf tab that is open in Maya and return its name.
    Returns None and the reason if no shelf is open."""
    try:
        top_level = mel.eval("$tmpHdaVersionChangerShelfTop = $gShelfTopLevel")
    except Exception as error:
        return None, "Maya's shelf layout could not be looked up: %s" % error
    if not top_level or not cmds.tabLayout(top_level, exists=True):
        return None, ("Maya has no shelf layout in this session ($gShelfTopLevel is empty), which is "
                      "what batch mode looks like. There is no shelf to add a button to.")

    shelf_name = cmds.tabLayout(top_level, query=True, selectTab=True)
    if not shelf_name:
        return None, "No shelf tab is open, so there is nowhere to put the button."
    return shelf_name, ""


def find_existing_buttons(shelf_name: str) -> list[str]:
    """Find the tool's buttons on the shelf and return their names in shelf order."""
    buttons = []
    for child in cmds.shelfLayout(shelf_name, query=True, childArray=True) or []:
        try:
            if cmds.objectTypeUI(child) != "shelfButton":
                continue
            command = cmds.shelfButton(child, query=True, command=True) or ""
        except Exception:
            continue
        if MARKER in command:
            buttons.append(child)
    return buttons


def install_shelf_button(shelf_name: str | None = None, save: bool = True) -> tuple[bool, str]:
    """Add the tool's button to a shelf, replacing an existing one.
    Returns False and the reason if the button could not be added."""
    if shelf_name is None:
        shelf_name, detail = get_current_shelf()
        if shelf_name is None:
            return False, detail

    if not cmds.shelfLayout(shelf_name, exists=True):
        return False, "There is no shelf called '%s'." % shelf_name

    icon_path, icon_exists = get_icon_path()
    if not icon_exists:
        icon_path = _FALLBACK_ICON

    existing = find_existing_buttons(shelf_name)
    command = build_button_command()
    settings = dict(image=icon_path, image1=icon_path, label=BUTTON_LABEL, annotation=BUTTON_ANNOTATION,
                    imageOverlayLabel="", command=command, sourceType="python")

    try:
        if existing:
            cmds.shelfButton(existing[0], edit=True, **settings)
            for surplus in existing[1:]:
                cmds.deleteUI(surplus)
            verb = "Updated the existing button on"
            if len(existing) > 1:
                verb = "Updated the button and removed %d duplicate(s) on" % (len(existing) - 1)
        else:
            cmds.shelfButton(parent=shelf_name, **settings)
            verb = "Added a button to"
    except Exception as error:
        return False, "Could not put the button on '%s': %s" % (shelf_name, error)

    detail = "%s the '%s' shelf." % (verb, shelf_name)
    if not icon_exists:
        detail += " The icon '%s' was not found beside the tool, so a stock Maya icon was used." % ICON_FILENAME

    if save:
        error = save_shelves()
        if error is not None:
            detail += (" The button is on the shelf but the shelves could not be saved (%s), so it will be "
                       "gone after a restart. Saving them by hand from the shelf menu fixes that." % error)
    return True, detail


def save_shelves() -> Exception | None:
    """Save the shelves, so a change to the button survives a restart.
    Returns the error if the shelves could not be saved."""
    try:
        mel.eval("saveAllShelves $gShelfTopLevel")
    except Exception as error:
        return error
    return None


def remove_shelf_button(shelf_name: str | None = None, save: bool = True) -> tuple[bool, str]:
    """Remove the tool's buttons from a shelf.
    Returns False and the reason if no button could be removed."""
    if shelf_name is None:
        shelf_name, detail = get_current_shelf()
        if shelf_name is None:
            return False, detail

    existing = find_existing_buttons(shelf_name)
    if not existing:
        return False, "There is no HDA Version Changer button on the '%s' shelf." % shelf_name

    for button in existing:
        try:
            cmds.deleteUI(button)
        except Exception as error:
            return False, "Could not remove the button: %s" % error

    detail = "Removed %d button(s) from the '%s' shelf." % (len(existing), shelf_name)
    if save:
        error = save_shelves()
        if error is not None:
            detail += (" The shelves could not be saved (%s), so the button will be back after a restart. "
                       "Saving them by hand from the shelf menu fixes that." % error)
    return True, detail
