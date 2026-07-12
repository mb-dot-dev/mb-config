from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import mb_config.config_manager as config_manager_module
from mb_config.config_manager import config_manager
from mb_config.workloads import initialize_config

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def reset_shared_config() -> Generator[None]:
    config_manager.reset_config()
    yield
    config_manager.reset_config()


DEFAULT_YAML = """\
database:
  host: placeholder-host
  password: placeholder-password
ssm_params:
  "secure:/myapp/db/password": "database:password"
  "string:/myapp/db/host": "database:host"
"""


def test_initialize_config_resolves_ssm_params_before_env_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "default.yaml").write_text(DEFAULT_YAML)

    def fake_load(mapping: dict) -> dict:
        assert mapping == {
            "secure:/myapp/db/password": "database:password",
            "string:/myapp/db/host": "database:host",
        }
        return {"database": {"password": "ssm-password", "host": "ssm-host"}}

    monkeypatch.setattr(config_manager_module, "load_ssm_parameters", fake_load)
    monkeypatch.delenv("CONFIG_ENV", raising=False)
    monkeypatch.setenv("DATABASE__HOST", "env-host")

    config = initialize_config(str(tmp_path))

    assert config["database"]["password"] == "ssm-password"
    assert config["database"]["host"] == "env-host"  # env vars override SSM values
    assert "ssm_params" not in config
