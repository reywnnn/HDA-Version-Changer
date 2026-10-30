"""Compare a scene before and after the upgrade, without Maya.

    python -m hda_version_changer.core.verify <source.ma> <upgraded.ma>

The houdiniAsset nodes of both files are paired by UUID. The exit code is 0 if every node of the
asset family has an upgraded pair that holds all of its values, 1 if not, and 2 for wrong
arguments.
"""



import sys
from hda_presets import core, scene_reader
from .config import SILO_GEN, UpgradeConfig
from .model import NodeCheck
from .planning import is_in_family, is_upgraded_name



def check_upgrade(source_ma: str, upgraded_ma: str, config: UpgradeConfig = SILO_GEN) -> list[NodeCheck]:
    """Check every node of the asset family in source_ma against its pair in upgraded_ma.
    Returns an empty list if source_ma has no node of the asset family."""
    source_nodes = [node for node in scene_reader.list_asset_nodes(source_ma) if is_in_family(node.asset_name, config.asset_family)]
    source_presets = scene_reader.read_presets(source_ma, [node.name for node in source_nodes])

    upgraded_by_uuid = {}
    for node in scene_reader.list_asset_nodes(upgraded_ma):
        upgraded_by_uuid.setdefault(node.uuid, []).append(node)

    checks, paired = [], {}
    for node in source_nodes:
        check = NodeCheck(uuid=node.uuid, source_name=node.name, upgraded_name=None)
        checks.append(check)
        pairs = upgraded_by_uuid.get(node.uuid, [])
        if len(pairs) != 1:
            check.problems.append("the upgraded file has %d node(s) with UUID %s" % (len(pairs), node.uuid))
            continue
        pair = pairs[0]
        check.upgraded_name = pair.name
        if not is_in_family(pair.asset_name, config.asset_family):
            check.problems.append("assetName is %r, expected a version of %r" % (pair.asset_name, config.asset_family))
        elif (pair.asset_name, pair.otl_path) == (node.asset_name, node.otl_path):
            check.problems.append("the node still uses %r from %r" % (pair.asset_name, pair.otl_path))
        if not is_upgraded_name(pair.name, config.new_node_name):
            check.problems.append("the node is named %r, expected %r or a higher number" % (pair.name, config.new_node_name))
        paired[pair.name] = (check, source_presets[node.name], config.ignored_parms.get(pair.asset_name, {}))

    upgraded_presets = scene_reader.read_presets(upgraded_ma, list(paired)) if paired else {}
    for name, (check, source_preset, ignored_parms) in paired.items():
        _compare_values(check, source_preset, upgraded_presets[name], ignored_parms)
    return checks


def _compare_values(check: NodeCheck, source: dict, upgraded: dict, ignored_parms: dict[str, str]) -> None:
    """Add a problem for every source value that the upgraded node lacks or holds differently.
    A menu parameter that has a label in both presets is compared by its label."""
    source_labels = source.get("menu_labels") or {}
    upgraded_labels = upgraded.get("menu_labels") or {}
    upgraded_parms = upgraded["parameters"]

    for parm, value in sorted(source["parameters"].items()):
        if parm in ignored_parms:
            continue
        if parm not in upgraded_parms:
            check.problems.append("%s is missing" % parm)
        elif parm in source_labels and parm in upgraded_labels:
            if source_labels[parm] != upgraded_labels[parm]:
                check.problems.append("%s: source %r, upgraded %r" % (parm, source_labels[parm], upgraded_labels[parm]))
        elif not core.values_equal(value, upgraded_parms[parm]):
            check.problems.append("%s: source %r, upgraded %r" % (parm, value, upgraded_parms[parm]))

    check.added = {parm: upgraded_parms[parm] for parm in sorted(upgraded_parms) if parm not in source["parameters"]}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m hda_version_changer.core.verify <source.ma> <upgraded.ma>", file=sys.stderr)
        return 2

    checks = check_upgrade(args[0], args[1])
    if not checks:
        print("%s has no node of %s." % (args[0], SILO_GEN.asset_family))
        return 1

    for check in checks:
        print("%s %s -> %s" % ("PASS" if check.passed else "FAIL", check.source_name, check.upgraded_name or "-"))
        for problem in check.problems:
            print("    problem: %s" % problem)
        for parm, value in check.added.items():
            print("    new in target: %s = %r" % (parm, value))
    passed = sum(check.passed for check in checks)
    print("%d of %d node(s) passed." % (passed, len(checks)))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
