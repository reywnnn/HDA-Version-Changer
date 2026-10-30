# Changelog

## Unreleased

## 0.1.0-beta (30.10.2026) - MINOR, Pre-release Testing Version

- The tool is ready to move into the beta testing phase.

- The parameter library `hda_parms` is renamed to `hda_presets`, and its modules are renamed
  and split, because the old short names did not say what the code does.

- The library works with presets, so its name now says so. It is also no longer the original
  `hda_parms` library by Arthur Novotný: most of its code has been rewritten for this tool.

- `maya_ma` is now `scene_reader`, which reads the values from the saved `.ma` file, and
  `maya_io` is now `node_writer`, which writes them to the node in Maya.

- The rules for Houdini Engine attributes that both use moved to the new module
  `attribute_rules`, so the writer no longer depends on the file reader.

- Backups use the new preset format `hda_presets`. The files end in `.hda_presets.json`
  instead of `.hda_parms.json`, and the parameter values are stored under `parameters` instead
  of `parms`. Backups made by earlier versions can no longer be applied again.

- Extracting this version over an earlier one leaves the unused folder `src/hda_parms` behind.
  It does no harm, but deleting the old folder before extracting keeps the install clean.

## 0.0.2-alpha (29.10.2026) - PATCH, Early Development Version

- Fixed `install.py` running an older copy of itself. Maya reuses a dropped `install.py` that is
  already loaded in the session, so dropping `install.py` from another folder, or after another
  tool's `install.py`, ran the earlier one, which stopped with "no package at …" and added no
  shelf button. `install.py` now unloads itself after each drop.

## 0.0.1-alpha (29.10.2026) - PATCH, Early Development Version

- Initial release.

- HDA Version Changer switches a `silo_gen` Houdini Engine node in the open Maya scene to another
  HDA version and keeps every parameter value set on the old version. It reads the old values
  from the saved `.ma` file, because the HDA's own scripts already change some values while the
  scene opens. Before any change it writes a JSON backup of the values to
  `%LOCALAPPDATA%\hda_version_changer\backups`. After the switch it writes the values back
  until none of them changes any more, and renames the node to `silo_gen_001`, `silo_gen_002`
  and so on. The scene is not saved; reopening it without saving undoes the switch.

- The scene must be saved as a Maya ASCII (`.ma`) file first.
