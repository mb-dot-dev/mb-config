from __future__ import annotations

from typing import TYPE_CHECKING

import mb_config.config_manager as config_manager_module
from mb_config.config_manager import ConfigManager

if TYPE_CHECKING:
    import pytest


def test_add_ssm_parameters_resolves_and_removes_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    received = {}

    def fake_load(mapping: dict) -> dict:
        received["mapping"] = mapping
        return {"database": {"password": "s3cret"}}

    monkeypatch.setattr(config_manager_module, "load_ssm_parameters", fake_load)

    manager = ConfigManager()
    manager.add_dict(
        {
            "ssm_params": {"secure:/myapp/db/password": "database:password"},
            "database": {"host": "db.example.com"},
        }
    )
    manager.add_ssm_parameters()

    assert received["mapping"] == {"secure:/myapp/db/password": "database:password"}
    assert manager.get_config() == {"database": {"host": "db.example.com", "password": "s3cret"}}


def test_add_ssm_parameters_is_noop_without_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_load(mapping: dict) -> dict:
        msg = "load_ssm_parameters must not be called"
        raise AssertionError(msg)

    monkeypatch.setattr(config_manager_module, "load_ssm_parameters", fail_load)

    manager = ConfigManager()
    manager.add_dict({"database": {"host": "db.example.com"}})
    result = manager.add_ssm_parameters()

    assert result is manager
    assert manager.get_config() == {"database": {"host": "db.example.com"}}
