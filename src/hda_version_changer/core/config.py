"""Settings of an HDA version upgrade and the instance for silo_gen."""



from dataclasses import dataclass, field



PROJECT_PATH_TOKEN = "%PRISM_PROJECT_PATH%"


@dataclass(frozen=True)
class AssetFamily:
    name: str
    file_prefix: str


@dataclass(frozen=True)
class UpgradeConfig:
    families: tuple[AssetFamily, ...]
    hda_folder: str
    new_node_name: str
    ignored_parms: dict[str, dict[str, str]]
    renamed_parms: dict[str, str] = field(default_factory=dict)
    max_passes: int = 4
    project_path_token: str = PROJECT_PATH_TOKEN
    project_path_env: str = "PRISM_PROJECT_PATH"

    display_root: str = ""


_SILO_GEN_1_1_INVISIBLE = {
    "id_key": "invisible since 1.1, the HDA computes it from silo_size and shell_type",
    "loadout_id_key": "invisible since 1.1, the HDA computes it from the loadout settings",
    "lod2_type": "invisible since 1.1",
}

SILO_GEN = UpgradeConfig(
    families=(
        AssetFamily(name="jandv.dev::Object/silo_gen", file_prefix="jandv.dev.silo_gen."),
        AssetFamily(name="scs.dev::Object/silo_gen", file_prefix="scs.dev.silo_gen."),
    ),
    hda_folder=PROJECT_PATH_TOKEN + "art_assets/houdini/packages/scs_industrial/hda/",
    new_node_name="silo_gen_001",
    display_root=PROJECT_PATH_TOKEN + "art_assets/houdini/packages/",
    ignored_parms={
        "jandv.dev::Object/silo_gen::1.1": _SILO_GEN_1_1_INVISIBLE,
        "scs.dev::Object/silo_gen::1.2.0": _SILO_GEN_1_1_INVISIBLE,
    },
    renamed_parms={
        "toggle_extra_structure": "toggle_loadout_structure",
        "extra_struct_type": "loadout_struct_type",
        "extra_struct_height": "loadout_struct_height",
        "extra_struct_width": "loadout_struct_width",
        "extra_frame_def_0": "loadout_frame_def_0",
        "extra_frame_def_1": "loadout_frame_def_1",
        "roof_trim": "roof_trim_type",
    },
)
