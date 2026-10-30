"""Data classes that describe a planned upgrade, its outcome and the offline check of its result.

The classes hold only strings, numbers, lists and dicts, so they work without Maya.
"""



import enum
from dataclasses import dataclass, field
from hda_presets.core import ApplyResult



class NodeStatus(enum.Enum):
    PLANNED = "planned"
    UPGRADED = "upgraded"
    UPGRADED_WITH_PROBLEMS = "upgraded with problems"
    FAILED = "failed"


@dataclass(frozen=True)
class UpgradeTarget:
    version: str
    asset: str
    file_name: str
    otl_path: str
    otl_path_abs: str
    ignored_parms: dict[str, str]


@dataclass(frozen=True)
class NodePlan:
    uuid: str
    original_name: str
    source_otl: str
    target_otl: str
    target_otl_abs: str
    preset: dict
    backup_path: str
    new_name: str


@dataclass
class NodeResult:
    plan: NodePlan
    status: NodeStatus
    final_name: str | None = None
    apply: ApplyResult | None = None
    ignored: dict[str, str] = field(default_factory=dict)
    added: dict[str, object] = field(default_factory=dict)
    error: str | None = None


@dataclass
class UpgradeReport:
    scene: str
    dry_run: bool
    started: str
    results: list[NodeResult] = field(default_factory=list)


@dataclass
class NodeCheck:
    uuid: str
    source_name: str
    upgraded_name: str | None
    problems: list[str] = field(default_factory=list)
    added: dict[str, object] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.problems
