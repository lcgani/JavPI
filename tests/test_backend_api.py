from fastapi.testclient import TestClient

import backend.app.main as backend_main


class _FakeSnap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return None if self._data is None else dict(self._data)


class _FakeDoc:
    def __init__(self):
        self.data = None
        self.subcollections = {}

    def set(self, payload, merge=False):
        incoming = dict(payload)
        if merge and isinstance(self.data, dict):
            base = dict(self.data)
            base.update(incoming)
            self.data = base
        else:
            self.data = incoming

    def get(self):
        return _FakeSnap(self.data)

    def collection(self, name):
        if name not in self.subcollections:
            self.subcollections[name] = _FakeCollection()
        return self.subcollections[name]


class _FakeCollection:
    def __init__(self):
        self.docs = {}

    def document(self, doc_id):
        key = str(doc_id)
        if key not in self.docs:
            self.docs[key] = _FakeDoc()
        return self.docs[key]


class _FakeDB:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = _FakeCollection()
        return self.collections[name]


def _client_with_fake_db(monkeypatch, api_key=""):
    monkeypatch.setattr(backend_main, "_db", _FakeDB())
    monkeypatch.setattr(backend_main, "_api_key", api_key)
    monkeypatch.setattr(backend_main, "_collection", "javpi_sessions")
    return TestClient(backend_main.app)


def test_session_flow(monkeypatch):
    client = _client_with_fake_db(monkeypatch)

    start_resp = client.post(
        "/v1/sessions/start",
        json={
            "session_id": "s1",
            "source": "desktop",
            "app_version": "0.1.0",
            "metadata": {"k": "v"},
        },
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["session_id"] == "s1"

    event_resp = client.post(
        "/v1/sessions/s1/events",
        json={"type": "tool_call", "payload": {"name": "mouse_click"}},
    )
    assert event_resp.status_code == 200

    end_resp = client.post(
        "/v1/sessions/s1/end",
        json={"status": "completed", "summary": {"ok": True}},
    )
    assert end_resp.status_code == 200

    get_resp = client.get("/v1/sessions/s1")
    assert get_resp.status_code == 200
    session = get_resp.json()["session"]
    assert session["session_id"] == "s1"
    assert session["status"] == "completed"


def test_event_requires_existing_session(monkeypatch):
    client = _client_with_fake_db(monkeypatch)
    resp = client.post(
        "/v1/sessions/missing/events",
        json={"type": "tool_call", "payload": {}},
    )
    assert resp.status_code == 404


def test_api_key_enforced(monkeypatch):
    client = _client_with_fake_db(monkeypatch, api_key="secret")

    unauthorized = client.post(
        "/v1/sessions/start",
        json={"session_id": "s2", "source": "desktop", "metadata": {}},
    )
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/v1/sessions/start",
        headers={"x-api-key": "secret"},
        json={"session_id": "s2", "source": "desktop", "metadata": {}},
    )
    assert authorized.status_code == 200
