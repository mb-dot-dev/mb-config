from pathlib import Path

from yamlrocks import load


def load_yaml(file_path: str, *, optional: bool) -> dict:
    path = Path(file_path)

    if optional and not path.exists():
        return {}

    content = load(path)
    if not isinstance(content, dict):
        msg = f"{file_path} must contain a top-level mapping, got {type(content).__name__}"
        raise TypeError(msg)
    return content
