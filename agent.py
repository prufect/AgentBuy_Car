"""
AutoBrief Agent — Job runner + LLM summary generation.

Orchestrates the full search flow:
  1. Scrape CarMax & Carvana in parallel via Bright Data
  2. Score all listings with the weighted engine
  3. Generate AI summaries for top results via Qwen Cloud / TokenRouter
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from models import (
    SearchClarifyingQuestion,
    SearchInterpretResponse,
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

# Primary LLM — Qwen Cloud (claim credits: https://tinyurl.com/qwencloudcredits)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_URL = os.getenv("QWEN_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")

# Fallback LLM — TokenRouter (claim credits: https://tinyurl.com/tokenroutercredits)
TOKENROUTER_API_KEY = os.getenv("TOKENROUTER_API_KEY", "")
TOKENROUTER_URL = os.getenv("TOKENROUTER_URL", "https://api.tokenrouter.com/v1/chat/completions")

LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")

BODY_STYLES = ["SUV", "Sedan", "Truck", "Coupe", "Hatchback", "Van", "Wagon", "Convertible"]
CONDITIONS = ["Like New", "Excellent", "Clean", "Good", "Fair"]
FEATURE_PATTERNS = {
    "Backup Camera": [r"\bbackup camera\b", r"\brear camera\b", r"\brearview camera\b"],
    "Bluetooth": [r"\bbluetooth\b"],
    "Apple CarPlay": [r"\bapple carplay\b", r"\bcarplay\b"],
    "Android Auto": [r"\bandroid auto\b"],
    "Leather Seats": [r"\bleather\b", r"\bleather seats\b"],
    "Sunroof": [r"\bsunroof\b", r"\bmoonroof\b"],
    "Navigation": [r"\bnavigation\b", r"\bnav\b"],
    "Heated Seats": [r"\bheated seats\b", r"\bheated front seats\b"],
    "Blind Spot Monitor": [r"\bblind spot\b", r"\bblind-spot\b"],
    "Lane Departure Warning": [r"\blane departure\b", r"\blane keeping\b", r"\blane keep\b"],
    "Remote Start": [r"\bremote start\b"],
    "4WD/AWD": [r"\b4wd\b", r"\bawd\b", r"\ball wheel drive\b", r"\bfour wheel drive\b"],
}


# ---------------------------------------------------------------------------
# LLM search interpretation
# ---------------------------------------------------------------------------

def _build_interpret_prompt(query: str) -> str:
    body_styles = ", ".join(BODY_STYLES)
    conditions = ", ".join(CONDITIONS)
    features = ", ".join(FEATURE_PATTERNS.keys())

    return f"""You convert used-car search briefs into structured search parameters.

Return ONLY a valid JSON object with this shape:
{{
  "search_params": {{
    "car_type": "SUV",
    "budget_min": 0,
    "budget_max": 35000,
    "year_min": 2019,
    "year_max": null,
    "mileage_max": 65000,
    "must_have_features": ["Apple CarPlay"],
    "condition": null
  }}
}}

Allowed car_type values: {body_styles}
Allowed condition values: {conditions}
Allowed feature values: {features}

Rules:
- Required fields are car_type, budget_min, and budget_max.
- If the user gives only a max budget, set budget_min to 0.
- Do not invent required fields. Use null for unknown values.
- Use integers for money, years, and mileage.
- Include optional fields only when the user says or strongly implies them.

