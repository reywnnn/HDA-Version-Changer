"""Upgrade the asset nodes of the open Maya scene to a chosen HDA version and reapply backups.

run() reads the old values from the scene file on disk, writes a JSON backup of every node,
switches each node to the chosen HDA version, writes the old values back, renames the node
and prints a report. With a node given, run() upgrades only that node. reapply() writes a
backup to its node again. Neither function saves the scene. find_nodes(), other_versions() and
preview() tell the dialog what run() would do.
"""



import datetime
import os
import maya.cmds as cmds
from hda_presets import attribute_rules, core, node_writer, scene_reader
from ..core import backup, planning
from ..core.config import SILO_GEN, UpgradeConfig
from ..core.model import NodePlan, NodeResult, NodeStatus, UpgradeReport, UpgradeTarget
from ..core.report import format_report, format_summary
from . import query, switch



def hda_folder(config: UpgradeConfig = SILO_GEN) -> str:
    """Return config.hda_folder with the project path expanded.
    Raises RuntimeError if the project path variable is not set."""
    return planning.expand_project_path(config.hda_folder, config.project_path_token,
                                        query.environment_path(config.project_path_env))


def find_versions(config: UpgradeConfig = SILO_GEN) -> list[str]:
    """Return the versions of the HDA files in config.hda_folder, newest first.
    Raises RuntimeError if the project path variable is not set."""
    versions = [planning.version_from_file_name(name, config.file_prefix)
                for name in query.list_hda_files(hda_folder(config))]
    return planning.sort_versions([version for version in versions if version])


def find_nodes(config: UpgradeConfig = SILO_GEN) -> list[str]:
    """Return the long names of all nodes of config.asset_family, sorted by their short names."""
    nodes = [node for node in query.find_asset_nodes()
             if planning.is_in_family(query.node_asset_name(node), config.asset_family)]
    return sorted(nodes, key=lambda node: (query.short_name(node).lower(), node))


def other_versions(node: str, config: UpgradeConfig = SILO_GEN) -> list[str]:
    """Return the versions of the HDA files that the node does not use yet, newest first.
    Raises RuntimeError if the project path variable is not set."""
    project_path = query.environment_path(config.project_path_env)
    asset_name, otl_path = query.node_asset_name(node), query.node_otl_path(node)
    return [version for version in find_versions(config) if not planning.is_on_target(
        asset_name, otl_path, planning.make_target(config, version, project_path), config.project_path_token, project_path)]


def preview(version: str, config: UpgradeConfig = SILO_GEN, node: str | None = None) -> tuple[UpgradeTarget, list[tuple[str, str]]]:
    """Return the target of a version and the old and new name of every node that run() would upgrade.
    The new names can still change if the scene changes before run()."""
    project_path = query.environment_path(config.project_path_env)
    target = planning.make_target(config, version, project_path)
    names = [query.short_name(found) for found in _chosen_nodes(target, config, project_path, node)]
    new_names = planning.new_node_names(config.new_node_name, len(names), _taken_names(node))
    return target, list(zip(names, new_names))


def run(version: str, dry_run: bool = False, config: UpgradeConfig = SILO_GEN, backup_dir: str | None = None,
        node: str | None = None) -> UpgradeReport:
    """Upgrade every node of config.asset_family that does not use the given version yet, or only the given node.
    If a check, the reading of the scene file or a backup fails, it raises before any change."""
    started = _now()

    scene = query.scene_path()
    project_path = query.environment_path(config.project_path_env)
    target = planning.make_target(config, version, project_path)
    if query.has_unsaved_changes():
        cmds.warning("The scene has unsaved changes. The old values are read from the file on disk.")

    nodes = [_asset_node_info(found) for found in _chosen_nodes(target, config, project_path, node)]
    if node is not None and not nodes:
        raise RuntimeError("%s is not a node of %s, or it already uses %s."
                           % (query.short_name(node), config.asset_family, target.asset))
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
            ignored = planning.split_ignored(plan.preset, target.ignored_parms)[1]
            report.results.append(NodeResult(plan=plan, status=NodeStatus.PLANNED, ignored=ignored))
    else:
        for plan in plans:
            report.results.append(_upgrade_node(plan, target, config.max_passes))

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
    cleaned, ignored = planning.split_ignored(preset, ignored_parms)
    apply = node_writer.apply_preset(node, cleaned, config.max_passes)
    result = NodeResult(
        plan=plan,
        status=planning.status_after_upgrade(apply, renamed=True),
        final_name=query.short_name(node),
        apply=apply,
        ignored=ignored,
        added=_added_parms(plan.preset, node),
    )

    print("Backup applied: %s" % json_path)
    _print_report(UpgradeReport(scene=cmds.file(query=True, sceneName=True) or "", dry_run=False,
                                started=_now(), results=[result]))
    return result


def _nodes_to_upgrade(target: UpgradeTarget, config: UpgradeConfig, project_path: str) -> list[str]:
    """Return the nodes of config.asset_family that do not use the target operator from the target file yet."""
    nodes = []
    for node in query.find_asset_nodes():
        asset_name = query.node_asset_name(node)
        if planning.is_in_family(asset_name, config.asset_family) and not planning.is_on_target(
                asset_name, query.node_otl_path(node), target, config.project_path_token, project_path):
            nodes.append(node)
    return nodes


def _chosen_nodes(target: UpgradeTarget, config: UpgradeConfig, project_path: str, node: str | None) -> list[str]:
    """Return the nodes that do not use the target yet, or only the given node if it is one of them.
    Raises RuntimeError if no node or more than one node has the given name."""
    nodes = _nodes_to_upgrade(target, config, project_path)
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


def _upgrade_node(plan: NodePlan, target: UpgradeTarget, max_passes: int) -> NodeResult:
    """Switch one node to the target version, write its values back and rename it.
    Returns a FAILED result instead of raising, so that the other nodes still get upgraded."""
    cleaned, ignored = planning.split_ignored(plan.preset, target.ignored_parms)
    found = query.nodes_by_uuid(plan.uuid)
    if len(found) != 1:
        return NodeResult(plan=plan, status=NodeStatus.FAILED, ignored=ignored,
                          error="%d node(s) have the UUID %s" % (len(found), plan.uuid))
    node = found[0]

    try:
        switch.switch_version(node, target.asset, target.otl_path)
    except Exception as error:
        return NodeResult(plan=plan, status=NodeStatus.FAILED, ignored=ignored, error=str(error))

    try:
        apply = node_writer.apply_preset(node, cleaned, max_passes)
    except Exception as error:
        apply = _stopped_apply(node, cleaned, error)
    added = _added_parms(plan.preset, node)

    try:
        final_name = switch.rename_node(node, plan.new_name)
    except Exception:
        final_name = None

    return NodeResult(
        plan=plan,
        status=planning.status_after_upgrade(apply, renamed=final_name == plan.new_name),
        final_name=final_name,
        apply=apply,
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
