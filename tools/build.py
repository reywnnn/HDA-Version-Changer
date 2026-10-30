"""Package the tool into an installable zip.

A test build goes to build/ and keeps the version. A MAJOR, MINOR or PATCH release goes to dist/
and raises that part of the version. Every build adds 1 to the build number. Both numbers are
stored in tools/version.json, together with an optional identifier such as 'alpha' that goes
between the version and the build number (0.0.1-alpha.004). A release also turns the Unreleased
section of tools/CHANGELOG.md into the section of that release. The archive carries the released sections of the changelog as
plain text in changelog.txt.
"""



import argparse
import datetime
import json
import os
import re
import shutil
import sys
import zipfile



ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD = os.path.join(ROOT, "build")

DIST = os.path.join(ROOT, "dist")

STATE_FILE = os.path.join(ROOT, "tools", "version.json")

ARCHIVE_PREFIX = "HDA_Version_Changer_"

INITIAL_VERSION = "0.0.0"

RELEASE_PARTS = ("major", "minor", "patch")

PACKAGE_DIRS = [
    ("src/hda_version_changer", ".py"),
    ("src/hda_presets", ".py"),
    ("icons", ".svg"),
]

STAMPED_FILES = [
    "tools/install.py",
]

CHANGELOG_FILE = "tools/CHANGELOG.md"

CHANGELOG_ARCHIVE_NAME = "changelog.txt"

EXTRA_FILES = [
    CHANGELOG_FILE,
]

REQUIRED_FILES = (
    "src/hda_version_changer/__init__.py",
    "src/hda_version_changer/core/__init__.py",
    "src/hda_version_changer/scene/upgrade.py",
    "src/hda_version_changer/ui/dialog.py",
    "src/hda_version_changer/ui/shelf_button.py",
    "src/hda_presets/__init__.py",
    "src/hda_presets/node_writer.py",
    "icons/hda_version_changer.svg",
    "install.py",
    CHANGELOG_ARCHIVE_NAME,
)

CHANGELOG_TITLES = {
    "major": "MAJOR, Not Backward Compatible",
    "minor": "MINOR, New Functionality",
    "patch": "PATCH, Bug Fixes",
}

UNRELEASED_RE = re.compile(r"^## Unreleased[ \t]*\r?\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)

HEADING_MARK_RE = re.compile(r"^#+[ \t]*")

EXCLUDED_NAMES = ("__pycache__",)

MODULE_VERSION_RE = re.compile(r'^MODULE_VERSION = "[^"]*".*$', re.MULTILINE)

IDENTIFIER_RE = re.compile(r"[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*")


# === version state =================================================================


def read_state(path: str | None = None) -> dict:
    """Read the version, the build number and the optional identifier from tools/version.json.
    Returns INITIAL_VERSION and build number 0 if the file does not exist."""
    path = path or STATE_FILE
    state = {"version": INITIAL_VERSION, "buildNumber": 0, "releases": []}
    if not os.path.isfile(path):
        return state
    with open(path, "r", encoding="utf-8-sig") as f:
        stored = json.load(f)
    if not isinstance(stored, dict):
        raise ValueError("%s does not hold an object" % path)

    state.update(stored)
    parse_version(state["version"])
    if not isinstance(state["buildNumber"], int) or state["buildNumber"] < 0:
        raise ValueError("%s: buildNumber must be a non-negative integer, got %r" % (path, state["buildNumber"]))
    if not isinstance(state["releases"], list):
        raise ValueError("%s: releases must be a list" % path)
    identifier = state.get("identifier")
    if identifier and (not isinstance(identifier, str) or not IDENTIFIER_RE.fullmatch(identifier)):
        raise ValueError("%s: identifier must be letters, digits, '-' and '.', such as 'alpha', got %r"
                         % (path, identifier))
    title = state.get("identifierTitle")
    if title is not None and not isinstance(title, str):
        raise ValueError("%s: identifierTitle must be text, such as 'Early Development Version', got %r" % (path, title))
    return state


def write_state(state: dict, path: str | None = None) -> None:
    path = path or STATE_FILE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, sort_keys=True)
        f.write("\n")


def parse_version(version: str) -> tuple[int, int, int]:
    parts = str(version).split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("not a major.minor.patch version: %r" % (version,))
    return tuple(int(part) for part in parts)


def format_version(parts: tuple[int, int, int]) -> str:
    return "%d.%d.%d" % tuple(parts)


def bump_version(version: str, part: str) -> str:
    """Raise the given part of the version and set the parts after it to 0."""
    major, minor, patch = parse_version(version)
    if part == "major":
        return format_version((major + 1, 0, 0))
    if part == "minor":
        return format_version((major, minor + 1, 0))
    return format_version((major, minor, patch + 1))


def format_label(version: str, identifier: str | None = None) -> str:
    """Return the version with the identifier, such as 0.0.1-alpha, or the version alone if there is no identifier."""
    return "%s-%s" % (version, identifier) if identifier else version


def format_stamp(version: str, build_number: int, identifier: str | None = None) -> str:
    return "%s.%03d" % (format_label(version, identifier), build_number)


