import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "tasks.db"
LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

FRONTEND_DIST = (BASE_DIR.parent / "frontend" / "dist").resolve()

# Path prefix on THIS host that replaces the client's local prefix
# (payload `remap_path`, e.g. "/mnt/NAS" on submitter machines).
REMAP_PATH = Path(os.environ.get("REMAP_PATH", "~/NAS")).expanduser()
DEFAULT_OUTPUT_DIR = Path("~/convert").expanduser()
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CONVERTER_DIR = BASE_DIR.parent.parent / "pw-video-convert"
if str(CONVERTER_DIR) not in sys.path:
    sys.path.insert(0, str(CONVERTER_DIR))
