"""Settings of an HDA version upgrade and the instance for silo_gen."""



from dataclasses import dataclass



PROJECT_PATH_TOKEN = "%PRISM_PROJECT_PATH%"


@dataclass(frozen=True)
class UpgradeConfig:
    asset_family: str
    file_prefix: str
    hda_folder: str
    new_node_name: str
    ignored_parms: dict[str, dict[str, str]]
    max_passes: int = 4
    project_path_token: str = PROJECT_PATH_TOKEN
    project_path_env: str = "PRISM_PROJECT_PATH"

    display_root: str = ""


SILO_GEN = UpgradeConfig(
    asset_family="jandv.dev::Object/silo_gen",
    file_prefix="jandv.dev.silo_gen.",
    hda_folder=PROJECT_PATH_TOKEN + "art_assets/houdini/packages/scs_industrial/hda/",
    new_node_name="silo_gen_001",
    display_root=PROJECT_PATH_TOKEN + "art_assets/houdini/packages/",
    ignored_parms={
        "jandv.dev::Object/silo_gen::1.1": {
            "id_key": "invisible in 1.1, the HDA computes it from silo_size and shell_type",
            "loadout_id_key": "invisible in 1.1, the HDA computes it from the loadout settings",
            "lod2_type": "invisible in 1.1",
        },
    },
)
