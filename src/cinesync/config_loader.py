"""
Shared config loader. Import this from any notebook or script so
people/embedding-version/API-key settings live in exactly one place.

Usage:
    from config_loader import load_config
    config = load_config()
    people = config["people"]
"""

import os
import re
import yaml
from cinesync.paths import PROJECT_ROOT

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute_env_vars(value):
    if isinstance(value, str):

        def replace(match):
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                raise ValueError(
                    f"config.yaml references ${{{var_name}}}, but the environment "
                    f"variable {var_name} isn't set. Export it before running, e.g. "
                    f"`export {var_name}=your_value_here`."
                )
            return env_value

        return _ENV_VAR_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(v) for v in value]
    return value


def load_config():
    with open(PROJECT_ROOT / "config.yaml", "r") as f:
        raw = yaml.safe_load(f)
    return _substitute_env_vars(raw)


if __name__ == "__main__":
    print(load_config())
