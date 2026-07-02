"""Basic API tests (no GPU models required)."""

from fastapi.testclient import TestClient

from voice_gpu_server.app import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "tts_loaded" in data
    assert "stt_loaded" in data


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "voice-gpu-server"
