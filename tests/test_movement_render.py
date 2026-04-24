from fastapi.templating import Jinja2Templates
from fastapi import Request
from starlette.datastructures import Headers

TEMPLATES = Jinja2Templates(directory="foodlog/templates")


def _fake_request():
    scope = {"type": "http", "headers": Headers().raw, "method": "GET", "path": "/"}
    return Request(scope)


def test_movement_partial_empty_state_renders():
    html = TEMPLATES.get_template("dashboard/movement_partial.html").render(
        workouts=[],
        sleep=None,
        weight=None,
        net_calories=None,
    )
    assert "Movement" in html
    assert "No movement or recovery data" in html


def test_movement_partial_renders_workout_card():
    html = TEMPLATES.get_template("dashboard/movement_partial.html").render(
        workouts=[{
            "activity_type": "Run",
            "distance_km": 6.8,
            "duration_min": 42,
            "calories_kcal": 410,
            "avg_hr": 152,
            "max_hr": 174,
            "hr_samples": [{"pct": 30}, {"pct": 55}, {"pct": 95}],
        }],
        sleep={"duration_min": 387, "resting_hr": 58},
        weight={"weight_kg": 81.4, "delta_kg": -0.3, "body_fat_pct": 19.2},
        net_calories=None,
    )
    assert "Run" in html
    assert "6.8" in html
    assert "42" in html
    assert "6h 27m" in html  # 387 min formatted
    assert "81.4" in html


def test_health_connect_page_renders_prompt():
    html = TEMPLATES.get_template("dashboard/health_connect.html").render()
    assert "Connect Google Health" in html
    assert '/health/connect' in html
