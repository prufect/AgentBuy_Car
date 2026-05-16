"""
Tests for agent.py — summary parsing, prompt building, LLM calls, and job runner.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from models import (
    CarListing, SearchRequest, ScoreBreakdown, ScoredCar,
    JobState, JobStatus,
)
from agent import (
    _parse_summaries,
    _build_summary_prompt,
    _call_llm,
    run_search_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_scored_car(title="2022 Toyota RAV4 XLE", price=28990, year=2022,
                    mileage=24500, source="CarMax", composite=85.0) -> ScoredCar:
    return ScoredCar(
        listing=CarListing(
            title=title,
            price=price,
            year=year,
            mileage=mileage,
            condition="Clean",
            features=["Backup Camera", "Bluetooth"],
            url="https://www.carmax.com/car/1",
            source=source,
            title_status="Clean",
        ),
        scores=ScoreBreakdown(
            price_value=90.0,
            year_depreciation=85.0,
            mileage=80.0,
            condition=95.0,
            feature_match=75.0,
            source_trust=95.0,
            composite=composite,
        ),
    )


def make_request(**kwargs) -> SearchRequest:
    defaults = dict(
        car_type="SUV",
        budget_min=20000,
        budget_max=30000,
        year_min=2018,
        year_max=2024,
        mileage_max=100000,
        must_have_features=[],
    )
    defaults.update(kwargs)
    return SearchRequest(**defaults)


# ---------------------------------------------------------------------------
# _parse_summaries
# ---------------------------------------------------------------------------

class TestParseSummaries:
    def test_valid_json_array(self):
        raw = '[{"car_index": 1, "summary": "Great value."}, {"car_index": 2, "summary": "Solid pick."}]'
        result = _parse_summaries(raw)
        assert result == {1: "Great value.", 2: "Solid pick."}

    def test_json_embedded_in_text(self):
        raw = 'Here are your summaries:\n[{"car_index": 1, "summary": "Nice car."}]\nEnd.'
        result = _parse_summaries(raw)
        assert result[1] == "Nice car."

    def test_empty_string_returns_empty_dict(self):
        assert _parse_summaries("") == {}

    def test_no_json_array_returns_empty_dict(self):
        assert _parse_summaries("Sorry, I cannot help with that.") == {}

    def test_malformed_json_returns_empty_dict(self):
        assert _parse_summaries("[{bad json here}]") == {}

    def test_missing_summary_field_skipped(self):
        raw = '[{"car_index": 1}, {"car_index": 2, "summary": "Good car."}]'
        result = _parse_summaries(raw)
        assert 1 not in result
        assert result[2] == "Good car."

    def test_missing_car_index_skipped(self):
        raw = '[{"summary": "Nice car."}]'
        result = _parse_summaries(raw)
        assert result == {}

    def test_multiple_cars(self):
        raw = '[{"car_index": 1, "summary": "A"}, {"car_index": 2, "summary": "B"}, {"car_index": 3, "summary": "C"}]'
        result = _parse_summaries(raw)
        assert len(result) == 3
        assert result[3] == "C"


# ---------------------------------------------------------------------------
# _build_summary_prompt
# ---------------------------------------------------------------------------

class TestBuildSummaryPrompt:
    def test_contains_car_title(self):
        cars = [make_scored_car(title="2022 Toyota RAV4 XLE")]
        req = make_request()
        prompt = _build_summary_prompt(cars, req)
        assert "2022 Toyota RAV4 XLE" in prompt

    def test_contains_price(self):
        cars = [make_scored_car(price=28990)]
        req = make_request()
        prompt = _build_summary_prompt(cars, req)
        assert "28,990" in prompt

    def test_contains_budget_range(self):
        cars = [make_scored_car()]
        req = make_request(budget_min=20000, budget_max=30000)
        prompt = _build_summary_prompt(cars, req)
        assert "20,000" in prompt
        assert "30,000" in prompt

    def test_contains_car_type(self):
        cars = [make_scored_car()]
        req = make_request(car_type="Sedan")
        prompt = _build_summary_prompt(cars, req)
        assert "Sedan" in prompt

    def test_multiple_cars_numbered(self):
        cars = [make_scored_car(title="Car A"), make_scored_car(title="Car B")]
        req = make_request()
        prompt = _build_summary_prompt(cars, req)
        assert "Car #1" in prompt
        assert "Car #2" in prompt

    def test_instructs_json_output(self):
        cars = [make_scored_car()]
        req = make_request()
        prompt = _build_summary_prompt(cars, req)
        assert "JSON" in prompt

    def test_contains_composite_score(self):
        cars = [make_scored_car(composite=85.0)]
        req = make_request()
        prompt = _build_summary_prompt(cars, req)
        assert "85.0" in prompt


# ---------------------------------------------------------------------------
# _call_llm
# ---------------------------------------------------------------------------

class TestCallLlm:
    @pytest.mark.asyncio
    async def test_uses_qwen_when_key_set(self):
        with patch("agent.QWEN_API_KEY", "test-key"), \
             patch("agent._call_qwen", new=AsyncMock(return_value="summary")) as mock_qwen, \
             patch("agent._call_tokenrouter", new=AsyncMock(return_value="fallback")):
            result = await _call_llm("prompt")
            mock_qwen.assert_called_once()
            assert result == "summary"

    @pytest.mark.asyncio
    async def test_falls_back_to_tokenrouter_when_qwen_fails(self):
        with patch("agent.QWEN_API_KEY", "test-key"), \
             patch("agent.TOKENROUTER_API_KEY", "tr-key"), \
             patch("agent._call_qwen", new=AsyncMock(return_value=None)), \
             patch("agent._call_tokenrouter", new=AsyncMock(return_value="fallback")) as mock_tr:
            result = await _call_llm("prompt")
            mock_tr.assert_called_once()
            assert result == "fallback"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_keys_set(self):
        with patch("agent.QWEN_API_KEY", ""), \
             patch("agent.TOKENROUTER_API_KEY", ""):
            result = await _call_llm("prompt")
            assert result is None

    @pytest.mark.asyncio
    async def test_skips_tokenrouter_when_qwen_succeeds(self):
        with patch("agent.QWEN_API_KEY", "test-key"), \
             patch("agent._call_qwen", new=AsyncMock(return_value="ok")), \
             patch("agent._call_tokenrouter", new=AsyncMock()) as mock_tr:
            await _call_llm("prompt")
            mock_tr.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_when_both_fail(self):
        with patch("agent.QWEN_API_KEY", "test-key"), \
             patch("agent.TOKENROUTER_API_KEY", "tr-key"), \
             patch("agent._call_qwen", new=AsyncMock(return_value=None)), \
             patch("agent._call_tokenrouter", new=AsyncMock(return_value=None)):
            result = await _call_llm("prompt")
            assert result is None


# ---------------------------------------------------------------------------
# run_search_job
# ---------------------------------------------------------------------------

class TestRunSearchJob:
    @pytest.mark.asyncio
    async def test_job_completes_with_results(self):
        job_id = "test-job-1"
        job_store = {job_id: JobState(job_id=job_id, created_at=datetime.now(timezone.utc).isoformat())}
        req = make_request()

        mock_cars = [make_scored_car(title=f"Car {i}", price=25000 + i * 1000) for i in range(3)]

        with patch("agent.scrape_carmax", new=AsyncMock(return_value=[c.listing for c in mock_cars])), \
             patch("agent.scrape_carvana", new=AsyncMock(return_value=[])), \
             patch("agent._call_llm", new=AsyncMock(return_value=None)):
            await run_search_job(job_id=job_id, request=req, job_store=job_store)

        state = job_store[job_id]
        assert state.status == JobStatus.completed
        assert state.result is not None
        assert state.result.total_found == 3

    @pytest.mark.asyncio
    async def test_job_status_is_running_then_completed(self):
        job_id = "test-job-2"
        job_store = {job_id: JobState(job_id=job_id, created_at=datetime.now(timezone.utc).isoformat())}
        req = make_request()

        with patch("agent.scrape_carmax", new=AsyncMock(return_value=[])), \
             patch("agent.scrape_carvana", new=AsyncMock(return_value=[])), \
             patch("agent._call_llm", new=AsyncMock(return_value=None)):
            await run_search_job(job_id=job_id, request=req, job_store=job_store)

        assert job_store[job_id].status == JobStatus.completed

    @pytest.mark.asyncio
    async def test_job_completes_with_no_results_when_nothing_scraped(self):
        job_id = "test-job-3"
        job_store = {job_id: JobState(job_id=job_id, created_at=datetime.now(timezone.utc).isoformat())}
        req = make_request()

        with patch("agent.scrape_carmax", new=AsyncMock(return_value=[])), \
             patch("agent.scrape_carvana", new=AsyncMock(return_value=[])):
            await run_search_job(job_id=job_id, request=req, job_store=job_store)

        state = job_store[job_id]
        assert state.status == JobStatus.completed
        assert state.result.total_found == 0

    @pytest.mark.asyncio
    async def test_both_scrapers_failing_completes_with_zero_results(self):
        # asyncio.gather(return_exceptions=True) catches scraper errors gracefully —
        # the job completes with 0 results rather than failing.
        job_id = "test-job-4"
        job_store = {job_id: JobState(job_id=job_id, created_at=datetime.now(timezone.utc).isoformat())}
        req = make_request()

        with patch("agent.scrape_carmax", new=AsyncMock(side_effect=Exception("network error"))), \
             patch("agent.scrape_carvana", new=AsyncMock(side_effect=Exception("network error"))):
            await run_search_job(job_id=job_id, request=req, job_store=job_store)

        state = job_store[job_id]
        assert state.status == JobStatus.completed
        assert state.result.total_found == 0

    @pytest.mark.asyncio
    async def test_job_fails_when_unhandled_exception_occurs(self):
        # Only truly unexpected errors (e.g. in score_cars) set status to failed.
        job_id = "test-job-4b"
        job_store = {job_id: JobState(job_id=job_id, created_at=datetime.now(timezone.utc).isoformat())}
        req = make_request()
        mock_listings = [make_scored_car().listing]

        with patch("agent.scrape_carmax", new=AsyncMock(return_value=mock_listings)), \
             patch("agent.scrape_carvana", new=AsyncMock(return_value=[])), \
             patch("agent.score_cars", side_effect=Exception("scoring crashed")):
            await run_search_job(job_id=job_id, request=req, job_store=job_store)

        state = job_store[job_id]
        assert state.status == JobStatus.failed
        assert "scoring crashed" in state.error

    @pytest.mark.asyncio
    async def test_summaries_merged_into_top_cars(self):
        job_id = "test-job-5"
        job_store = {job_id: JobState(job_id=job_id, created_at=datetime.now(timezone.utc).isoformat())}
        req = make_request()

        mock_listings = [make_scored_car(title=f"Car {i}").listing for i in range(3)]
        llm_response = '[{"car_index": 1, "summary": "Best deal around."}, {"car_index": 2, "summary": "Solid choice."}]'

        with patch("agent.scrape_carmax", new=AsyncMock(return_value=mock_listings)), \
             patch("agent.scrape_carvana", new=AsyncMock(return_value=[])), \
             patch("agent.QWEN_API_KEY", "test-key"), \
             patch("agent._call_llm", new=AsyncMock(return_value=llm_response)):
            await run_search_job(job_id=job_id, request=req, job_store=job_store)

        state = job_store[job_id]
        assert state.status == JobStatus.completed
        summaries = [car.summary for car in state.result.cars if car.summary]
        assert len(summaries) >= 1

    @pytest.mark.asyncio
    async def test_combines_carmax_and_carvana_results(self):
        job_id = "test-job-6"
        job_store = {job_id: JobState(job_id=job_id, created_at=datetime.now(timezone.utc).isoformat())}
        req = make_request()

        carmax_listings = [make_scored_car(title="CarMax Car", source="CarMax").listing]
        carvana_listings = [make_scored_car(title="Carvana Car", source="Carvana").listing]

        with patch("agent.scrape_carmax", new=AsyncMock(return_value=carmax_listings)), \
             patch("agent.scrape_carvana", new=AsyncMock(return_value=carvana_listings)), \
             patch("agent._call_llm", new=AsyncMock(return_value=None)):
            await run_search_job(job_id=job_id, request=req, job_store=job_store)

        state = job_store[job_id]
        assert state.result.total_found == 2
        sources = {car.listing.source for car in state.result.cars}
        assert "CarMax" in sources
        assert "Carvana" in sources
