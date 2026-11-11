"""Upgrade the asset nodes of the open Maya scene to a newer HDA version and reapply backups.

run() reads the old values from the scene file on disk, writes a JSON backup of every node,
switches each node that uses an older version to the chosen HDA version, writes the old values
back under their current names, renames the node and prints a report. With a node given, run()
upgrades only that node. reapply() writes a backup to its node again. Neither function saves the
scene. find_nodes(), other_versions() and preview() tell the dialog what run() would do, and
current_hda() tells it what a node uses now.
"""



import datetime
import os
import maya.cmds as cmds
from hda_presets import attribute_rules, core, node_writer, scene_reader
from ..core import backup, planning
from ..core.config import SILO_GEN, AssetFamily, UpgradeConfig
from ..core.model import NodePlan, NodeResult, NodeStatus, UpgradeReport, UpgradeTarget
from ..core.report import format_report, format_summary
from . import query, switch



def hda_folder(config: UpgradeConfig = SILO_GEN) -> str:
    """Return config.hda_folder with the project path expanded.
    Raises RuntimeError if the project path variable is not set."""
    return planning.expand_project_path(config.hda_folder, config.project_path_token,
                                        query.environment_path(config.project_path_env))


def find_versions(config: UpgradeConfig = SILO_GEN) -> list[str]:
    """Return the versions of the HDA files of all families in config.hda_folder, newest first.
    Raises RuntimeError if the project path variable is not set or two families have the same version."""
    return planning.sort_versions(list(_family_versions(config)))


def find_nodes(config: UpgradeConfig = SILO_GEN) -> list[str]:
    """Return the long names of all nodes of config.families, sorted by their short names."""
    nodes = [node for node in query.find_asset_nodes()
             if planning.is_in_family(query.node_asset_name(node), config.families)]
    return sorted(nodes, key=lambda node: (query.short_name(node).lower(), node))


def other_versions(node: str, config: UpgradeConfig = SILO_GEN) -> list[str]:
    """Return the versions of the HDA files that are newer than the version the node uses, newest first.
    Raises RuntimeError if the project path variable is not set."""
    asset_name = query.node_asset_name(node)
    return [version for version in find_versions(config) if planning.is_older(asset_name, version)]


def current_hda(node: str, config: UpgradeConfig = SILO_GEN) -> tuple[str, str, str]:
    """Return the operator the node uses, its otlFilePath and that path with the project path expanded.
    The expanded path is otlFilePath unchanged if the project path variable is not set."""
    otl_path = query.node_otl_path(node)
    project_path = os.environ.get(config.project_path_env)
    absolute = planning.expand_project_path(otl_path, config.project_path_token, project_path) if project_path else otl_path
    return query.node_asset_name(node), otl_path, absolute


def preview(version: str, config: UpgradeConfig = SILO_GEN, node: str | None = None) -> tuple[UpgradeTarget, list[tuple[str, str]]]:
    """Return the target of a version and the old and new name of every node that run() would upgrade.
    The new names can still change if the scene changes before run()."""
    target = _target(version, config)
    names = [query.short_name(found) for found in _chosen_nodes(target, config, node)]
    new_names = planning.new_node_names(config.new_node_name, len(names), _taken_names(node))
    return target, list(zip(names, new_names))


def run(version: str, dry_run: bool = False, config: UpgradeConfig = SILO_GEN, backup_dir: str | None = None,
        node: str | None = None) -> UpgradeReport:
    """Upgrade every node of config.families that uses an older version than the given one, or only the given node.
    If a check, the reading of the scene file or a backup fails, it raises before any change."""
    started = _now()

    scene = query.scene_path()
    target = _target(version, config)
    if query.has_unsaved_changes():
        cmds.warning("The scene has unsaved changes. The old values are read from the file on disk.")

    nodes = [_asset_node_info(found) for found in _chosen_nodes(target, config, node)]
    if node is not None and not nodes:
        raise RuntimeError("%s is not a node of %s, or it already uses %s or a newer version."
                           % (query.short_name(node), _family_names(config), version))
    report = UpgradeReport(scene=scene, dry_run=dry_run, started=started)
    if not nodes:
        _print_report(report)
        return report
    duplicates = planning.find_duplicate_names([node.name for node in nodes])
    if duplicates:
        raise RuntimeError("More than one node is named %s; rename them first." % ", ".join(duplicates))

    try:
        presets = scene_reader.read_presets(scene, [node.name for node in nodes])
    except ValueError as error:
        raise RuntimeError("The scene file on disk does not match the open scene: %s" % error) from error
    plans = planning.build_plans(
        nodes, presets, target, config.new_node_name,
        _taken_names(node),
        _backup_paths(nodes, scene, backup_dir),
    )

    _prepare_target_library(target)
    for plan in plans:
        backup.write_backup(plan, target.asset)

    if dry_run:
        for plan in plans:
            _, renamed, ignored = planning.prepare_preset(plan.preset, config.renamed_parms, target.ignored_parms)
            report.results.append(NodeResult(plan=plan, status=NodeStatus.PLANNED, renamed=renamed, ignored=ignored))
    else:
        for plan in plans:
            report.results.append(_upgrade_node(plan, target, config))

    _print_report(report)
    return report


