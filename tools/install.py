"""Install HDA Version Changer into Maya.

The installer writes a Maya module file into the trunk's maya/modules folder, which Maya reads at
startup. The file stays on this machine and is not committed. The module file makes Maya add 'src'
to sys.path and 'icons' to XBMLANGPATH. The installer does not change userSetup.py or any other
shared file. The installer also puts the tool on the open shelf. The module file points to the
folder this file is in, so moving that folder breaks the install.
"""



import os



MODULE_NAME = "hda_version_changer"
MODULE_VERSION = "0.0.0.000"
PACKAGES = ("hda_version_changer", "hda_presets")


def install_root():
    return os.path.dirname(os.path.abspath(__file__))


def trunk_modules_dir():
    """Find the trunk's Maya modules folder, which Maya reads at startup.
    Returns None and the reason if PRISM_PROJECT_PATH is not set or the folder does not exist."""
    project_path = os.environ.get("PRISM_PROJECT_PATH")
    if not project_path:
        return None, ("PRISM_PROJECT_PATH is not set, so the trunk's maya\\modules folder cannot "
                      "be found. Start Maya the way prism expects.")

    modules_dir = os.path.join(project_path, "maya", "modules")
    if not os.path.isdir(modules_dir):
        return None, ("'%s' does not exist, so PRISM_PROJECT_PATH ('%s') does not point at the "
                      "trunk." % (modules_dir, project_path))
    return modules_dir, ""


def module_file_path():
    """Return the path of the .mod file in the trunk's Maya modules folder.
    Returns None and the reason if the modules folder cannot be found."""
    modules_dir, detail = trunk_modules_dir()
    if modules_dir is None:
        return None, detail
    return os.path.join(modules_dir, MODULE_NAME + ".mod"), ""


def build_module_file(root, modules_dir):
    """Return the text of the .mod file for the tool installed in the given folder.
    The path is relative to the modules folder, unless the tool is on another drive."""
    try:
        path = os.path.relpath(root, modules_dir)
    except ValueError:
        path = root
    return "\n".join([
        "+ %s %s %s" % (MODULE_NAME, MODULE_VERSION, path.replace("\\", "/")),
        "scripts: src",
        "icons: icons",
        "",
    ])


def use_this_copy(root):
    """Put this copy's 'src' folder first on sys.path and drop any copy that is already imported.
    Returns the names of the dropped modules if a copy was already imported."""
    import sys

    source = os.path.join(root, "src")
    while source in sys.path:
        sys.path.remove(source)
    sys.path.insert(0, source)

    loaded = sorted(name for name in sys.modules if name.split(".")[0] in PACKAGES)
    for name in loaded:
        del sys.modules[name]
    return loaded


def install():
    """Write the module file, put the tool on the open shelf and print what happened.
    Returns False if one of the steps fails."""
    root = install_root()
    package = os.path.join(root, "src", MODULE_NAME, "__init__.py")
    if not os.path.isfile(package):
        print("HDA Version Changer: no package at '%s'. Run this from the folder the archive "
              "was extracted to." % os.path.join(root, "src"))
        return False

    path, detail = module_file_path()
    if path is None:
        print("HDA Version Changer: %s" % detail)
        return False

    try:
        with open(path, "w") as f:
            f.write(build_module_file(root, os.path.dirname(path)))
    except (IOError, OSError) as error:
        print("HDA Version Changer: could not write '%s': %s" % (path, error))
        return False
    print("HDA Version Changer: wrote %s" % path)

    dropped = use_this_copy(root)
    if dropped:
        print("HDA Version Changer: replaced %d module(s) an earlier copy had loaded" % len(dropped))

    try:
        import hda_version_changer
        added, button_detail = hda_version_changer.install_shelf_button()
    except Exception as error:
        print("HDA Version Changer: the module file is written, but the package could not be "
              "imported in this session: %s. Restart Maya." % error)
        return False
    print("HDA Version Changer: %s" % button_detail)

    print("HDA Version Changer: installed. Restart Maya once so the module is picked up at "
          "startup; the shelf button works in this session already.")
    return added


def uninstall():
    """Remove the module file and the shelf button, and print what happened.
    Returns False if the module file was not removed."""
    path, detail = module_file_path()
    if path is None:
        print("HDA Version Changer: %s" % detail)
        return False

    removed_module = False
    if os.path.isfile(path):
        try:
            os.remove(path)
            removed_module = True
            print("HDA Version Changer: removed %s" % path)
        except OSError as error:
            print("HDA Version Changer: could not remove '%s': %s" % (path, error))
    else:
        print("HDA Version Changer: no module file at %s" % path)

    try:
        import hda_version_changer
        _, button_detail = hda_version_changer.remove_shelf_button()
        print("HDA Version Changer: %s" % button_detail)
    except Exception as error:
        print("HDA Version Changer: the shelf button was not removed (%s). Remove it by hand "
              "if it is still there." % error)

    return removed_module


def onMayaDroppedPythonFile(*args):
    """Install the tool when this file is dragged into a Maya viewport, which calls this function.
    Afterwards this file leaves sys.modules, so the next dropped install.py runs its own code."""
    import sys

    try:
        install()
    finally:
        sys.modules.pop(__name__, None)


if __name__ == "__main__":
    install()
