# SSM Parameter Store Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional loader that resolves values from AWS SSM Parameter Store into the config, driven by an `ssm_params` mapping in already-loaded config layers.

**Architecture:** A pure loader function `load_ssm_parameters(mapping, client=None)` in `src/mb_config/loaders/ssm_param_loader.py` fetches each parameter individually and returns a nested dict. `ConfigManager.add_ssm_parameters()` pops the `ssm_params` key from the merged config and merges the loader's result. `workloads.initialize_config` calls it after the YAML layers and before environment variables, so env vars override SSM values.

**Tech Stack:** Python ≥3.14, uv, pytest, boto3 (optional extra), yamlrocks (existing).

**Spec:** `docs/superpowers/specs/2026-07-12-ssm-param-loader-design.md`

## Global Constraints

- The config key is exactly `ssm_params` (not `ssm_secrets`).
- Mapping key syntax: `<prefix>:<ssm-path>` where prefix is exactly `string` or `secure`. `secure:` fetches with `WithDecryption=True` and requires SSM `Type` `SecureString`; `string:` requires `Type` `String`.
- Mapping value syntax: target path split on `:` into arbitrary-depth segments.
- `boto3>=1.34` lives only in the `ssm` optional-dependency extra (plus the `dev` group for tests). It must never be imported at module import time — only lazily, and only when a real client is needed.
- All failures raise at load time (fail hard). Secret values must never appear in exception messages.
- Test everything with an injected fake client — no moto, no network, no real AWS calls.
- Run tests with `uv run pytest`.
- Known environment issue: `git commit` may fail with `error: 1Password: failed to fill whole buffer` (commit signing). If that happens, leave the changes staged, report it, and continue — do not disable signing.

---

### Task 1: Packaging + loader happy path

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/mb_config/loaders/ssm_param_loader.py` (currently an empty stub)
- Test: `tests/test_ssm_param_loader.py` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `load_ssm_parameters(mapping: dict, client: Any = None) -> dict` in `mb_config.loaders.ssm_param_loader`. `client` needs only a `get_parameter(Name=..., WithDecryption=...)` method returning `{"Parameter": {"Type": ..., "Value": ...}}`. Task 2 extends this same function with validation; Tasks 3–4 monkeypatch it.

- [ ] **Step 1: Add dependency configuration to `pyproject.toml`**

Append after the `[build-system]` section:

```toml
[project.optional-dependencies]
ssm = ["boto3>=1.34"]

[dependency-groups]
dev = [
    "pytest>=8",
    "boto3>=1.34",
]
```

- [ ] **Step 2: Install dependencies**

Run: `uv sync`
Expected: succeeds and installs `pytest` and `boto3` (uv installs the `dev` group by default).

- [ ] **Step 3: Write the failing tests**

Create `tests/test_ssm_param_loader.py`:

```python
from mb_config.loaders.ssm_param_loader import load_ssm_parameters


class FakeSsmClient:
    """Minimal stand-in for boto3's SSM client: path -> (type, value)."""

    def __init__(self, parameters: dict) -> None:
        self._parameters = parameters
        self.calls: list[dict] = []

    def get_parameter(self, *, Name: str, WithDecryption: bool = False) -> dict:
        self.calls.append({"Name": Name, "WithDecryption": WithDecryption})
        if Name not in self._parameters:
            raise LookupError(f"ParameterNotFound: {Name}")
        parameter_type, value = self._parameters[Name]
        return {"Parameter": {"Name": Name, "Type": parameter_type, "Value": value}}


def test_loads_string_parameter_without_decryption():
    client = FakeSsmClient({"/myapp/db/host": ("String", "db.example.com")})

    result = load_ssm_parameters({"string:/myapp/db/host": "database:host"}, client=client)

    assert result == {"database": {"host": "db.example.com"}}
    assert client.calls == [{"Name": "/myapp/db/host", "WithDecryption": False}]


