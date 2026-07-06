from pathlib import Path
from importlib.resources import files

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/cinesync/ -> root
DATA_DIR = PROJECT_ROOT / "data"
DB_SCHEMA_PATH = files("cinesync").joinpath("schemas").joinpath("schema.sql")
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
LOGS_DIR = DATA_DIR / "logs"