def reapply(json_path: str, config: UpgradeConfig = SILO_GEN) -> NodeResult:
    """Write the values of a backup to the node with the backup's UUID in the open scene.
    Raises RuntimeError if no node or more than one node has that UUID."""
    preset = backup.read_backup(json_path)
    uuid = preset["source"]["node_uuid"]
    found = query.nodes_by_uuid(uuid)
    if len(found) != 1:
        raise RuntimeError("%d node(s) in the open scene have the UUID %s of the backup." % (len(found), uuid))
    node = found[0]

    otl_path = query.node_otl_path(node)
    plan = NodePlan(
        uuid=uuid,
        original_name=preset["source"].get("node", ""),
        source_otl=preset["hda"].get("library", ""),
        target_otl=otl_path,
        target_otl_abs=planning.expand_project_path(
            otl_path, config.project_path_token, os.environ.get(config.project_path_env, "")),
        preset=preset,
        backup_path=json_path,
        new_name=query.short_name(node),
    )
    ignored_parms = config.ignored_parms.get(query.node_asset_name(node), {})
    cleaned, renamed, ignored = planning.prepare_preset(preset, config.renamed_parms, ignored_parms)
    apply = node_writer.apply_preset(node, cleaned, config.max_passes)
    result = NodeResult(
        plan=plan,
        status=planning.status_after_upgrade(apply, renamed=True),
        final_name=query.short_name(node),
        apply=apply,
        renamed=renamed,
        ignored=ignored,
        added=_added_parms(cleaned, node),
    )

    print("Backup applied: %s" % json_path)
    _print_report(UpgradeReport(scene=cmds.file(query=True, sceneName=True) or "", dry_run=False,
                                started=_now(), results=[result]))
    return result


def _family_versions(config: UpgradeConfig) -> dict[str, AssetFamily]:
    """Return every version in config.hda_folder and the family whose file holds it.
    Raises RuntimeError if the project path variable is not set or two families have the same version."""
    try:
        return planning.find_family_versions(config.families, query.list_hda_files(hda_folder(config)))
    except ValueError as error:
        raise RuntimeError(str(error)) from error


def _target(version: str, config: UpgradeConfig) -> UpgradeTarget:
    """Return the target of a version from the family whose file in config.hda_folder holds it.
    Raises RuntimeError if no family has a file of that version."""
    family = _family_versions(config).get(version)
    if family is None:
        raise RuntimeError("No HDA file of version %s was found in %s." % (version, hda_folder(config)))
    return planning.make_target(config, family, version, query.environment_path(config.project_path_env))


def _family_names(config: UpgradeConfig) -> str:
    return " or ".join(family.name for family in config.families)


def _nodes_to_upgrade(target: UpgradeTarget, config: UpgradeConfig) -> list[str]:
    """Return the nodes of config.families that use an older version than the target."""
    nodes = []
    for node in query.find_asset_nodes():
        asset_name = query.node_asset_name(node)
        if planning.is_in_family(asset_name, config.families) and planning.is_older(asset_name, target.version):
            nodes.append(node)
    return nodes


def _chosen_nodes(target: UpgradeTarget, config: UpgradeConfig, node: str | None) -> list[str]:
    """Return the nodes that use an older version than the target, or only the given node if it is one of them.
    Raises RuntimeError if no node or more than one node has the given name."""
    nodes = _nodes_to_upgrade(target, config)
    if node is None:
        return nodes
    wanted = query.long_name(node)
    return [found for found in nodes if found == wanted]