def test_loads_secure_string_parameter_with_decryption():
    client = FakeSsmClient({"/myapp/db/password": ("SecureString", "s3cret")})

    result = load_ssm_parameters(
        {"secure:/myapp/db/password": "database:password"}, client=client
    )

    assert result == {"database": {"password": "s3cret"}}
    assert client.calls == [{"Name": "/myapp/db/password", "WithDecryption": True}]


def test_target_supports_arbitrary_nesting_depth():
    client = FakeSsmClient({"/myapp/db/password": ("SecureString", "s3cret")})

    result = load_ssm_parameters(
        {"secure:/myapp/db/password": "database:credentials:password"}, client=client
    )

    assert result == {"database": {"credentials": {"password": "s3cret"}}}


def test_single_segment_target_assigns_top_level():
    client = FakeSsmClient({"/myapp/api_key": ("SecureString", "key-123")})

    result = load_ssm_parameters({"secure:/myapp/api_key": "api_key"}, client=client)

    assert result == {"api_key": "key-123"}


def test_multiple_entries_merge_into_one_result():
    client = FakeSsmClient(
        {
            "/myapp/db/host": ("String", "db.example.com"),
            "/myapp/db/password": ("SecureString", "s3cret"),
        }
    )

    result = load_ssm_parameters(
        {
            "string:/myapp/db/host": "database:host",
            "secure:/myapp/db/password": "database:password",
        },
        client=client,
    )

    assert result == {"database": {"host": "db.example.com", "password": "s3cret"}}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_ssm_param_loader.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_ssm_parameters'` (the module is an empty stub).

- [ ] **Step 5: Write the minimal implementation**

Replace the contents of `src/mb_config/loaders/ssm_param_loader.py` with:

```python
from typing import Any


def load_ssm_parameters(mapping: dict, client: Any = None) -> dict:
    """
    Load configuration values from AWS SSM Parameter Store.

    The mapping key is "<prefix>:<parameter path>" where the prefix is
    "string" or "secure" and selects the expected SSM parameter type.
    The mapping value is the target location in the configuration,
    with ":" separating nesting levels.
    E.g. {"secure:/myapp/db/password": "database:password"} returns
    ```{
        "database": {
            "password": "<resolved value>"
        }
    }```
    """
    if client is None:
        client = _create_client()

    config: dict = {}

    for key, target in mapping.items():
        prefix, _, parameter_path = key.partition(":")
        secure = prefix == "secure"

        response = client.get_parameter(Name=parameter_path, WithDecryption=secure)
        value = response["Parameter"]["Value"]

        parts = target.split(":")
        current_level = config
        for part in parts[:-1]:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]
        current_level[parts[-1]] = value

    return config


def _create_client() -> Any:
    import boto3

    return boto3.client("ssm")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ssm_param_loader.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/mb_config/loaders/ssm_param_loader.py tests/test_ssm_param_loader.py
git commit -m "feat: add SSM parameter loader with string/secure prefixes"
```

---

### Task 2: Loader validation and error handling

**Files:**
- Modify: `src/mb_config/loaders/ssm_param_loader.py`
- Test: `tests/test_ssm_param_loader.py` (append)

**Interfaces:**
- Consumes: `load_ssm_parameters` and `FakeSsmClient` from Task 1.
- Produces: the final loader contract — `ValueError` for malformed mapping entries, `RuntimeError` for fetch failures and type mismatches, `ImportError` with an `mb-config[ssm]` hint when boto3 is missing. Signature unchanged.

- [ ] **Step 1: Write the failing error tests**

Append to `tests/test_ssm_param_loader.py` (add `import sys` and `import pytest` at the top of the file):