def plan_test_build(state: dict) -> tuple[str, dict]:
    """Return the stamp and the new version state for the next test build.
    The state passed in stays as it is, because a failed build must not use up a build number."""
    build_number = state["buildNumber"] + 1
    stamp = format_stamp(state["version"], build_number, state.get("identifier"))
    return stamp, dict(state, buildNumber=build_number)


def plan_release(state: dict, part: str) -> tuple[str, dict]:
    """Return the stamp and the new version state for the next release of the given part."""
    build_number = state["buildNumber"] + 1
    version = bump_version(state["version"], part)
    stamp = format_stamp(version, build_number, state.get("identifier"))
    next_state = dict(state, version=version, buildNumber=build_number, releases=list(state["releases"]) + [stamp])
    return stamp, next_state


def print_preview(state: dict) -> None:
    """Print the zip that each task would build next."""
    print("Version %s, build %d. Next:" % (format_label(state["version"], state.get("identifier")), state["buildNumber"]))
    for part in RELEASE_PARTS:
        stamp, _ = plan_release(state, part)
        print("  %s  %s%s%s%s.zip" % (part.upper(), os.path.relpath(DIST, ROOT), os.sep, ARCHIVE_PREFIX, stamp))
    stamp, _ = plan_test_build(state)
    print("  BUILD  %s%s%s%s.zip" % (os.path.relpath(BUILD, ROOT), os.sep, ARCHIVE_PREFIX, stamp))
    print("Nothing was written and %s is unchanged." % os.path.relpath(STATE_FILE, ROOT))


# === contents ======================================================================


def collect() -> list[tuple[str, str]]:
    """Return (file path, path in the archive) for every file from PACKAGE_DIRS.
    Raises IOError if a folder or a file that goes into the archive is missing."""
    entries = []

    for relative_dir, extension in PACKAGE_DIRS:
        source_dir = os.path.join(ROOT, relative_dir.replace("/", os.sep))
        if not os.path.isdir(source_dir):
            raise IOError("missing folder: %s" % source_dir)
        for dir_path, dir_names, file_names in os.walk(source_dir):
            dir_names[:] = [name for name in dir_names if name not in EXCLUDED_NAMES]
            for file_name in sorted(file_names):
                if not file_name.endswith(extension):
                    continue
                absolute = os.path.join(dir_path, file_name)
                entries.append((absolute, os.path.relpath(absolute, ROOT).replace(os.sep, "/")))

    for relative_file in STAMPED_FILES + EXTRA_FILES:
        absolute = os.path.join(ROOT, relative_file.replace("/", os.sep))
        if not os.path.isfile(absolute):
            raise IOError("missing file: %s" % absolute)

    return entries


def stamp_installer(text: str, stamp: str) -> str:
    stamped, count = MODULE_VERSION_RE.subn('MODULE_VERSION = "%s"' % stamp, text)
    if count != 1:
        raise ValueError("expected one MODULE_VERSION line in install.py, found %d" % count)
    return stamped


def read_changelog() -> str:
    """Return the text of the changelog, keeping its line endings.
    Returns an empty string if the changelog does not exist."""
    path = os.path.join(ROOT, CHANGELOG_FILE.replace("/", os.sep))
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_changelog(text: str) -> None:
    with open(os.path.join(ROOT, CHANGELOG_FILE.replace("/", os.sep)), "w", encoding="utf-8", newline="") as f:
        f.write(text)


def identifier_title(state: dict) -> str | None:
    """Return the identifierTitle of the state, such as 'Early Development Version'.
    Returns None if the state has no identifier or no identifierTitle."""
    title = (state.get("identifierTitle") or "").strip()
    return title if state.get("identifier") and title else None


def release_changelog(text: str, version: str, part: str, date: str, title: str | None = None) -> str | None:
    """Rename the Unreleased section to the release's heading and open a new empty one above it.
    Returns None if the Unreleased section is missing or empty."""
    match = UNRELEASED_RE.search(text)
    if match is None or not match.group(1).strip():
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    description = "%s, %s" % (part.upper(), title) if title else CHANGELOG_TITLES[part]
    heading = "## %s (%s) - %s" % (version, date, description)
    return "%s## Unreleased%s%s%s%s%s%s" % (
        text[:match.start()], newline, newline, heading, newline, match.group(1), text[match.end():])


