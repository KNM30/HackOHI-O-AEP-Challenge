import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = Path(os.environ.get("AEP_PROCESSED_DIR", ROOT / "data" / "processed"))
CORS_ORIGINS = os.environ.get("AEP_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
# Premise and historical damage points are rounded before display (~100 m at this latitude).
DISPLAY_ROUND_DECIMALS = 3
