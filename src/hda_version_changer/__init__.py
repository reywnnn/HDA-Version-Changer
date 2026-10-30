"""Upgrade silo_gen Houdini Engine asset nodes in the open Maya scene to a chosen HDA version.

show() opens the dialog, run() upgrades the scene without it and reapply() writes a JSON backup
back to its node. install_shelf_button() and remove_shelf_button() put the tool on the open
shelf and take it off again. All of them need Maya. The package 'core' also works in plain
Python, 'scene' and 'ui' need Maya.
"""



__all__ = ["show", "run", "reapply", "install_shelf_button", "remove_shelf_button"]


def __getattr__(name):
    if name == "show":
        from .ui import dialog
        return dialog.show
    if name in ("install_shelf_button", "remove_shelf_button"):
        from .ui import shelf_button
        return getattr(shelf_button, name)
    if name in ("run", "reapply"):
        from .scene import upgrade
        return getattr(upgrade, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
