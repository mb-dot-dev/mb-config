# SSM Parameter Store Loader — Design

Date: 2026-07-12
Status: Approved design, pending implementation

## Purpose

Add an optional loader to `mb-config` that resolves values from AWS SSM
Parameter Store and merges them into the configuration. The loader activates
only when the already-merged configuration layers contain an `ssm_params`
mapping. The AWS SDK (`boto3`) is an optional extra, so the core package
stays dependency-free of AWS.

## Mapping syntax

```yaml
ssm_params:
  secure:/myapp/db/password: "database:credentials:password"
  string:/myapp/db/host: "database:host"
  secure:/myapp/api_key: "api_key"
```

- **Key** = `<type-prefix>:<ssm-parameter-path>`, split on the first `:`.
  - Prefix must be exactly `string` or `secure`. A missing or unknown prefix
    raises `ValueError` naming the offending key.
  - `secure:` fetches with `WithDecryption=True` and requires the parameter's
    `Type` to be `SecureString`; `string:` requires `Type` to be `String`.
    A mismatch raises `RuntimeError` naming the parameter path.
- **Value** = target path in the config dict, split on `:` into
  arbitrary-depth segments. `"foo:bar:baz"` assigns to
  `config["foo"]["bar"]["baz"]`; a single segment (`"api_key"`) assigns
  top-level. A non-string value raises `ValueError`.

## Components

### `src/mb_config/loaders/ssm_param_loader.py`

```python
def load_ssm_parameters(mapping: dict, client=None) -> dict: ...
```

- Takes only the `ssm_params` mapping (not the whole config) and returns a
  nested dict of resolved values, ready for `merge_configurations`.
- Imports `boto3` lazily inside the function. If the import fails, raises
  `ImportError` instructing the user to install `mb-config[ssm]`.
- When `client` is `None`, builds `boto3.client("ssm")` using the default
  credential/region chain. The `client` parameter is the testing seam.
- Fetches each entry with an individual `get_parameter` call. Config files
  list a handful of secrets at most, so per-parameter calls keep error
  attribution precise without meaningful overhead.

### `src/mb_config/config_manager.py`

```python
def add_ssm_parameters(self: Self) -> Self:
    mapping = self._config.pop("ssm_params", None)
    if not mapping:
        return self
    return self.add_dict(load_ssm_parameters(mapping))
```

- Follows the existing fluent-builder pattern.
- `pop` removes `ssm_params` from the final config — the mapping is loader
  plumbing, not application config.
- Complete no-op when `ssm_params` is absent: `boto3` is never imported, so
  installations without the extra are unaffected.

### `src/mb_config/workloads.py`

`initialize_config` calls the loader after the YAML layers and **before**
environment variables:

```python
# ... yaml layers ...
config_manager.add_ssm_parameters()
config_manager.add_environment_variables()
```

Consequences of this order:

- Environment variables override SSM-resolved values.
- The `ssm_params` mapping must be supplied by the YAML layers; environment
  variables cannot contribute to the mapping because it is consumed before
  they are merged.

### `pyproject.toml`

```toml
[project.optional-dependencies]
ssm = ["boto3>=1.34"]
```

A `dev` dependency group is added with `pytest` and `boto3` for tests.

## Error handling

All failures raise at load time (fail hard — a missing secret means the app
would run misconfigured, so crash at startup):

| Failure | Exception | Message contains |
|---|---|---|
| Bad/missing type prefix, non-string target | `ValueError` | the offending mapping key |
| `boto3` not installed while `ssm_params` present | `ImportError` | install hint for `mb-config[ssm]` |
| Parameter not found / access denied | `RuntimeError` | the SSM parameter path |
| Returned `Type` doesn't match the prefix | `RuntimeError` | the SSM parameter path and both types |

Secret values never appear in exception messages.

## Testing

New `tests/` directory using pytest. Unit tests inject a fake SSM client via
the `client` parameter — no moto, no network. Coverage:

- Happy path for both `string:` and `secure:` prefixes, including
  `WithDecryption` being set only for `secure:`.
- Arbitrary-depth target nesting and single-segment (top-level) targets.
- Multiple entries merging into one result dict.
- No-op when `ssm_params` is absent; `ssm_params` removed from final config
  when present.
- Each error class: bad prefix, non-string target, fetch failure,
  type mismatch.
- Lazy-import `ImportError` message, by simulating an absent `boto3`.
- `initialize_config` ordering: SSM values are overridable by environment
  variables.
