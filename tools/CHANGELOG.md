# Changelog

## Unreleased

## 0.1.1-beta (11.11.2026) - PATCH, Pre-release Testing Version

- Version 1.2.0 of `silo_gen` is now offered. Its file `scs.dev.silo_gen.1.2.0.hda` and its
  operator `scs.dev::Object/silo_gen::1.2.0` use the namespace `scs.dev` instead of
  `jandv.dev`, so the tool now reads the HDA files of both namespaces and finds the nodes of
  both.

- A node can only be upgraded. **Available Versions** offers only versions newer than the one
  the node uses, and an upgraded node can no longer be switched back or switched again to the
  same version from another file. Every version but the newest is shown as obsolete, for example
  `1.1 (obsolete)`, and can still be chosen.

- Nodes made with an early revision of 1.0 (`batch_01`) keep their loadout and roof trim
  settings. That revision stores seven parameters under other names, such as
  `extra_struct_type` and `roof_trim`; their values are now written to the current parameters
  `loadout_struct_type` and `roof_trim_type`, and the report lists each renamed parameter.

- Switching a node no longer prints the Houdini Engine warnings "Could not find asset … in OTL
  file …" and "… but the expected path was …". Houdini Engine now creates the new version once,
  from the new file, instead of once with the old file and once with the new one.

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