def _taken_names(node: str | None) -> set[str]:
    """Return the short names a new node name must avoid.
    A single upgraded node may keep its own name, so silo_gen_001 stays silo_gen_001."""
    taken = query.taken_short_names()
    if node is not None:
        taken.discard(query.short_name(node))
    return taken


def _upgrade_node(plan: NodePlan, target: UpgradeTarget, config: UpgradeConfig) -> NodeResult:
    """Switch one node to the target version, write its values back and rename it.
    Returns a FAILED result instead of raising, so that the other nodes still get upgraded."""
    cleaned, renamed, ignored = planning.prepare_preset(plan.preset, config.renamed_parms, target.ignored_parms)
    found = query.nodes_by_uuid(plan.uuid)
    if len(found) != 1:
        return NodeResult(plan=plan, status=NodeStatus.FAILED, renamed=renamed, ignored=ignored,
                          error="%d node(s) have the UUID %s" % (len(found), plan.uuid))
    node = found[0]

    try:
        switch.switch_version(node, target.asset, target.otl_path)
    except Exception as error:
        return NodeResult(plan=plan, status=NodeStatus.FAILED, renamed=renamed, ignored=ignored, error=str(error))

    try:
        apply = node_writer.apply_preset(node, cleaned, config.max_passes)
    except Exception as error:
        apply = _stopped_apply(node, cleaned, error)
    added = _added_parms(cleaned, node)

    try:
        final_name = switch.rename_node(node, plan.new_name)
    except Exception:
        final_name = None

    return NodeResult(
        plan=plan,
        status=planning.status_after_upgrade(apply, renamed=final_name == plan.new_name),
        final_name=final_name,
        apply=apply,
        renamed=renamed,
        ignored=ignored,
        added=added,
    )


def _asset_node_info(node: str) -> scene_reader.AssetNodeInfo:
    return scene_reader.AssetNodeInfo(
        name=query.short_name(node),
        uuid=query.node_uuid(node),
        asset_name=query.node_asset_name(node),
        otl_path=query.node_otl_path(node),
    )


def _backup_paths(nodes: list[scene_reader.AssetNodeInfo], scene: str, backup_dir: str | None) -> dict[str, str]:
    folder = backup_dir or backup.default_backup_dir(scene, query.environment_path("LOCALAPPDATA"))
    paths, taken = {}, set()
    for node in nodes:
        path = backup.backup_path(folder, scene, node.name, taken)
        taken.add(path)
        paths[node.name] = path
    return paths


def _prepare_target_library(target: UpgradeTarget) -> None:
    """Load the target .hda file into Houdini Engine and check that it defines the target operator.
    Raises RuntimeError if the file is missing or does not define the target operator."""
    if not os.path.isfile(target.otl_path_abs):
        raise RuntimeError("The target HDA file does not exist: %s" % target.otl_path_abs)
    operators = query.load_hda_library(target.otl_path_abs)
    if target.asset not in operators:
        raise RuntimeError("%s does not define %s. It defines: %s"
                           % (target.otl_path_abs, target.asset, ", ".join(operators) or "nothing"))


def _added_parms(preset: dict, node: str) -> dict:
    """Return the parameters the node has and the preset lacks, or an empty dict if the node cannot be read."""
    try:
        return core.diff_parms(preset, node_writer.read_node_preset(node))[0]
    except Exception:
        return {}


def _stopped_apply(node: str, preset: dict, error: Exception) -> core.ApplyResult:
    """Return the result of a write that stopped with an error, with the values the node holds by now.
    If the node cannot be read, every value counts as not written."""
    result = core.ApplyResult(problems={"(all values)": "writing stopped: %s" % error})
    try:
        result.missing = [parm for parm in preset["parameters"]
                          if not cmds.objExists("%s.%s" % (node, attribute_rules.attr_name(parm)))]
        result.mismatched = node_writer.mismatches(node, preset)
    except Exception:
        result.mismatched = [(parm, value, None) for parm, value in preset["parameters"].items()]
    return result


def _print_report(report: UpgradeReport) -> None:
    print(format_report(report))
    print("")
    print(format_summary(report))
    attention = [result for result in report.results
                 if result.status in (NodeStatus.UPGRADED_WITH_PROBLEMS, NodeStatus.FAILED)]
    if attention:
        cmds.warning("%d node(s) need attention, see the report in the Script Editor." % len(attention))


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")
