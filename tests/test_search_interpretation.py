import asyncio

from fastapi.testclient import TestClient

import agent
from main import app


def disable_llm(monkeypatch):
    monkeypatch.setattr(agent, "QWEN_API_KEY", "")
    monkeypatch.setattr(agent, "TOKENROUTER_API_KEY", "")


def test_complete_brief_returns_ready_search_request(monkeypatch):
    disable_llm(monkeypatch)

    result = asyncio.run(
        agent.interpret_search_query(
            "I need a reliable family SUV under $35k, 2019 or newer, "
            "under 65k miles, with Apple CarPlay and blind spot monitor."
        )
    )

    assert result.status == "ready"
    assert result.search_params is not None
    assert result.questions == []
    assert result.search_params.car_type == "SUV"
    assert result.search_params.budget_min == 0
    assert result.search_params.budget_max == 35000
    assert result.search_params.year_min == 2019
    assert result.search_params.mileage_max == 65000
    assert "Apple CarPlay" in result.search_params.must_have_features
    assert "Blind Spot Monitor" in result.search_params.must_have_features


def test_missing_budget_asks_required_budget_question(monkeypatch):
    disable_llm(monkeypatch)

    result = asyncio.run(agent.interpret_search_query("I need a family SUV with CarPlay."))

    assert result.status == "needs_clarification"
    assert result.search_params is None
    assert any(question.field == "budget_max" for question in result.questions)


def test_missing_body_style_asks_required_body_style_question(monkeypatch):
    disable_llm(monkeypatch)

    result = asyncio.run(agent.interpret_search_query("I need something under $30k with low miles."))

    assert result.status == "needs_clarification"
    assert result.search_params is None
    assert any(question.field == "car_type" for question in result.questions)


def test_clarifying_budget_answer_returns_ready_request(monkeypatch):
    disable_llm(monkeypatch)

    result = asyncio.run(
        agent.interpret_search_query(
            "I need something safe with low miles.\n\n"
            "Clarifying answers:\n"
            "What body style should I search for? SUV\n"
            "What's the highest price you want to consider? $30k"
        )
    )

    assert result.status == "ready"
    assert result.search_params is not None
    assert result.search_params.car_type == "SUV"
    assert result.search_params.budget_min == 0
    assert result.search_params.budget_max == 30000


def test_search_interpret_route_returns_ready_payload(monkeypatch):
    disable_llm(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/search/interpret",
        json={"query": "Weekend truck $22k-$45k, 2017 or newer, under 90k miles, backup camera."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["search_params"]["car_type"] == "Truck"
    assert data["search_params"]["budget_min"] == 22000
    assert data["search_params"]["budget_max"] == 45000
    assert data["search_params"]["year_min"] == 2017
    assert data["search_params"]["mileage_max"] == 90000


def test_search_interpret_route_rejects_empty_query():
    client = TestClient(app)

    response = client.post("/search/interpret", json={"query": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Search brief cannot be empty."
