"""End-to-end API tests via FastAPI TestClient (background loops running)."""

import time


def test_health_and_status(client):
    assert client.get("/health").json()["status"] == "ok"
    status = client.get("/api/status").json()
    assert status["status"] == "running"
    assert "version" in status


def test_state_has_expected_shape(client):
    time.sleep(0.4)  # allow a few ticks
    state = client.get("/api/state").json()
    assert len(state["state"]["assets"]) == 4
    assert state["impact"]["simulated"] is True
    assert "agent_status" in state


def test_inject_failure_validation(client):
    # Unknown failure type -> 422 (schema validation).
    assert client.post(
        "/api/inject-failure", json={"asset_id": "M1", "failure_type": "boom"}
    ).status_code == 422
    # Missing field -> 422.
    assert client.post("/api/inject-failure", json={"asset_id": "M1"}).status_code == 422


def test_inject_failure_and_unknown_asset(client):
    ok = client.post(
        "/api/inject-failure", json={"asset_id": "M1", "failure_type": "bearing_wear"}
    )
    assert ok.status_code == 200
    assert ok.json()["success"] is True
    missing = client.post(
        "/api/inject-failure", json={"asset_id": "ZZ", "failure_type": "bearing_wear"}
    )
    assert missing.status_code == 404


def test_maintenance_unknown_asset(client):
    assert client.post("/api/maintenance", json={"asset_id": "ZZ"}).status_code == 404


def test_integrations_endpoint(client):
    integrations = client.get("/api/integrations").json()["integrations"]
    assert any(i["key"] == "opcua" for i in integrations)


def test_impact_endpoint_has_methodology(client):
    impact = client.get("/api/impact").json()
    assert "snapshot" in impact
    assert "formulas" in impact["methodology"]


def test_impact_assumptions_update(client):
    resp = client.post(
        "/api/impact/assumptions", json={"downtime_cost_per_hour": 50000}
    ).json()
    assert resp["methodology"]["assumptions"]["downtime_cost_per_hour"] == 50000.0


def test_contact_endpoint(client):
    resp = client.post(
        "/api/contact",
        json={"name": "Yahia", "email": "y@x.com", "message": "Book a demo"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_analysis_endpoint(client):
    time.sleep(0.5)
    analysis = client.get("/api/analysis").json()
    assert "fleet_summary" in analysis
    assert "agent_status" in analysis


def test_websocket_initial_frame(client):
    with client.websocket_connect("/ws/live") as ws:
        frame = ws.receive_json()
    assert frame["type"] == "initial_state"
    assert "state" in frame


def test_reset(client):
    assert client.post("/api/reset").json()["success"] is True