```python
def test_key_without_prefix_raises_value_error():
    with pytest.raises(ValueError, match="/myapp/db/host"):
        load_ssm_parameters({"/myapp/db/host": "database:host"}, client=FakeSsmClient({}))


def test_unknown_prefix_raises_value_error():
    with pytest.raises(ValueError, match="secret:/myapp/db/host"):
        load_ssm_parameters(
            {"secret:/myapp/db/host": "database:host"}, client=FakeSsmClient({})
        )


def test_empty_parameter_path_raises_value_error():
    with pytest.raises(ValueError, match="secure:"):
        load_ssm_parameters({"secure:": "database:password"}, client=FakeSsmClient({}))


def test_non_string_target_raises_value_error():
    with pytest.raises(ValueError, match="secure:/myapp/db/password"):
        load_ssm_parameters(
            {"secure:/myapp/db/password": ["database", "password"]},
            client=FakeSsmClient({}),
        )


def test_fetch_failure_raises_runtime_error_naming_the_path():
    client = FakeSsmClient({})  # parameter does not exist

    with pytest.raises(RuntimeError, match="/myapp/db/password"):
        load_ssm_parameters({"secure:/myapp/db/password": "database:password"}, client=client)


def test_type_mismatch_raises_runtime_error_without_leaking_the_value():
    client = FakeSsmClient({"/myapp/db/password": ("String", "s3cret")})

    with pytest.raises(RuntimeError, match="SecureString") as excinfo:
        load_ssm_parameters({"secure:/myapp/db/password": "database:password"}, client=client)

    assert "s3cret" not in str(excinfo.value)


def test_missing_boto3_raises_import_error_with_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)  # makes `import boto3` fail

    with pytest.raises(ImportError, match=r"mb-config\[ssm\]"):
        load_ssm_parameters({"secure:/myapp/db/password": "database:password"})
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_ssm_param_loader.py -v`
Expected: the 5 Task-1 tests PASS; the 7 new tests FAIL (`DID NOT RAISE`, `KeyError`, or `LookupError` instead of the expected exception types).

- [ ] **Step 3: Add validation and error wrapping**

Replace the contents of `src/mb_config/loaders/ssm_param_loader.py` with:

```python
from typing import Any

_TYPE_BY_PREFIX = {"string": "String", "secure": "SecureString"}


def load_ssm_parameters(mapping: dict, client: Any = None) -> dict:
    """
    Load configuration values from AWS SSM Parameter Store.

    The mapping key is "<prefix>:<parameter path>" where the prefix is
    "string" or "secure" and selects the expected SSM parameter type.
    The mapping value is the target location in the configuration,
    with ":" separating nesting levels.
    E.g. {"secure:/myapp/db/password": "database:password"} returns
    ```{
        "database": {
            "password": "<resolved value>"
        }
    }```
    """
    if client is None:
        client = _create_client()

    config: dict = {}

    for key, target in mapping.items():
        prefix, _, parameter_path = key.partition(":")
        if prefix not in _TYPE_BY_PREFIX or not parameter_path:
            raise ValueError(
                f"Invalid ssm_params key '{key}': expected 'string:<path>' or 'secure:<path>'"
            )
        if not isinstance(target, str) or not target:
            raise ValueError(
                f"Invalid ssm_params target for key '{key}': expected a non-empty string"
            )

        value = _fetch_parameter(client, parameter_path, expected_type=_TYPE_BY_PREFIX[prefix])

        parts = target.split(":")
        current_level = config
        for part in parts[:-1]:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]
        current_level[parts[-1]] = value

    return config


def _create_client() -> Any:
    try:
        import boto3
    except ImportError as error:
        raise ImportError(
            "boto3 is required to resolve ssm_params; install the extra: mb-config[ssm]"
        ) from error

    return boto3.client("ssm")


def _fetch_parameter(client: Any, parameter_path: str, *, expected_type: str) -> str:
    try:
        response = client.get_parameter(
            Name=parameter_path, WithDecryption=expected_type == "SecureString"
        )
    except Exception as error:
        raise RuntimeError(f"Failed to fetch SSM parameter '{parameter_path}'") from error

    actual_type = response["Parameter"]["Type"]
    if actual_type != expected_type:
        raise RuntimeError(
            f"SSM parameter '{parameter_path}' has type '{actual_type}', expected '{expected_type}'"
        )

    return response["Parameter"]["Value"]
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `uv run pytest tests/test_ssm_param_loader.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mb_config/loaders/ssm_param_loader.py tests/test_ssm_param_loader.py
git commit -m "feat: validate ssm_params mapping and fail hard on fetch errors"
```

---

### Task 3: ConfigManager.add_ssm_parameters

**Files:**
- Modify: `src/mb_config/config_manager.py`
- Test: `tests/test_config_manager.py` (create)

**Interfaces:**
- Consumes: `load_ssm_parameters(mapping)` from Task 2 (imported into `mb_config.config_manager`; tests monkeypatch it there).
- Produces: `ConfigManager.add_ssm_parameters(self) -> Self` — pops `ssm_params` from the internal config, no-ops when absent/empty, otherwise merges the loader result. Task 4 calls this method.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_manager.py`:

