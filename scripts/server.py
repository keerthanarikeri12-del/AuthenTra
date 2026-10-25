"""Explicit local demonstration entry point. Production uses backend.main:app directly."""
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
os.environ["AUTHENTRA_DEMO"] = "1"
import uvicorn
if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, log_level="info")