User brief:
{query}"""


async def interpret_search_query(query: str) -> SearchInterpretResponse:
    """Convert a natural-language brief into search params or required questions."""
    cleaned = query.strip()
    if not cleaned:
        return _response_from_partial({}, "local")

    if QWEN_API_KEY or TOKENROUTER_API_KEY:
        prompt = _build_interpret_prompt(cleaned)
        raw = await _call_llm(prompt)
        if raw:
            parsed = _parse_interpret_json(raw)
            if parsed:
                partial = _coerce_partial_params(parsed.get("search_params", parsed))
                response = _response_from_partial(partial, "llm")
                if response.status == "ready":
                    return response

    return _response_from_partial(_extract_local_search_params(cleaned), "local")


def _parse_interpret_json(raw: str) -> Optional[dict[str, Any]]:
    """Parse an LLM JSON object, tolerating accidental wrapper text."""
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None
        try:
            parsed = json.loads(match.group())
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def _coerce_partial_params(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    partial: dict[str, Any] = {}
    for key in (
        "car_type",
        "budget_min",
        "budget_max",
        "year_min",
        "year_max",
        "mileage_max",
        "must_have_features",
        "condition",
    ):
        value = raw.get(key)
        if value is not None:
            partial[key] = value

    if "car_type" in partial:
        partial["car_type"] = _normalize_car_type(str(partial["car_type"]))
    if "condition" in partial:
        partial["condition"] = _normalize_condition(str(partial["condition"]))
    if "must_have_features" in partial:
        features = partial["must_have_features"]
        if isinstance(features, list):
            partial["must_have_features"] = _normalize_features([str(feature) for feature in features])
        else:
            partial["must_have_features"] = []

    for key in ("budget_min", "budget_max", "year_min", "year_max", "mileage_max"):
        if key in partial:
            partial[key] = _safe_int(partial[key])

    return partial


def _extract_local_search_params(query: str) -> dict[str, Any]:
    lowered = query.lower()
    partial: dict[str, Any] = {}

    car_type = _extract_car_type(lowered)
    if car_type:
        partial["car_type"] = car_type

    budget_min, budget_max = _extract_budget(lowered)
    if budget_min is not None:
        partial["budget_min"] = budget_min
    if budget_max is not None:
        partial["budget_max"] = budget_max

    year_min, year_max = _extract_years(lowered)
    if year_min is not None:
        partial["year_min"] = year_min
    if year_max is not None:
        partial["year_max"] = year_max

    mileage_max = _extract_mileage(lowered)
    if mileage_max is not None:
        partial["mileage_max"] = mileage_max

    features = _extract_features(lowered)
    if features:
        partial["must_have_features"] = features

    condition = _extract_condition(lowered)
    if condition:
        partial["condition"] = condition

    return partial


def _response_from_partial(partial: dict[str, Any], source: str) -> SearchInterpretResponse:
    params = _coerce_partial_params(partial)
    questions = _required_questions(params)
    if questions:
        return SearchInterpretResponse(status="needs_clarification", questions=questions, source=source)

    if params.get("budget_min") is None:
        params["budget_min"] = 0

    try:
        request = SearchRequest(
            car_type=params["car_type"],
            budget_min=params["budget_min"],
            budget_max=params["budget_max"],
            year_min=params.get("year_min"),
            year_max=params.get("year_max"),
            mileage_max=params.get("mileage_max"),
            must_have_features=params.get("must_have_features", []),
            condition=params.get("condition"),
        )
    except (KeyError, ValidationError, TypeError, ValueError):
        return SearchInterpretResponse(
            status="needs_clarification",
            questions=_required_questions(params),
            source=source,
        )

    if request.budget_min > request.budget_max:
        request.budget_min, request.budget_max = request.budget_max, request.budget_min

    return SearchInterpretResponse(
        status="ready",
        search_params=request,
        questions=[],
        summary=_summarize_search_request(request),
        source=source,
    )


def _required_questions(params: dict[str, Any]) -> list[SearchClarifyingQuestion]:
    questions: list[SearchClarifyingQuestion] = []
    if not params.get("car_type"):
        questions.append(
            SearchClarifyingQuestion(
                id="car_type",
                field="car_type",
                question="What body style should I search for?",
            )
        )
    if params.get("budget_max") is None:
        questions.append(
            SearchClarifyingQuestion(
                id="budget_max",
                field="budget_max",
                question="What's the highest price you want to consider?",
            )
        )
    return questions


def _summarize_search_request(request: SearchRequest) -> str:
    parts = [request.car_type, f"${request.budget_min:,}-${request.budget_max:,}"]
    if request.year_min:
        parts.append(f"{request.year_min}+")
    if request.mileage_max:
        parts.append(f"under {request.mileage_max:,} miles")
    if request.must_have_features:
        parts.append(", ".join(request.must_have_features))
    return " / ".join(parts)


def _extract_car_type(lowered: str) -> Optional[str]:
    aliases = {
        "SUV": [r"\bsuvs?\b", r"\bcrossover\b", r"\bcrossovers\b"],
        "Sedan": [r"\bsedans?\b", r"\bcommuter car\b"],
        "Truck": [r"\btrucks?\b", r"\bpickups?\b", r"\bpick-up\b"],
        "Coupe": [r"\bcoupes?\b"],
        "Hatchback": [r"\bhatchbacks?\b"],
        "Van": [r"\bvans?\b", r"\bminivans?\b"],
        "Wagon": [r"\bwagons?\b"],
        "Convertible": [r"\bconvertibles?\b"],
    }
    for car_type, patterns in aliases.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            return car_type
    return None


def _extract_budget(lowered: str) -> tuple[Optional[int], Optional[int]]:
    range_match = re.search(
        r"\$\s*(\d+(?:\.\d+)?)\s*([kK])?\s*(?:-|to|and)\s*\$?\s*(\d+(?:\.\d+)?)\s*([kK])?",
        lowered,
    )
    if range_match:
        low = _parse_amount(range_match.group(1), range_match.group(2))
        high = _parse_amount(range_match.group(3), range_match.group(4))
        return (min(low, high), max(low, high))

    max_match = re.search(
        r"(?:under|below|less than|up to|max(?:imum)?|budget(?: of)?)\s*\$+\s*(\d+(?:\.\d+)?)\s*([kK])?",
        lowered,
    )
    if max_match:
        return (0, _parse_amount(max_match.group(1), max_match.group(2)))

    price_answer_match = re.search(
        r"(?:highest price|price|budget|spend|pay)[^\n$]{0,80}\$\s*(\d+(?:\.\d+)?)\s*([kK])?",
        lowered,
    )
    if price_answer_match:
        return (0, _parse_amount(price_answer_match.group(1), price_answer_match.group(2)))

    budget_match = re.search(r"\bbudget(?: of| is)?\s*(\d{4,6})\b", lowered)
    if budget_match:
        return (0, int(budget_match.group(1)))

    money_matches = re.findall(r"\$\s*(\d+(?:\.\d+)?)\s*([kK])?", lowered)
    if len(money_matches) == 1:
        amount, suffix = money_matches[0]
        return (0, _parse_amount(amount, suffix))

    return (None, None)


def _extract_years(lowered: str) -> tuple[Optional[int], Optional[int]]:
    range_match = re.search(r"\b(19\d{2}|20\d{2})\s*(?:-|to)\s*(19\d{2}|20\d{2})\b", lowered)
    if range_match:
        low = int(range_match.group(1))
        high = int(range_match.group(2))
        return (min(low, high), max(low, high))

    newer_match = re.search(r"\b(19\d{2}|20\d{2})\s*(?:or\s+newer|or\s+later|and\s+newer|\+)", lowered)
    if newer_match:
        return (int(newer_match.group(1)), None)

    after_match = re.search(r"\b(?:newer than|after)\s*(19\d{2}|20\d{2})\b", lowered)
    if after_match:
        return (int(after_match.group(1)) + 1, None)

    return (None, None)


def _extract_mileage(lowered: str) -> Optional[int]:
    match = re.search(
        r"(?:under|below|less than|up to|max(?:imum)?)\s*(\d+(?:\.\d+)?)\s*([kK])?\s*(?:miles|mi\b)",
        lowered,
    )
    if match:
        return _parse_amount(match.group(1), match.group(2))

    low_miles_match = re.search(r"\blow miles?\b|\blow mileage\b", lowered)
    if low_miles_match:
        return 65000

    return None


def _extract_features(lowered: str) -> list[str]:
    features = []
    for feature, patterns in FEATURE_PATTERNS.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            features.append(feature)
    return features


def _extract_condition(lowered: str) -> Optional[str]:
    for condition in CONDITIONS:
        if re.search(rf"\b{re.escape(condition.lower())}\b", lowered):
            return condition
    return None


def _normalize_car_type(value: str) -> Optional[str]:
    lowered = value.lower()
    for car_type in BODY_STYLES:
        if lowered == car_type.lower() or lowered == f"{car_type.lower()}s":
            return car_type
    return _extract_car_type(lowered)


def _normalize_condition(value: str) -> Optional[str]:
    lowered = value.lower()
    for condition in CONDITIONS:
        if lowered == condition.lower():
            return condition
    return None


def _normalize_features(values: list[str]) -> list[str]:
    normalized = []
    for value in values:
        lowered = value.lower()
        for feature, patterns in FEATURE_PATTERNS.items():
            if feature not in normalized and (
                lowered == feature.lower() or any(re.search(pattern, lowered) for pattern in patterns)
            ):
                normalized.append(feature)
    return normalized


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_amount(value: str, suffix: Optional[str]) -> int:
    amount = float(value)
    if suffix or amount < 1000:
        amount *= 1000
    return int(amount)


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
    """Try Qwen Cloud first, then TokenRouter as fallback."""
    # Try Qwen Cloud (primary)
    if QWEN_API_KEY:
        result = await _call_qwen(prompt)
        if result:
            return result

    # Try TokenRouter (fallback)
    if TOKENROUTER_API_KEY:
        result = await _call_tokenrouter(prompt)
        if result:
            return result

    logger.warning("No LLM API key configured — skipping summary generation")
    return None


async def _call_qwen(prompt: str) -> Optional[str]:
    """Call Qwen Cloud (DashScope) chat completions endpoint."""
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            resp = await client.post(
                QWEN_URL,
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
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
                return data.get("output", {}).get("text")
            logger.warning("Qwen %s: %s", resp.status_code, resp.text[:300])
            return None
        except Exception as exc:
            logger.error("Qwen error: %s", exc)
            return None


async def _call_tokenrouter(prompt: str) -> Optional[str]:
    """Call TokenRouter chat completions endpoint."""
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

        if top_cars and (QWEN_API_KEY or TOKENROUTER_API_KEY):
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
