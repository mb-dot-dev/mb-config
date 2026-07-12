from typing import Self

from mb_config.loaders.env_loader import load_environment_variables
from mb_config.loaders.ssm_param_loader import load_ssm_parameters
from mb_config.loaders.yaml_loader import load_yaml
from mb_config.merger import merge_configurations


class ConfigManager:
    _config: dict

    def __init__(self: Self) -> None:
        self._config = {}

    def add_yaml(self: Self, file_path: str, *, optional: bool = False) -> Self:
        return self.add_dict(load_yaml(file_path, optional=optional))

    def add_environment_variables(self: Self) -> Self:
        return self.add_dict(load_environment_variables())

    def add_ssm_parameters(self: Self) -> Self:
        mapping = self._config.pop("ssm_params", None)
        if not mapping:
            return self
        return self.add_dict(load_ssm_parameters(mapping))

    def add_dict(self: Self, to_merge_with: dict) -> Self:
        self._config = merge_configurations(self._config, to_merge_with)
        return self

    def get_config(self: Self) -> dict:
        return self._config

    def reset_config(self: Self) -> None:
        self._config = {}


config_manager = ConfigManager()


def get_config() -> dict:
    return config_manager.get_config()


def reset_config() -> None:
    config_manager.reset_config()
