from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
APP_DATA_DIR = REPO_ROOT / "app" / "data"

FIXTURES_DIR = EVALS_DIR / "fixtures"
DATASETS_DIR = EVALS_DIR / "datasets"
REPORTS_DIR = EVALS_DIR / "reports"
THRESHOLDS_PATH = EVALS_DIR / "thresholds.json"
