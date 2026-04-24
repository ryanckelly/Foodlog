"""PWA assets must be reachable without auth so browsers can install the app."""
from fastapi.testclient import TestClient


def test_manifest_public_and_correct_content_type(raw_client: TestClient):
    response = raw_client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    body = response.json()
    assert body["start_url"] == "/dashboard"
    assert body["theme_color"] == "#0075de"
    assert any(icon["sizes"] == "512x512" for icon in body["icons"])


def test_service_worker_public_and_scoped_to_root(raw_client: TestClient):
    response = raw_client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers.get("service-worker-allowed") == "/"


def test_static_icons_public(raw_client: TestClient):
    response = raw_client.get("/static/icon-192.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
