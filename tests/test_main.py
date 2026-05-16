"""
Tests for main.py — FastAPI endpoint behaviour.
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from main import app, job_store

client = TestClient(app)

VALID_PAYLOAD = {
    "car_type": "SUV",
    "budget_min": 20000,
    "budget_max": 30000,
    "year_min": 2018,
    "year_max": 2024,
    "mileage_max": 100000,
    "must_have_features": ["Backup Camera"],
    "condition": "Clean",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clear_jobs():
    job_store.clear()


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------

class TestPostSearch:
    def setup_method(self):
        clear_jobs()

    def test_valid_request_returns_202(self):
        with patch("main.run_search_job", new=AsyncMock()):
            res = client.post("/search", json=VALID_PAYLOAD)
        assert res.status_code == 202

    def test_valid_request_returns_job_id(self):
        with patch("main.run_search_job", new=AsyncMock()):
            res = client.post("/search", json=VALID_PAYLOAD)
        assert "job_id" in res.json()
        assert isinstance(res.json()["job_id"], str)

    def test_job_stored_after_request(self):
        with patch("main.run_search_job", new=AsyncMock()):
            res = client.post("/search", json=VALID_PAYLOAD)
        job_id = res.json()["job_id"]
        assert job_id in job_store

    def test_budget_min_greater_than_max_returns_400(self):
        payload = {**VALID_PAYLOAD, "budget_min": 30000, "budget_max": 20000}
        res = client.post("/search", json=payload)
        assert res.status_code == 400
        assert "budget_min" in res.json()["detail"]

    def test_budget_max_over_500k_returns_400(self):
        payload = {**VALID_PAYLOAD, "budget_max": 600000}
        res = client.post("/search", json=payload)
        assert res.status_code == 400

    def test_missing_required_fields_returns_422(self):
        res = client.post("/search", json={"car_type": "SUV"})
        assert res.status_code == 422

    def test_optional_fields_can_be_omitted(self):
        payload = {"car_type": "SUV", "budget_min": 20000, "budget_max": 30000}
        with patch("main.run_search_job", new=AsyncMock()):
            res = client.post("/search", json=payload)
        assert res.status_code == 202

    def test_each_request_gets_unique_job_id(self):
        with patch("main.run_search_job", new=AsyncMock()):
            id1 = client.post("/search", json=VALID_PAYLOAD).json()["job_id"]
            id2 = client.post("/search", json=VALID_PAYLOAD).json()["job_id"]
        assert id1 != id2


# ---------------------------------------------------------------------------
# GET /search/{job_id}
# ---------------------------------------------------------------------------

class TestGetSearch:
    def setup_method(self):
        clear_jobs()

    def _create_job(self) -> str:
        with patch("main.run_search_job", new=AsyncMock()):
            res = client.post("/search", json=VALID_PAYLOAD)
        return res.json()["job_id"]

    def test_known_job_id_returns_200(self):
        job_id = self._create_job()
        res = client.get(f"/search/{job_id}")
        assert res.status_code == 200

    def test_unknown_job_id_returns_404(self):
        res = client.get("/search/nonexistent-job-id")
        assert res.status_code == 404

    def test_response_contains_job_id(self):
        job_id = self._create_job()
        res = client.get(f"/search/{job_id}")
        assert res.json()["job_id"] == job_id

    def test_response_contains_status(self):
        job_id = self._create_job()
        res = client.get(f"/search/{job_id}")
        assert "status" in res.json()

    def test_response_contains_progress(self):
        job_id = self._create_job()
        res = client.get(f"/search/{job_id}")
        assert "progress" in res.json()

    def test_response_contains_progress_detail(self):
        job_id = self._create_job()
        res = client.get(f"/search/{job_id}")
        assert "progress_detail" in res.json()

    def test_response_contains_result_field(self):
        job_id = self._create_job()
        res = client.get(f"/search/{job_id}")
        assert "result" in res.json()

    def test_new_job_has_pending_or_running_status(self):
        job_id = self._create_job()
        res = client.get(f"/search/{job_id}")
        assert res.json()["status"] in ("pending", "running", "completed", "failed")


# ---------------------------------------------------------------------------
# POST /search/test
# ---------------------------------------------------------------------------

class TestPostSearchTest:
    def test_returns_200(self):
        res = client.post("/search/test", json=VALID_PAYLOAD)
        assert res.status_code == 200

    def test_returns_cars_list(self):
        res = client.post("/search/test", json=VALID_PAYLOAD)
        assert "cars" in res.json()
        assert isinstance(res.json()["cars"], list)

    def test_returns_non_empty_cars(self):
        res = client.post("/search/test", json=VALID_PAYLOAD)
        assert len(res.json()["cars"]) > 0

    def test_returns_total_found(self):
        res = client.post("/search/test", json=VALID_PAYLOAD)
        data = res.json()
        assert data["total_found"] == len(data["cars"])

    def test_returns_search_params(self):
        res = client.post("/search/test", json=VALID_PAYLOAD)
        assert "search_params" in res.json()

    def test_car_has_required_fields(self):
        res = client.post("/search/test", json=VALID_PAYLOAD)
        car = res.json()["cars"][0]
        assert "listing" in car
        assert "scores" in car
        assert "composite" in car["scores"]

    def test_car_listing_has_price(self):
        res = client.post("/search/test", json=VALID_PAYLOAD)
        listing = res.json()["cars"][0]["listing"]
        assert "price" in listing
        assert listing["price"] > 0

    def test_scores_are_within_range(self):
        res = client.post("/search/test", json=VALID_PAYLOAD)
        for car in res.json()["cars"]:
            scores = car["scores"]
            for key, val in scores.items():
                assert 0 <= val <= 100, f"Score {key}={val} out of range"


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestGetHealth:
    def test_returns_200(self):
        res = client.get("/health")
        assert res.status_code == 200

    def test_returns_status_ok(self):
        res = client.get("/health")
        assert res.json()["status"] == "ok"

    def test_returns_job_count(self):
        res = client.get("/health")
        assert "jobs" in res.json()
        assert isinstance(res.json()["jobs"], int)

    def test_job_count_reflects_store(self):
        clear_jobs()
        with patch("main.run_search_job", new=AsyncMock()):
            client.post("/search", json=VALID_PAYLOAD)
        res = client.get("/health")
        assert res.json()["jobs"] >= 1