```python
import mb_config.config_manager as config_manager_module
from mb_config.config_manager import ConfigManager


def test_add_ssm_parameters_resolves_and_removes_mapping(monkeypatch):
    received = {}

    def fake_load(mapping):
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
    assert manager.get_config() == {
        "database": {"host": "db.example.com", "password": "s3cret"}
    }


def test_add_ssm_parameters_is_noop_without_mapping(monkeypatch):
    def fail_load(mapping):
        raise AssertionError("load_ssm_parameters must not be called")

    monkeypatch.setattr(config_manager_module, "load_ssm_parameters", fail_load)

    manager = ConfigManager()
    manager.add_dict({"database": {"host": "db.example.com"}})
    result = manager.add_ssm_parameters()

    assert result is manager
    assert manager.get_config() == {"database": {"host": "db.example.com"}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_manager.py -v`
Expected: FAIL — `AttributeError: module 'mb_config.config_manager' has no attribute 'load_ssm_parameters'`.

- [ ] **Step 3: Implement the method**

In `src/mb_config/config_manager.py`, add the import after the existing loader imports:

```python
from mb_config.loaders.ssm_param_loader import load_ssm_parameters
```

Add the method to `ConfigManager` after `add_environment_variables`:

```python
    def add_ssm_parameters(self: Self) -> Self:
        mapping = self._config.pop("ssm_params", None)
        if not mapping:
            return self
        return self.add_dict(load_ssm_parameters(mapping))
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `uv run pytest -v`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mb_config/config_manager.py tests/test_config_manager.py
git commit -m "feat: add ConfigManager.add_ssm_parameters"
```

---

### Task 4: Wire into initialize_config before environment variables

**Files:**
- Modify: `src/mb_config/workloads.py`
- Test: `tests/test_workloads.py` (create)

**Interfaces:**
- Consumes: `ConfigManager.add_ssm_parameters()` from Task 3; the shared `config_manager` singleton and `initialize_config(config_folder_path)` from `mb_config.workloads` (existing).
- Produces: final behavior — `initialize_config` resolves `ssm_params` after YAML layers and before environment variables.

- [ ] **Step 1: Write the failing test**

Create `tests/test_workloads.py`:

```python
import pytest

import mb_config.config_manager as config_manager_module
from mb_config.config_manager import config_manager
from mb_config.workloads import initialize_config


@pytest.fixture(autouse=True)
def reset_shared_config():
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


def test_initialize_config_resolves_ssm_params_before_env_vars(tmp_path, monkeypatch):
    (tmp_path / "default.yaml").write_text(DEFAULT_YAML)

    def fake_load(mapping):
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
```

Note: the YAML keys must be quoted because they contain `:`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_workloads.py -v`
Expected: FAIL — `assert config["database"]["password"] == "ssm-password"` fails with `"placeholder-password"`, and `"ssm_params" not in config` would also fail (the mapping is never consumed).

- [ ] **Step 3: Wire the loader into initialize_config**

In `src/mb_config/workloads.py`, add one line so the end of `initialize_config` reads:

```python
    # resolve SSM parameters declared by the layers above
    config_manager.add_ssm_parameters()

    # load environment variables
    config_manager.add_environment_variables()

    return config_manager.get_config()
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `uv run pytest -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mb_config/workloads.py tests/test_workloads.py
git commit -m "feat: resolve ssm_params in initialize_config before env vars"
```
