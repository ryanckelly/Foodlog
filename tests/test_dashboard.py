import pytest
from fastapi.testclient import TestClient

def test_dashboard_index(client: TestClient):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "FoodLog" in response.text