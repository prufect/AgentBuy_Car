"""
AutoBrief Agent — Job runner + LLM summary generation.

Orchestrates the full search flow:
  1. Scrape CarMax & Carvana in parallel via Bright Data
  2. Score all listings with the weighted engine
  3. Generate AI summaries for top results via AgentField / TokenRouter
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional
from datetime import datetime, timezone

import httpx

from models import (
    SearchRequest,
    SearchProgress,
    SearchResult,
    ScoredCar,
    JobState,
    JobStatus,
)
from scraper import scrape_carmax, scrape_carvana
from scoring import score_cars

logger = logging.getLogger(__name__)

BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "")
AGENTFIELD_API_KEY = os.getenv("AGENTFIELD_API_KEY", "")
AGENTFIELD_URL = os.getenv("AGENTFIELD_URL", "https://api.agentfield.com/v1/chat/completions")

# TokenRouter as fallback LLM
TOKENROUTER_API_KEY = os.getenv("TOKENROUTER_API_KEY", "")
TOKENROUTER_URL = os.getenv("TOKENROUTER_URL", "https://api.tokenrouter.com/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")


# ---------------------------------------------------------------------------
# LLM summary generation
# ---------------------------------------------------------------------------

def _build_summary_prompt(cars: list[ScoredCar], request: SearchRequest) -> str:
    """Build the prompt for generating car summaries."""
    cars_text = ""
    for i, car in enumerate(cars, 1):
        cars_text += f"""
Car #{i}: {car.listing.title}
- Price: ${car.listing.price:,}
- Year: {car.listing.year or 'Unknown'}
- Mileage: {car.listing.mileage or 'Unknown'} miles
- Condition: {car.listing.condition}
- Source: {car.listing.source}
- Composite Score: {car.scores.composite}/100
- Score Breakdown: Price Value={car.scores.price_value}, Year={car.scores.year_depreciation}, Mileage={car.scores.mileage}, Condition={car.scores.condition}, Features={car.scores.feature_match}
"""

    return f"""You are an expert car buying advisor. A user is looking for a {request.car_type} with a budget of ${request.budget_min:,}-${request.budget_max:,}.

Here are the top matching cars:

{cars_text}

For each car, write exactly 2 sentences explaining why it's a good fit for this buyer. Be specific about the value proposition.

Respond ONLY with a valid JSON array (no markdown fences) where each element has:
{{ "car_index": 1, "summary": "Your 2-sentence summary here." }}

