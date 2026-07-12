import os
from pathlib import Path

from mb_config.config_manager import config_manager

DEFAULT_CONFIG_ENVIRONMENT = "dev"


def initialize_config(config_folder_path: str) -> dict:
    environment_name = os.getenv("CONFIG_ENV", DEFAULT_CONFIG_ENVIRONMENT)

    def resolve_path(file_name: str) -> str:
        return str(Path(config_folder_path) / file_name)

    # load default and env specific config files
    config_manager.add_yaml(resolve_path("default.yaml")).add_yaml(
        resolve_path(f"{environment_name}.yaml"), optional=True
    )

    # if dev then load secrets.toml
    if environment_name == DEFAULT_CONFIG_ENVIRONMENT:
        config_manager.add_yaml(resolve_path("secrets.yaml"), optional=True)

    # resolve SSM parameters declared by the layers above
    config_manager.add_ssm_parameters()

    # load environment variables
    config_manager.add_environment_variables()

    return config_manager.get_config()
