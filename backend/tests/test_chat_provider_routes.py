"""Exercise real chat routes so provider schemas cannot outrun routing guards."""
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import main
from app.provider_catalog import CLOUD_PROVIDER_IDS


@pytest.mark.parametrize("provider", CLOUD_PROVIDER_IDS)
def test_registered_cloud_provider_reaches_both_chat_routes(monkeypatch, provider):
    seen = []
    def answer(*args, **kwargs):
        seen.append(args[3])
        return {"answer": "fixture answer", "sources": [], "mode": "demo"}
    def prepare(*args, **kwargs):
        return {"direct": answer(*args, **kwargs)}
    monkeypatch.setattr(main, "run_agent", answer)
    monkeypatch.setattr(main, "prepare_stream_state", prepare)
    with TestClient(main.app) as client:
        for route in ("/api/chat", "/api/chat/stream"):
            response = client.post(route, json={"message": "hello", "model": provider, "client_id": str(uuid4())})
            assert response.status_code == 200, (provider, route, response.text)
            assert "fixture answer" in response.text
    assert seen == [provider, provider]