Index starts at 1 matching the car numbering above."""


async def _call_llm(prompt: str) -> Optional[str]:
    """Try AgentField first, then TokenRouter as fallback."""
    # Try AgentField
    if AGENTFIELD_API_KEY:
        result = await _call_agentfield(prompt)
        if result:
            return result

    # Try TokenRouter
    if TOKENROUTER_API_KEY:
        result = await _call_tokenrouter(prompt)
        if result:
            return result

    logger.warning("No LLM API key configured — skipping summary generation")
    return None


async def _call_agentfield(prompt: str) -> Optional[str]:
    """Call AgentField's chat completions endpoint."""
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            resp = await client.post(
                AGENTFIELD_URL,
                headers={
                    "Authorization": f"Bearer {AGENTFIELD_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2048,
                    "temperature": 0.3,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices")
                if choices:
                    return choices[0].get("message", {}).get("content")
                return data.get("content") or data.get("response") or data.get("text")
            logger.warning("AgentField %s: %s", resp.status_code, resp.text[:300])
            return None
        except Exception as exc:
            logger.error("AgentField error: %s", exc)
            return None


async def _call_tokenrouter(prompt: str) -> Optional[str]:
    """Call TokenRouter's chat completions endpoint."""
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            resp = await client.post(
                TOKENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {TOKENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2048,
                    "temperature": 0.3,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices")
                if choices:
                    return choices[0].get("message", {}).get("content")
                return None
            logger.warning("TokenRouter %s: %s", resp.status_code, resp.text[:300])
            return None
        except Exception as exc:
            logger.error("TokenRouter error: %s", exc)
            return None


def _parse_summaries(raw: str) -> dict[int, str]:
    """Parse LLM response into a dict of {car_index: summary}."""
    summaries = {}
    try:
        # Try to extract JSON array from the response
        match = re.search(r'\[[\s\S]*\]', raw)
        if not match:
            return summaries

        items = json.loads(match.group())
        for item in items:
            idx = item.get("car_index", 0)
            summary = item.get("summary", "")
            if idx and summary:
                summaries[idx] = summary
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse LLM summaries: %s", exc)

    return summaries


# ---------------------------------------------------------------------------
# Main job runner
# ---------------------------------------------------------------------------

async def run_search_job(
    job_id: str,
    request: SearchRequest,
    job_store: dict,
):
    """Run the full car search pipeline: scrape -> score -> summarize."""
    state: JobState = job_store[job_id]
    state.status = JobStatus.running

    try:
        # ── Step 1: Scrape ──────────────────────────────────────────────
        state.progress = "Scraping car listings..."
        state.progress_detail["scraping_carmax"] = SearchProgress(step="scraping_carmax", status="running")
        state.progress_detail["scraping_carvana"] = SearchProgress(step="scraping_carvana", status="running")

        carmax_task = scrape_carmax(
            car_type=request.car_type,
            budget_min=request.budget_min,
            budget_max=request.budget_max,
            api_key=BRIGHTDATA_API_KEY,
            year_min=request.year_min,
            year_max=request.year_max,
            mileage_max=request.mileage_max,
        )
        carvana_task = scrape_carvana(
            car_type=request.car_type,
            budget_min=request.budget_min,
            budget_max=request.budget_max,
            api_key=BRIGHTDATA_API_KEY,
            year_min=request.year_min,
            year_max=request.year_max,
            mileage_max=request.mileage_max,
        )

        results = await asyncio.gather(carmax_task, carvana_task, return_exceptions=True)

        carmax_listings = results[0] if not isinstance(results[0], Exception) else []
        carvana_listings = results[1] if not isinstance(results[1], Exception) else []

        if isinstance(results[0], Exception):
            logger.error("CarMax scrape failed: %s", results[0])
            state.progress_detail["scraping_carmax"] = SearchProgress(step="scraping_carmax", status="failed")
        else:
            state.progress_detail["scraping_carmax"] = SearchProgress(step="scraping_carmax", status="done")

        if isinstance(results[1], Exception):
            logger.error("Carvana scrape failed: %s", results[1])
            state.progress_detail["scraping_carvana"] = SearchProgress(step="scraping_carvana", status="failed")
        else:
            state.progress_detail["scraping_carvana"] = SearchProgress(step="scraping_carvana", status="done")

        all_listings = carmax_listings + carvana_listings
        logger.info("Total listings scraped: %d (CarMax: %d, Carvana: %d)",
                     len(all_listings), len(carmax_listings), len(carvana_listings))

        if not all_listings:
            state.status = JobStatus.completed
            state.progress = "No cars found matching your criteria."
            state.result = SearchResult(
                search_params=request,
                cars=[],
                total_found=0,
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
            return

        # ── Step 2: Score ───────────────────────────────────────────────
        state.progress = f"Scoring {len(all_listings)} cars..."
        state.progress_detail["scoring"] = SearchProgress(step="scoring", status="running")

        scored_cars = score_cars(all_listings, request)

        state.progress_detail["scoring"] = SearchProgress(step="scoring", status="done")

        # ── Step 3: Generate AI summaries for top cars ──────────────────
        top_cars = scored_cars[:5]  # Summarize top 5

        if top_cars and (AGENTFIELD_API_KEY or TOKENROUTER_API_KEY):
            state.progress = "Generating AI summaries..."
            state.progress_detail["generating_summaries"] = SearchProgress(
                step="generating_summaries", status="running"
            )

            prompt = _build_summary_prompt(top_cars, request)
            raw = await _call_llm(prompt)

            if raw:
                summaries = _parse_summaries(raw)
                for i, car in enumerate(top_cars, 1):
                    if i in summaries:
                        car.summary = summaries[i]

            state.progress_detail["generating_summaries"] = SearchProgress(
                step="generating_summaries", status="done"
            )

        # ── Done ────────────────────────────────────────────────────────
        state.result = SearchResult(
            search_params=request,
            cars=scored_cars,
            total_found=len(scored_cars),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        state.status = JobStatus.completed
        state.progress = f"Found {len(scored_cars)} cars!"

    except Exception as exc:
        logger.error("Job %s crashed: %s", job_id, exc, exc_info=True)
        state.status = JobStatus.failed
        state.error = str(exc)
        state.progress = "Search failed."
