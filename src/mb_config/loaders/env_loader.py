import os


def load_environment_variables() -> dict:
    """
    Load configuration based on the environment variables.
    The loader creates a dictionary from the variables.
    When the environment variable has double underscores (__),
    then it is treated as a nested dictionary.
    E.g. The FOO__BAR=baz returns
    ```{
        "foo": {
            "bar": "baz"
        }
    }```
    """
    config = {}

    for key, value in os.environ.items():
        parts = key.lower().split("__")
        current_level = config

        for part in parts[:-1]:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]

        current_level[parts[-1]] = value

    return config
