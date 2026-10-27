"""Disposable local-chain fixture shared by live integration suites."""
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def get_node_binary():
    cmd = shutil.which("node")
    if cmd:
        return cmd
    bundled = Path(os.environ.get("USERPROFILE", "")) / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    if bundled.exists():
        return str(bundled)
    return "node"


@pytest.fixture(scope="module")
def live_chain(tmp_path_factory):
    """Use a disposable chain, never the user's running demo or saved records."""
    import socket
    from backend import registry as registry_module
    isolated = tmp_path_factory.mktemp("live-chain")
    (isolated / "scripts").mkdir()
    (isolated / "contracts").mkdir()
    # Keep module resolution anchored in this repository, with isolated runtime data.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    script = (ROOT / "scripts/chain.mjs").read_text().replace("8545", str(port))
    script_path = ROOT / ".local" / f"test-chain-{uuid.uuid4().hex}.mjs"
    script_path.parent.mkdir(exist_ok=True)
    script_path.write_text(script)
    shutil.copy(ROOT / "contracts/AuthenTraRegistry.sol", isolated / "contracts")
    log = open(isolated / "chain.log", "w+")
    chain_proc = subprocess.Popen([get_node_binary(), str(script_path)], cwd=isolated, stdout=log, stderr=log)
    try:
        for _ in range(100):
            time.sleep(0.2)
            if chain_proc.poll() is not None:
                pytest.fail("Disposable chain exited before readiness; inspect " + str(isolated / "chain.log"))
            config = isolated / ".local/chain.json"
            if config.exists() and json.loads(config.read_text()).get("bootstrapComplete"):
                break
        else:
            pytest.fail("Disposable chain readiness timed out; inspect " + str(isolated / "chain.log"))
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(registry_module, "ROOT", isolated)
            reg = registry_module.Registry()
            assert reg.health()
            # Deployment and both approvals must be mined with consecutive owner nonces.
            assert reg.w3.eth.get_transaction_count(reg.owner) == 3
            assert all(reg.approved(a) for a in list(reg.keys)[:2])
            address = reg.contract.address
            block = reg.w3.eth.block_number
            check = subprocess.run([get_node_binary(), str(script_path), "--check"], cwd=isolated, capture_output=True, timeout=15)
            assert check.returncode == 0
            assert reg.w3.eth.block_number == block
            # An occupied RPC port without matching metadata must fail, not report ready.
            backup = config.with_suffix(".backup")
            config.rename(backup)
            try:
                missing = subprocess.run([get_node_binary(), str(script_path), "--check"], cwd=isolated, capture_output=True, timeout=15)
                assert missing.returncode != 0
                assert b"Missing or incompatible" in missing.stderr
            finally:
                backup.rename(config)
            # Restart the initialized database: no redeployment or approval transactions.
            chain_proc.terminate()
            chain_proc.wait(timeout=10)
            chain_proc = subprocess.Popen([get_node_binary(), str(script_path)], cwd=isolated, stdout=log, stderr=log)
            for _ in range(100):
                time.sleep(0.2)
                if reg.health():
                    break
            assert reg.health()
            assert reg.contract.address == address
            assert reg.w3.eth.block_number == block
            yield reg
    finally:
        chain_proc.terminate()
        chain_proc.wait(timeout=10)
        log.close()
        script_path.unlink(missing_ok=True)

