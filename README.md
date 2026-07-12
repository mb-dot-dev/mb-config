# mb-config

Layered configuration loading for Python apps. `mb-config` merges YAML files,
AWS SSM parameters, and environment variables into a single configuration
dictionary, with later layers overriding earlier ones.

## Installation

```bash
uv add mb-config
```

If you need to resolve values from AWS SSM Parameter Store, install the
`ssm` extra (pulls in `boto3`):

```bash
uv add "mb-config[ssm]"
```

## Quick start

Create a config folder with a `default.yaml` and, optionally, one YAML file
per environment:

```
config/
  default.yaml
  dev.yaml
  staging.yaml
  prod.yaml
```

Then initialize the config once, at application startup:

```python
from mb_config import initialize_config, get_config

initialize_config("config")

config = get_config()
config["database"]["host"]
```

`get_config()` can be called anywhere else in your app afterwards to read
the already-loaded configuration.

## How layers are merged

`initialize_config(config_folder_path)` builds the configuration by merging,
in order (each layer overrides matching keys from the previous one):

1. `default.yaml` — required, always loaded.
2. `<environment>.yaml` — optional, loaded for the current environment (see
   below).
3. `secrets.yaml` — optional, only loaded when the environment is `dev`.
4. AWS SSM parameters — resolved from an `ssm_params` mapping, if present in
   the config loaded so far (see [SSM parameters](#ssm-parameters)).
5. Environment variables — always loaded last, so they can override
   anything above (see [Environment variables](#environment-variables)).

Dictionaries are merged recursively (deep merge); non-dict values are
replaced outright.

### Selecting the environment

The environment is read from the `CONFIG_ENV` environment variable and
defaults to `dev`:

```bash
CONFIG_ENV=staging python app.py
```

This loads `default.yaml`, then `staging.yaml` on top of it. When
`CONFIG_ENV` is unset (or `dev`), `secrets.yaml` is also loaded — a
convenient place for local, untracked secrets during development.

### Environment variables

Environment variables are merged on top of everything else. Double
underscores (`__`) in the variable name denote nesting, and keys are
lowercased:

```bash
DATABASE__HOST=env-host
```

```python
{"database": {"host": "env-host"}}
```

### SSM parameters

Declare which SSM parameters to resolve inside any of your YAML layers using
an `ssm_params` mapping. Keys are `"<type>:<parameter path>"`, values are
the target location in the config (`:`-separated for nesting):

```yaml
# default.yaml
ssm_params:
  "secure:/myapp/db/password": "database:password"
  "string:/myapp/db/host": "database:host"
```

`secure:` fetches a `SecureString` (with decryption); `string:` fetches a
plain `String`. Resolved values are merged into the config and the
`ssm_params` key itself is removed. SSM resolution requires the `ssm` extra
and valid AWS credentials in the environment; if a parameter's actual type
in SSM doesn't match the declared prefix, a `RuntimeError` is raised.

## Using `ConfigManager` directly

`initialize_config` is a convenience wrapper around `ConfigManager` for the
common "config folder + environment" layout. For custom setups, build the
configuration yourself:

```python
from mb_config.config_manager import ConfigManager

config = (
    ConfigManager()
    .add_yaml("config/default.yaml")
    .add_yaml("config/prod.yaml", optional=True)
    .add_ssm_parameters()
    .add_environment_variables()
    .get_config()
)
```

Available builder methods, each returning `self` so calls can be chained:

- `add_yaml(file_path, *, optional=False)` — merge in a YAML file. When
  `optional=True`, a missing file is silently skipped.
- `add_dict(to_merge_with)` — merge in an arbitrary dictionary.
- `add_environment_variables()` — merge in env vars (see above).
- `add_ssm_parameters()` — resolve and merge in the `ssm_params` mapping
  currently present in the config, then remove that key.
- `get_config()` — return the merged configuration dictionary.

## API reference

- `initialize_config(config_folder_path: str) -> dict` — loads and merges
  the standard layered configuration described above, using the shared,
  process-wide config instance.
- `get_config() -> dict` — returns the current merged configuration from
  the shared config instance.
- `reset_config() -> None` — clears the shared config instance. Mainly
  useful in tests.

## Development

```bash
make install-dev   # install dependencies
make test          # lint + unit tests
make coverage       # run tests with coverage report
```
