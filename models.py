"""
Pydantic models for AutoBrief — the data contract for the entire platform.
All team members code against these interfaces.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from enum import Enum


# ---------------------------------------------------------------------------
# Job lifecycle
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------------------
# User input
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    car_type: str = Field(
        ...,
        description="Body style: SUV, Sedan, Truck, Coupe, Hatchback, Van, Wagon, Convertible",
    )
    budget_min: int = Field(..., description="Minimum budget in USD")
    budget_max: int = Field(..., description="Maximum budget in USD")
    year_min: Optional[int] = Field(None, description="Oldest model year acceptable")
    year_max: Optional[int] = Field(None, description="Newest model year acceptable")
    mileage_max: Optional[int] = Field(None, description="Maximum mileage in miles")
    must_have_features: list[str] = Field(
        default_factory=list,
        description="Features the car must have, e.g. ['Backup Camera', 'Bluetooth', 'Leather Seats']",
    )
    condition: Optional[str] = Field(
        None,
        description="Preferred condition: Clean, Like New, Excellent, Good, Fair",
    )


class SearchInterpretRequest(BaseModel):
    query: str = Field(..., description="Natural-language car search brief")


class SearchClarifyingQuestion(BaseModel):
    id: str = Field(..., description="Stable question id for the frontend")
    question: str = Field(..., description="Question to ask before searching")
    field: str = Field(..., description="SearchRequest field this question fills")


class SearchInterpretResponse(BaseModel):
    status: Literal["ready", "needs_clarification"]
    search_params: Optional[SearchRequest] = None
    questions: list[SearchClarifyingQuestion] = Field(default_factory=list)
    summary: Optional[str] = Field(None, description="Short readable description of the interpreted search")
    source: Optional[str] = Field(None, description="Interpretation source: llm or local")


# ---------------------------------------------------------------------------
# Scraped car data (normalised from CarMax / Carvana)
# ---------------------------------------------------------------------------

class CarListing(BaseModel):
    title: str = Field(..., description="Full listing title, e.g. '2021 Toyota RAV4 XLE'")
    price: int = Field(..., description="Listed price in USD")
    year: Optional[int] = Field(None, description="Model year")
    mileage: Optional[int] = Field(None, description="Odometer reading in miles")
    condition: str = Field(default="Clean", description="Condition label")
    features: list[str] = Field(default_factory=list, description="Listed features / highlights")
    url: str = Field(..., description="Direct link to the listing")
    image_url: Optional[str] = Field(None, description="Thumbnail image URL")
    source: str = Field(..., description="Where we found it: 'CarMax' or 'Carvana'")
    make: Optional[str] = Field(None, description="Extracted make, e.g. 'Toyota'")
    model: Optional[str] = Field(None, description="Extracted model, e.g. 'RAV4'")
    trim: Optional[str] = Field(None, description="Trim level, e.g. 'XLE'")
    body_style: Optional[str] = Field(
        None,
        description="Body style from the listing, e.g. 'SUV', 'Sedan', 'Hatchback'",
    )
    accident_count: Optional[int] = Field(None, description="Number of reported accidents, if available")
    title_status: Optional[str] = Field(None, description="Title status: Clean, Rebuilt, Salvage")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class ScoreBreakdown(BaseModel):
    """All sub-scores are 0-100."""
    price_value: float = 0.0
    year_depreciation: float = 0.0
    mileage: float = 0.0
    condition: float = 0.0
    feature_match: float = 0.0
    source_trust: float = 0.0
    composite: float = 0.0


class ScoredCar(BaseModel):
    listing: CarListing
    scores: ScoreBreakdown
    summary: Optional[str] = Field(None, description="AI-generated 'Why this car fits you' summary")


# ---------------------------------------------------------------------------
# Job state (in-memory)
# ---------------------------------------------------------------------------

class SearchProgress(BaseModel):
    step: str = Field(..., description="e.g. 'scraping_carmax', 'scraping_carvana', 'scoring', 'generating_summaries'")
    status: str = "pending"  # pending | running | done | failed


class SearchResult(BaseModel):
    search_params: SearchRequest
    cars: list[ScoredCar] = []
    total_found: int = 0
    generated_at: str = ""


class JobState(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.pending
    progress: str = "Starting search..."
    progress_detail: dict[str, SearchProgress] = {}
    result: Optional[SearchResult] = None
    error: Optional[str] = None
    created_at: str = ""
