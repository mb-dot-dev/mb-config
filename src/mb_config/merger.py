def merge_configurations(base_config: dict, to_merge_with: dict) -> dict:
    for key, value in to_merge_with.items():
        if key in base_config and isinstance(base_config[key], dict) and isinstance(value, dict):
            base_config[key] = merge_configurations(base_config[key], value)
        else:
            base_config[key] = value
    return base_config
