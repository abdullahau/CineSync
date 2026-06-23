"""
Shared config loader. Import this from any notebook or script so
people/embedding-version/API-key settings live in exactly one place.

Usage:
    from config_loader import load_config
    config = load_config()
    people = config["people"]
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)
