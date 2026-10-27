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
import json
from urllib.request import urlopen

def is_port_in_use(port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(('127.0.0.1', port)) == 0

def demo_is_ready():
    try:
        with urlopen("http://127.0.0.1:8000/api/health", timeout=3) as response:
            health = json.load(response)
        ready = health.get("demo") is True and health.get("status") == "ready" and all(
            health.get(key) is True for key in ("blockchain", "database", "model"))
    except Exception:
        ready = False
    return ready

if __name__ == "__main__":
    if is_port_in_use(8000):
        ready = demo_is_ready()
        if not ready:
            sys.exit("Port 8000 is occupied, but a ready AuthenTra demo was not found. Inspect the existing service before restarting.")
        print("AuthenTra demo is already ready at http://127.0.0.1:8000.")
        sys.exit(0)
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, log_level="info")
