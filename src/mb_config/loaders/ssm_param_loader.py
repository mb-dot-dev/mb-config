from typing import Protocol, cast

_TYPE_BY_PREFIX = {"string": "String", "secure": "SecureString"}


class SsmClient(Protocol):
    def get_parameter(self, *, Name: str, WithDecryption: bool = False) -> dict: ...  # noqa: N803


def load_ssm_parameters(mapping: object, client: SsmClient | None = None) -> dict:
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
    if not isinstance(mapping, dict):
        msg = "ssm_params must be a mapping of '<prefix>:<path>' keys to target path strings"
        raise TypeError(msg)
    checked_mapping = cast("dict[str, str]", mapping)
    if client is None:
        client = _create_client()

    config: dict = {}

    for key, target in checked_mapping.items():
        prefix, _, parameter_path = key.partition(":")
        if prefix not in _TYPE_BY_PREFIX or not parameter_path:
            msg = f"Invalid ssm_params key '{key}': expected 'string:<path>' or 'secure:<path>'"
            raise ValueError(msg)
        if not isinstance(target, str) or not target:
            msg = f"Invalid ssm_params target for key '{key}': expected a non-empty string"
            raise ValueError(msg)

        value = _fetch_parameter(client, parameter_path, expected_type=_TYPE_BY_PREFIX[prefix])

        parts = target.split(":")
        current_level = config
        for part in parts[:-1]:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]
        current_level[parts[-1]] = value

    return config


def _create_client() -> SsmClient:
    try:
        import boto3  # noqa: PLC0415
    except ImportError as error:
        msg = "boto3 is required to resolve ssm_params; install the extra: mb-config[ssm]"
        raise ImportError(msg) from error

    return boto3.client("ssm")


def _fetch_parameter(client: SsmClient, parameter_path: str, *, expected_type: str) -> str:
    try:
        response = client.get_parameter(Name=parameter_path, WithDecryption=expected_type == "SecureString")
    except Exception as error:
        msg = f"Failed to fetch SSM parameter '{parameter_path}'"
        raise RuntimeError(msg) from error

    actual_type = response["Parameter"]["Type"]
    if actual_type != expected_type:
        msg = f"SSM parameter '{parameter_path}' has type '{actual_type}', expected '{expected_type}'"
        raise RuntimeError(msg)

    return response["Parameter"]["Value"]
