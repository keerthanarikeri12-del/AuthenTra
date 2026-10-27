import os
os.environ["AUTHENTRA_DEMO"] = "1"
import json
from unittest.mock import Mock

from backend import documents, main
from backend.registry import Registry


def test_model_health_rejects_corrupt_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "ROOT", tmp_path)
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local/model.joblib").write_bytes(b"invalid model")
    assert documents.model_ready() is False


def test_model_health_accepts_predicting_model(tmp_path, monkeypatch):
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    monkeypatch.setattr(documents, "ROOT", tmp_path)
    (tmp_path / ".local").mkdir()
    model = RandomForestClassifier(n_estimators=2, random_state=1).fit([[0] * 10, [1] * 10], [0, 1])
    joblib.dump(model, tmp_path / ".local/model.joblib")
    assert documents.model_ready() is True


def test_health_degrades_when_model_unavailable(tmp_path, monkeypatch):
    from backend.storage import initialize
    monkeypatch.setenv("AUTHENTRA_DB", str(tmp_path / "health.db"))
    initialize()
    chain = Mock()
    chain.health.return_value = True
    chain.get_network_info.return_value = {"network_name": "Local", "chain_id": 1337}
    monkeypatch.setattr(main, "Registry", lambda: chain)
    monkeypatch.setattr(main, "model_ready", lambda: False)
    result = main.health()
    assert result["status"] == "degraded"
    assert result["blockchain"] is True
    assert result["database"] is True
    assert result["model"] is False


def test_network_failure_is_not_reported_as_local_chain():
    registry = Registry.__new__(Registry)
    registry.w3 = Mock()
    type(registry.w3.eth).chain_id = property(lambda self: (_ for _ in ()).throw(ConnectionError()))
    registry.contract = Mock(address="0x123")
    info = registry.get_network_info()
    assert info["chain_id"] is None
    assert info["network_name"] == "Blockchain unavailable"


def test_server_rejects_unrelated_or_degraded_listener(monkeypatch):
    import io
    from scripts import server
    for health in [{}, {"demo": True, "status": "degraded"},
                   {"demo": True, "status": "ready", "model": False, "blockchain": True, "database": True}]:
        monkeypatch.setattr(server, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(health).encode()))
        assert server.demo_is_ready() is False
    health = {"demo": True, "status": "ready", "model": True, "blockchain": True, "database": True}
    monkeypatch.setattr(server, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(health).encode()))
    assert server.demo_is_ready() is True


def test_demo_seed_does_not_restore_revoked_issuer_permission(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from scripts import seed_demo
    chain = Mock()
    chain.approved.return_value = False
    chain.lookup.return_value = {"revoked": True}
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {"wallet": "0x123"}
    @contextmanager
    def connect():
        yield conn
    monkeypatch.setattr(seed_demo, "ROOT", tmp_path)
    monkeypatch.setattr(seed_demo, "Registry", lambda: chain)
    monkeypatch.setattr(seed_demo, "initialize", lambda: None)
    monkeypatch.setattr(seed_demo, "seed_demo", lambda registry: None)
    monkeypatch.setattr(seed_demo, "connect", connect)
    seed_demo.prepare_demo()
    chain.set_issuer.assert_not_called()
    chain.revoke.assert_not_called()
