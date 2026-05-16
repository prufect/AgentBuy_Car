"""
AutoBrief — AI-Powered Car Buying Platform
FastAPI backend with async job processing.
"""

import uuid
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from models import (
    SearchInterpretRequest,
    SearchInterpretResponse,
    SearchRequest,
    JobState,
    JobStatus,
    ScoredCar,
    CarListing,
    ScoreBreakdown,
    SearchResult,
)
from agent import interpret_search_query, run_search_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# In-memory job store — fine for single-instance hackathon deployment
job_store: dict[str, JobState] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AutoBrief starting up")
    yield
    logger.info("AutoBrief shutting down")


app = FastAPI(
    title="AutoBrief",
    description="AI-Powered Car Buying Platform — find, score, and rank the best cars for you",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Search endpoints
# ---------------------------------------------------------------------------

@app.post("/search", status_code=202)
async def start_search(req: SearchRequest, background_tasks: BackgroundTasks):
    """Start an async car search job. Returns a job_id to poll."""
    if req.budget_min > req.budget_max:
        raise HTTPException(status_code=400, detail="budget_min must be <= budget_max")
    if req.budget_max > 500000:
        raise HTTPException(status_code=400, detail="budget_max seems unreasonably high")

    job_id = str(uuid.uuid4())
    job_store[job_id] = JobState(
        job_id=job_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    background_tasks.add_task(
        run_search_job,
        job_id=job_id,
        request=req,
        job_store=job_store,
    )

    return {"job_id": job_id}


@app.post("/search/interpret", response_model=SearchInterpretResponse)
async def interpret_search(req: SearchInterpretRequest):
    """Turn a natural-language brief into search params or required questions."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Search brief cannot be empty.")

    return await interpret_search_query(req.query)


@app.get("/search/{job_id}")
async def get_search(job_id: str):
    """Poll for search job status and results."""
    state = job_store.get(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found.")

    return {
        "job_id": state.job_id,
        "status": state.status,
        "progress": state.progress,
        "progress_detail": {
            k: {"step": v.step, "status": v.status}
            for k, v in state.progress_detail.items()
        },
        "result": state.result.model_dump() if state.result else None,
        "error": state.error,
    }


# ---------------------------------------------------------------------------
# Mock endpoint — for frontend development without live scraping
# ---------------------------------------------------------------------------

@app.post("/search/test")
async def mock_search(req: SearchRequest):
    """Returns hardcoded scored cars so the frontend can be built independently."""
    mock_cars = [
        ScoredCar(
            listing=CarListing(
                title="2022 Toyota RAV4 XLE",
                price=28990,
                year=2022,
                mileage=24500,
                condition="Clean",
                features=["Backup Camera", "Bluetooth", "Apple CarPlay", "Lane Departure Warning"],
                url="https://www.carmax.com/car/12345",
                image_url="https://via.placeholder.com/400x250?text=2022+RAV4",
                source="CarMax",
                make="Toyota",
                model="RAV4",
                trim="XLE",
                title_status="Clean",
            ),
            scores=ScoreBreakdown(
                price_value=92.0,
                year_depreciation=88.0,
                mileage=85.0,
                condition=95.0,
                feature_match=75.0,
                source_trust=95.0,
                composite=89.3,
            ),
            summary="A well-priced 2022 RAV4 XLE with low mileage and a clean title. Great value for the budget with reliable Toyota engineering.",
        ),
        ScoredCar(
            listing=CarListing(
                title="2021 Honda CR-V EX",
                price=26500,
                year=2021,
                mileage=31000,
                condition="Clean",
                features=["Backup Camera", "Bluetooth", "Honda Sensing", "Sunroof"],
                url="https://www.carvana.com/vehicle/67890",
                image_url="https://via.placeholder.com/400x250?text=2021+CR-V",
                source="Carvana",
                make="Honda",
                model="CR-V",
                trim="EX",
                title_status="Clean",
            ),
            scores=ScoreBreakdown(
                price_value=95.0,
                year_depreciation=82.0,
                mileage=78.0,
                condition=95.0,
                feature_match=50.0,
                source_trust=90.0,
                composite=83.5,
            ),
            summary="Excellent budget fit with Honda's legendary reliability. Slightly higher mileage but well-maintained with Honda Sensing safety suite.",
        ),
        ScoredCar(
            listing=CarListing(
                title="2023 Hyundai Tucson SEL",
                price=27800,
                year=2023,
                mileage=12000,
                condition="Like New",
                features=["Backup Camera", "Bluetooth", "Wireless Charging", "Blind Spot Monitor"],
                url="https://www.carmax.com/car/54321",
                image_url="https://via.placeholder.com/400x250?text=2023+Tucson",
                source="CarMax",
                make="Hyundai",
                model="Tucson",
                trim="SEL",
                title_status="Clean",
            ),
            scores=ScoreBreakdown(
                price_value=93.0,
                year_depreciation=95.0,
                mileage=95.0,
                condition=98.0,
                feature_match=50.0,
                source_trust=95.0,
                composite=88.0,
            ),
            summary="Nearly new 2023 Tucson with just 12K miles — outstanding year and mileage scores. Modern tech features and still under factory warranty.",
        ),
    ]

    return SearchResult(
        search_params=req,
        cars=mock_cars,
        total_found=3,
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).model_dump()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "jobs": len(job_store)}


# ---------------------------------------------------------------------------
# Static files + SPA fallback
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")
