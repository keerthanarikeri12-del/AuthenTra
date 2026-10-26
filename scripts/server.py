"""Explicit local demonstration entry point. Production uses backend.main:app directly."""
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
os.environ["AUTHENTRA_DEMO"] = "1"
import uvicorn
import socket

def is_port_in_use(port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(('127.0.0.1', port)) == 0

if __name__ == "__main__":
    if is_port_in_use(8000):
        print("AuthenTra FastAPI server is ALREADY running on http://127.0.0.1:8000.")
        print("No action needed. If you want to restart it from scratch, run .\\stop-backend.ps1 first.")
        sys.exit(0)
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, log_level="info")
