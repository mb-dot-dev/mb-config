import subprocess
import sys

import pytest

from mb_config.loaders.ssm_param_loader import load_ssm_parameters


class FakeSsmClient:
    """Minimal stand-in for boto3's SSM client: path -> (type, value)."""

    def __init__(self, parameters: dict) -> None:
        self._parameters = parameters
        self.calls: list[dict] = []

    def get_parameter(self, *, Name: str, WithDecryption: bool = False) -> dict:  # noqa: N803
        self.calls.append({"Name": Name, "WithDecryption": WithDecryption})
        if Name not in self._parameters:
            msg = f"ParameterNotFound: {Name}"
            raise LookupError(msg)
        parameter_type, value = self._parameters[Name]
        return {"Parameter": {"Name": Name, "Type": parameter_type, "Value": value}}


def test_loads_string_parameter_without_decryption() -> None:
    client = FakeSsmClient({"/myapp/db/host": ("String", "db.example.com")})

    result = load_ssm_parameters({"string:/myapp/db/host": "database:host"}, client=client)

    assert result == {"database": {"host": "db.example.com"}}
    assert client.calls == [{"Name": "/myapp/db/host", "WithDecryption": False}]


def test_loads_secure_string_parameter_with_decryption() -> None:
    client = FakeSsmClient({"/myapp/db/password": ("SecureString", "s3cret")})

    result = load_ssm_parameters({"secure:/myapp/db/password": "database:password"}, client=client)

    assert result == {"database": {"password": "s3cret"}}
    assert client.calls == [{"Name": "/myapp/db/password", "WithDecryption": True}]


def test_target_supports_arbitrary_nesting_depth() -> None:
    client = FakeSsmClient({"/myapp/db/password": ("SecureString", "s3cret")})

    result = load_ssm_parameters({"secure:/myapp/db/password": "database:credentials:password"}, client=client)

    assert result == {"database": {"credentials": {"password": "s3cret"}}}


def test_single_segment_target_assigns_top_level() -> None:
    client = FakeSsmClient({"/myapp/api_key": ("SecureString", "key-123")})

    result = load_ssm_parameters({"secure:/myapp/api_key": "api_key"}, client=client)

    assert result == {"api_key": "key-123"}


def test_multiple_entries_merge_into_one_result() -> None:
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


def test_key_without_prefix_raises_value_error() -> None:
    with pytest.raises(ValueError, match="/myapp/db/host"):
        load_ssm_parameters({"/myapp/db/host": "database:host"}, client=FakeSsmClient({}))


def test_unknown_prefix_raises_value_error() -> None:
    with pytest.raises(ValueError, match="secret:/myapp/db/host"):
        load_ssm_parameters({"secret:/myapp/db/host": "database:host"}, client=FakeSsmClient({}))


def test_empty_parameter_path_raises_value_error() -> None:
    with pytest.raises(ValueError, match="secure:"):
        load_ssm_parameters({"secure:": "database:password"}, client=FakeSsmClient({}))


def test_non_string_target_raises_value_error() -> None:
    with pytest.raises(ValueError, match="secure:/myapp/db/password"):
        load_ssm_parameters(
            {"secure:/myapp/db/password": ["database", "password"]},
            client=FakeSsmClient({}),
        )


def test_fetch_failure_raises_runtime_error_naming_the_path() -> None:
    client = FakeSsmClient({})  # parameter does not exist

    with pytest.raises(RuntimeError, match="/myapp/db/password"):
        load_ssm_parameters({"secure:/myapp/db/password": "database:password"}, client=client)


def test_type_mismatch_raises_runtime_error_without_leaking_the_value() -> None:
    client = FakeSsmClient({"/myapp/db/password": ("String", "s3cret")})

    with pytest.raises(RuntimeError, match="SecureString") as excinfo:
        load_ssm_parameters({"secure:/myapp/db/password": "database:password"}, client=client)

    assert "s3cret" not in str(excinfo.value)


def test_missing_boto3_raises_import_error_with_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "boto3", None)  # makes `import boto3` fail

    with pytest.raises(ImportError, match=r"mb-config\[ssm\]"):
        load_ssm_parameters({"secure:/myapp/db/password": "database:password"})


def test_non_dict_mapping_raises_type_error() -> None:
    with pytest.raises(TypeError, match="ssm_params"):
        load_ssm_parameters("not-a-mapping", client=FakeSsmClient({}))


def test_importing_mb_config_does_not_import_boto3() -> None:
    code = (
        "import sys\n"
        "import mb_config.workloads\n"
        "import mb_config.config_manager\n"
        "assert 'boto3' not in sys.modules, 'boto3 must only be imported lazily'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603
