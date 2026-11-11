"""Text report and summary of an upgrade run for the Maya Script Editor, and the status line for the dialog."""



from .model import NodeResult, NodeStatus, UpgradeReport



_INDENT = "    "


def format_report(report: UpgradeReport) -> str:
    mode = "dry run, the scene was not changed" if report.dry_run else "upgrade"
    lines = [
        "HDA version upgrade: %s" % report.scene,
        "Mode: %s, started %s" % (mode, report.started),
        _summary(report.results),
    ]
    for result in report.results:
        lines.append("")
        lines.extend(_node_lines(result))
    return "\n".join(lines)


def format_summary(report: UpgradeReport) -> str:
    """Return the overall outcome and, for every node, how many of its values reached the new version."""
    if not report.results:
        return "Result: no node to upgrade."
    lines = ["Result: %s." % _outcome(report)]
    lines.extend(_INDENT + _transfer_line(result) for result in report.results)
    return "\n".join(lines)


def format_status(report: UpgradeReport) -> str:
    """Return one line with the transferred parameters of all nodes and the overall outcome.
    The dialog shows this line in its status field."""
    if not report.results:
        return "No node to upgrade."
    counts = [transfer_counts(result) for result in report.results]
    transferred, total = sum(count[0] for count in counts), sum(count[1] for count in counts)
    if report.dry_run:
        return "Dry run: %d parameters to transfer, the scene was not changed." % total
    outcome = {
        "succeeded": "operation successful",
        "failed": "failed, the node was not switched",
        "finished with problems": "finished with problems, see the Script Editor",
    }[_outcome(report)]
    return "Transferred %d / %d parameters: %s." % (transferred, total, outcome)


def transfer_counts(result: NodeResult) -> tuple[int, int]:
    """Return how many values of the node were transferred and how many it had, without the ignored ones.
    A value counts as transferred if it is not missing, has no problem and matches the node."""
    parms = {result.renamed.get(parm, parm) for parm in result.plan.preset["parameters"]} - set(result.ignored)
    apply = result.apply
    if apply is None:
        return 0, len(parms)
    failed = set(apply.missing) | set(apply.problems) | {parm for parm, _, _ in apply.mismatched}
    return len(parms - failed), len(parms)


def _outcome(report: UpgradeReport) -> str:
    statuses = {result.status for result in report.results}
    if report.dry_run:
        return "dry run, the scene was not changed"
    if statuses == {NodeStatus.UPGRADED}:
        return "succeeded"
    if statuses == {NodeStatus.FAILED}:
        return "failed"
    return "finished with problems"


def _transfer_line(result: NodeResult) -> str:
    plan = result.plan
    transferred, total = transfer_counts(result)
    if result.status == NodeStatus.PLANNED:
        return "%s -> %s: %d parameters to transfer" % (plan.original_name, plan.new_name, total)
    if result.status == NodeStatus.FAILED:
        return "%s: 0 / %d parameters transferred, the node was not switched" % (plan.original_name, total)
    return "%s -> %s: %d / %d parameters transferred" % (
        plan.original_name, result.final_name or plan.original_name, transferred, total)


def _summary(results: list[NodeResult]) -> str:
    if not results:
        return "No node to upgrade."
    counts = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    parts = ["%d %s" % (counts[status], status.value) for status in NodeStatus if status in counts]
    return "%d node(s): %s" % (len(results), ", ".join(parts))


def _node_lines(result: NodeResult) -> list[str]:
    plan = result.plan
    if result.status == NodeStatus.PLANNED:
        lines = ["[PLANNED] %s -> %s" % (plan.original_name, plan.new_name)]
        lines.append(_INDENT + "target: %s" % plan.target_otl)
        lines.append(_INDENT + "values: %d" % len(plan.preset["parameters"]))
    elif result.status == NodeStatus.FAILED:
        lines = ["[FAILED] %s: %s" % (plan.original_name, result.error)]
    else:
        lines = ["[%s] %s -> %s" % (result.status.name, plan.original_name, result.final_name or plan.original_name)]
    lines.append(_INDENT + "backup: %s" % plan.backup_path)

    apply = result.apply
    if apply:
        lines.append(_INDENT + "written: %d value(s) in %d pass(es)" % (len(apply.written), apply.passes))
    for old, new in sorted(result.renamed.items()):
        lines.append(_INDENT + "renamed: %s -> %s" % (old, new))
    for parm, reason in sorted(result.ignored.items()):
        lines.append(_INDENT + "ignored: %s (%s)" % (parm, reason))
    if apply:
        for parm in apply.missing:
            lines.append(_INDENT + "missing: %s does not exist on the node" % parm)
        for parm, reason in sorted(apply.problems.items()):
            lines.append(_INDENT + "problem: %s: %s" % (parm, reason))
        for parm, wanted, actual in apply.mismatched:
            lines.append(_INDENT + "mismatch: %s: wanted %s, the node has %s" % (parm, _format_value(wanted), _format_value(actual)))
    if result.status in (NodeStatus.UPGRADED, NodeStatus.UPGRADED_WITH_PROBLEMS) and result.final_name != plan.new_name:
        lines.append(_INDENT + "rename: wanted %s, the node is named %s" % (plan.new_name, result.final_name or plan.original_name))
    for parm, value in sorted(result.added.items()):
        lines.append(_INDENT + "new in target: %s = %s" % (parm, _format_value(value)))
    return lines


def _format_value(value) -> str:
    if isinstance(value, float):
        return "%g" % value
    if isinstance(value, (list, tuple)):
        return "(%s)" % ", ".join(_format_value(item) for item in value)
    if isinstance(value, str):
        return '"%s"' % value
    return str(value)