def released_changelog_text(text: str) -> str:
    """Turn the changelog into the plain text that goes into the archive as changelog.txt.
    The Unreleased section is left out, so the text describes only released versions."""
    text = UNRELEASED_RE.sub("", text.replace("\r\n", "\n"))
    lines = [HEADING_MARK_RE.sub("", line).replace("`", "").rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip("\n") + "\n"


def build(stamp: str, output_dir: str, changelog: str | None = None) -> str:
    """Write the archive into output_dir, print what went into it, and return its path.
    A given changelog text goes into the archive instead of the changelog file."""
    entries = collect()
    os.makedirs(output_dir, exist_ok=True)

    target = os.path.join(output_dir, "%s%s.zip" % (ARCHIVE_PREFIX, stamp))
    if os.path.exists(target):
        os.remove(target)

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for absolute, archive_name in entries:
            archive.write(absolute, archive_name)

        for relative_file in STAMPED_FILES:
            absolute = os.path.join(ROOT, relative_file.replace("/", os.sep))
            with open(absolute, "r", encoding="utf-8") as f:
                archive.writestr(os.path.basename(absolute), stamp_installer(f.read(), stamp))

        for relative_file in EXTRA_FILES:
            absolute = os.path.join(ROOT, relative_file.replace("/", os.sep))
            if relative_file == CHANGELOG_FILE:
                text = changelog if changelog is not None else read_changelog()
                archive.writestr(CHANGELOG_ARCHIVE_NAME, released_changelog_text(text))
            else:
                archive.write(absolute, os.path.basename(absolute))

    print("Built %s" % target)
    print("  %d files, %.0f KB" % (len(entries) + len(STAMPED_FILES) + len(EXTRA_FILES),
                                   os.path.getsize(target) / 1024.0))
    for _, archive_name in entries:
        print("    %s" % archive_name)
    for relative_file in STAMPED_FILES:
        print("    %s  (stamped %s)" % (os.path.basename(relative_file), stamp))
    for relative_file in EXTRA_FILES:
        print("    %s" % (CHANGELOG_ARCHIVE_NAME if relative_file == CHANGELOG_FILE else os.path.basename(relative_file)))
    return target


def verify(target: str, stamp: str) -> bool:
    """Check the archive contents and the install.py stamp, and print each problem.
    Returns False if the archive has a problem."""
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        installer = archive.read("install.py").decode("utf-8") if "install.py" in names else ""

    problems = ["missing: %s" % required for required in REQUIRED_FILES if required not in names]
    if installer and 'MODULE_VERSION = "%s"' % stamp not in installer:
        problems.append("install.py is not stamped %s" % stamp)

    for name in names:
        if name.startswith(("tests/", "docs/", "tools/", "build/", "dist/")):
            problems.append("should not be in the build: %s" % name)
        if "__pycache__" in name or name.endswith(".pyc"):
            problems.append("bytecode in the build: %s" % name)

    for problem in problems:
        print("  FAIL  %s" % problem)
    if not problems:
        print("  Verified: the packages, the icon and the installer stamped %s, with no tests and no docs." % stamp)
    return not problems


# === entry point ===================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="Package HDA Version Changer.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--major", action="store_const", const="major", dest="mode",
                      help="MAJOR release into dist/: major + 1, minor and patch 0, build number + 1")
    mode.add_argument("--minor", action="store_const", const="minor", dest="mode",
                      help="MINOR release into dist/: minor + 1, patch 0, build number + 1")
    mode.add_argument("--patch", action="store_const", const="patch", dest="mode",
                      help="PATCH release into dist/: patch + 1, build number + 1")
    mode.add_argument("--test", action="store_const", const="build", dest="mode",
                      help="test build into build/: same version, build number + 1")
    mode.add_argument("--preview", action="store_const", const="preview", dest="mode",
                      help="print what each task would build and write nothing")
    parser.add_argument("--clean", action="store_true",
                        help="delete build/ first; refused with a release, which would lose dist/")
    args = parser.parse_args()

    if args.clean and args.mode in RELEASE_PARTS:
        print("--clean is refused with --%s: it would delete every earlier release in dist/." % args.mode)
        return 1

    try:
        state = read_state()
    except (ValueError, IOError, OSError) as error:
        print("Cannot read %s: %s" % (os.path.relpath(STATE_FILE, ROOT), error))
        print("It holds the version and the build number. Fix it by hand, or delete it to start "
              "again from version %s build 0." % INITIAL_VERSION)
        return 1

    if args.mode == "preview":
        print_preview(state)
        return 0

    if args.mode == "build":
        stamp, next_state = plan_test_build(state)
        output_dir = BUILD
    else:
        stamp, next_state = plan_release(state, args.mode)
        output_dir = DIST
    label = format_label(next_state["version"], next_state.get("identifier"))

    changelog = None
    if args.mode in RELEASE_PARTS:
        changelog = release_changelog(read_changelog(), label, args.mode,
                                      datetime.date.today().strftime("%d.%m.%Y"), identifier_title(next_state))
        if changelog is None:
            print('Nothing to release: the "## Unreleased" section in tools/CHANGELOG.md is empty.')
            return 1

    print("%s: %s%s.zip" % (args.mode.upper(), ARCHIVE_PREFIX, stamp))
    print("  version %s   build %d   into %s%s\n" % (
        label, next_state["buildNumber"], os.path.relpath(output_dir, ROOT), os.sep))

    if args.clean and os.path.isdir(output_dir):
        shutil.rmtree(output_dir)
        print("Removed %s\n" % output_dir)

    target = build(stamp, output_dir, changelog)
    if not verify(target, stamp):
        print("\nThe archive is wrong, so %s was left alone. Fix it and build again." % os.path.relpath(STATE_FILE, ROOT))
        return 1

    if changelog is not None:
        write_changelog(changelog)
    write_state(next_state)
    print("\n%s now reads version %s, build %d." % (
        os.path.relpath(STATE_FILE, ROOT), label, next_state["buildNumber"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
