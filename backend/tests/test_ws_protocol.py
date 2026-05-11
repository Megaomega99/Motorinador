"""Tests for WebSocket protocol (commands and state updates)."""
import json
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.state import motor_state
from app.models import StatusFrame, Params


@pytest.fixture(autouse=True)
def reset_state():
    motor_state.params = Params()
    motor_state.last_status = None
    yield


def test_healthz():
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        assert "serial" in data


def test_get_params_returns_defaults():
    with TestClient(app) as client:
        r = client.get("/api/params")
        assert r.status_code == 200
        data = r.json()
        assert data["radius_cm"] == 12.0
        assert data["enc_ppr"] == 600


def test_update_params():
    with TestClient(app) as client:
        r = client.put("/api/params", json={"radius_cm": 8.5, "steps_per_rev": 200,
                                             "microsteps": 8, "enc_ppr": 600,
                                             "debounce_us": 50, "rpm_min": 5.0,
                                             "rpm_max": 120.0, "rpm_step": 5.0})
        assert r.status_code == 200
        assert r.json()["radius_cm"] == 8.5
        assert motor_state.params.radius_cm == 8.5


def test_get_state_503_when_no_status():
    with TestClient(app) as client:
        r = client.get("/api/state")
        assert r.status_code == 503


def test_get_state_returns_last_frame():
    motor_state.last_status = StatusFrame(
        target_rpm=30.0, real_rpm=29.8, angle_deg=142.3,
        dir="FWD", running=True, ts=0.0
    )
    with TestClient(app) as client:
        r = client.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert data["target_rpm"] == 30.0
        assert data["dir"] == "FWD"


def test_ws_receives_params_on_connect():
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # First message should be params or log buffer
            messages = []
            for _ in range(5):
                try:
                    msg = ws.receive_text(timeout=0.5)
                    messages.append(json.loads(msg))
                except Exception:
                    break
            types = [m.get("type") for m in messages]
            assert "params" in types


def test_ws_set_params_via_websocket():
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # Drain initial messages
            for _ in range(5):
                try:
                    ws.receive_text(timeout=0.3)
                except Exception:
                    break

            ws.send_text(json.dumps({
                "type": "set_params",
                "data": {
                    "radius_cm": 9.0, "steps_per_rev": 200,
                    "microsteps": 8, "enc_ppr": 600,
                    "debounce_us": 50, "rpm_min": 5.0,
                    "rpm_max": 120.0, "rpm_step": 5.0
                }
            }))
            # Should receive params update
            msg = json.loads(ws.receive_text(timeout=1.0))
            assert msg["type"] == "params"
            assert msg["data"]["radius_cm"] == 9.0
        assert motor_state.params.radius_cm == 9.0
