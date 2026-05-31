from fastapi.testclient import TestClient

from api.server import create_app


def test_api_health():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_api_plan_non_stream_returns_plan_structure():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/plan",
        json={"query": "2人去北京3天，预算3000", "stream": False, "max_revisions": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == "北京"
    assert "itinerary" in data
    assert "hotels" in data
    assert data["budget_status"] in {"within_budget", "over_budget"}


def test_api_plan_stream_returns_sse_events():
    client = TestClient(create_app())
    with client.stream(
        "POST",
        "/api/v1/plan",
        json={"query": "2人去北京3天，预算3000", "stream": True, "max_revisions": 3},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(list(resp.iter_text()))
    assert "agent_update" in body
    assert "complete" in body
