from pathlib import Path
from tomllib import load


def load_toml(file_path: str, *, optional: bool) -> dict:
    path = Path(file_path)

    if optional and not path.exists():
        return {}

    with path.open("rb") as file:
        return load(file)
