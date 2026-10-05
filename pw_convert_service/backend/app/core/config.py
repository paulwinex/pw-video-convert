from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent  # ..../pw_convert_service
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "tasks.db"
LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

FRONTEND_DIST = (BASE_DIR.parent / "frontend" / "dist").resolve()
