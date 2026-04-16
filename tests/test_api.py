import datetime


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "fatsecret" in data
    assert "usda" in data


def test_create_entry(client):
    resp = client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken Breast",
                "quantity": 1.0,
                "unit": "serving",
                "weight_g": 150.0,
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "source_id": "33691",
                "raw_input": "grilled chicken breast",
            }
        ],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 1
    assert data[0]["food_name"] == "Chicken Breast"
    assert data[0]["id"] is not None


def test_get_entries_today(client):
    client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken Breast",
                "quantity": 1.0,
                "unit": "serving",
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "raw_input": "chicken",
            }
        ],
    )
    resp = client.get("/entries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


def test_get_entries_filter_meal_type(client):
    client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken",
                "quantity": 1.0,
                "unit": "serving",
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "raw_input": "chicken",
            }
        ],
    )
    resp = client.get("/entries", params={"meal_type": "dinner"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_update_entry(client):
    create_resp = client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken",
                "quantity": 1.0,
                "unit": "serving",
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "raw_input": "chicken",
            }
        ],
    )
    entry_id = create_resp.json()[0]["id"]

    resp = client.put(f"/entries/{entry_id}", json={"quantity": 2.0, "calories": 495.0})
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 2.0
    assert resp.json()["calories"] == 495.0


def test_update_nonexistent_entry(client):
    resp = client.put("/entries/999", json={"quantity": 2.0})
    assert resp.status_code == 404


def test_delete_entry(client):
    create_resp = client.post(
        "/entries",
        json=[
            {
                "meal_type": "snack",
                "food_name": "Apple",
                "quantity": 1.0,
                "unit": "medium",
                "calories": 95.0,
                "protein_g": 0.5,
                "carbs_g": 25.0,
                "fat_g": 0.3,
                "source": "usda",
                "raw_input": "apple",
            }
        ],
    )
    entry_id = create_resp.json()[0]["id"]

    resp = client.delete(f"/entries/{entry_id}")
    assert resp.status_code == 204

    resp = client.get("/entries")
    assert resp.json() == []


def test_delete_nonexistent_entry(client):
    resp = client.delete("/entries/999")
    assert resp.status_code == 404
