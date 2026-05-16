"""
Weighted multi-factor scoring engine for AutoBrief.

Each car gets a 0-100 composite score from 6 sub-scores:
  - Price Value (25%): How well the price fits the user's budget
  - Year / Depreciation (20%): Newer models score higher
  - Mileage (20%): Lower mileage scores higher, normalized per year
  - Condition (15%): Title status + condition label
  - Feature Match (10%): How many must-have features are present
  - Source Trust (10%): Trustworthiness of the source
"""

from models import CarListing, SearchRequest, ScoreBreakdown, ScoredCar

# Default weights — can be adjusted for personalization later
WEIGHTS = {
    "price_value": 0.25,
    "year_depreciation": 0.20,
    "mileage": 0.20,
    "condition": 0.15,
    "feature_match": 0.10,
    "source_trust": 0.10,
}

CURRENT_YEAR = 2026


# ---------------------------------------------------------------------------
# Sub-score calculators (each returns 0-100)
# ---------------------------------------------------------------------------

def score_price_value(car: CarListing, req: SearchRequest) -> float:
    """
    How well does the price fit the budget?
    - Sweet spot is 80% of budget_max (best value perception)
    - Over-budget gets penalized heavily
    - Under-budget gets diminishing returns
    """
    budget_min = req.budget_min
    budget_max = req.budget_max
    budget_range = budget_max - budget_min
    if budget_range <= 0:
        budget_range = 1

    sweet_spot = budget_min + (budget_range * 0.7)  # 70% into the range

    if car.price > budget_max:
        # Over budget: steep penalty
        over_pct = (car.price - budget_max) / budget_max
        return max(0, 60 - (over_pct * 200))

    if car.price < budget_min:
        # Under budget: slight bonus with diminishing returns
        under_pct = (budget_min - car.price) / budget_range
        return min(100, 85 + under_pct * 30)

    # Within budget: score based on proximity to sweet spot
    distance = abs(car.price - sweet_spot) / budget_range
    return min(100, 95 - (distance * 30))


def score_year_depreciation(car: CarListing, req: SearchRequest) -> float:
    """
    Newer cars score higher, with diminishing returns.
    Uses user's year_min as the floor if set, otherwise 2015.
    """
    if car.year is None:
        return 50.0  # Unknown year gets a neutral score

    min_year = req.year_min or 2015
    max_year = req.year_max or CURRENT_YEAR

    year_range = max_year - min_year
    if year_range <= 0:
        year_range = 1

    # Score linearly within range, bonus for newest
    if car.year >= max_year:
        return 100.0
    if car.year <= min_year:
        return 20.0

    ratio = (car.year - min_year) / year_range
    return 20 + (ratio * 80)


def score_mileage(car: CarListing, req: SearchRequest) -> float:
    """
    Lower mileage scores higher. Normalized per year of age.
    Average US driver: ~14,000 miles/year.
    """
    if car.mileage is None:
        return 50.0  # Unknown mileage gets neutral score

    max_mileage = req.mileage_max or 150000

    # If over the user's max, heavy penalty
    if car.mileage > max_mileage:
        over_pct = (car.mileage - max_mileage) / max_mileage
        return max(0, 40 - (over_pct * 100))

    # Score inversely proportional to mileage
    ratio = 1 - (car.mileage / max_mileage)
    return 40 + (ratio * 60)


def score_condition(car: CarListing, req: SearchRequest) -> float:
    """
    Based on title status and condition label.
    Clean title + Like New = best. Salvage = worst.
    """
    score = 70.0  # Base score

    # Title status adjustment
    title_scores = {
        "clean": 30,
        "Clean": 30,
        "rebuilt": 10,
        "Rebuilt": 10,
        "salvage": -30,
        "Salvage": -30,
    }
    if car.title_status:
        score += title_scores.get(car.title_status, 0)
    else:
        score += 25  # Assume clean if not reported

    # Condition label adjustment
    condition_scores = {
        "Like New": 15,
        "like new": 15,
        "Excellent": 12,
        "excellent": 12,
        "Clean": 8,
        "Good": 5,
        "good": 5,
        "Fair": -5,
        "fair": -5,
        "Poor": -15,
        "poor": -15,
    }
    score += condition_scores.get(car.condition, 5)  # Default mild positive

    # Accident penalty
    if car.accident_count is not None:
        score -= car.accident_count * 10

    return max(0, min(100, score))


def score_feature_match(car: CarListing, req: SearchRequest) -> float:
    """
    Ratio of user's must-have features present in the listing.
    If no features requested, returns 75 (neutral-positive).
    """
    if not req.must_have_features:
        return 75.0  # No feature requirements = no penalty

    car_features_lower = [f.lower() for f in car.features]
    matched = 0
    for feature in req.must_have_features:
        if any(feature.lower() in cf for cf in car_features_lower):
            matched += 1

    ratio = matched / len(req.must_have_features)
    return ratio * 100


def score_source_trust(car: CarListing, req: SearchRequest) -> float:
    """
    Trustworthiness of the data source.
    CarMax certified pre-owned > Carvana > unknown.
    """
    trust_scores = {
        "CarMax": 95.0,
        "carmax": 95.0,
        "Carvana": 90.0,
        "carvana": 90.0,
    }
    return trust_scores.get(car.source, 70.0)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def score_car(car: CarListing, request: SearchRequest) -> ScoredCar:
    """Score a single car listing against the user's search request."""

    price_val = score_price_value(car, request)
    year_dep = score_year_depreciation(car, request)
    mileage = score_mileage(car, request)
    condition = score_condition(car, request)
    feature = score_feature_match(car, request)
    source = score_source_trust(car, request)

    composite = (
        price_val * WEIGHTS["price_value"]
        + year_dep * WEIGHTS["year_depreciation"]
        + mileage * WEIGHTS["mileage"]
        + condition * WEIGHTS["condition"]
        + feature * WEIGHTS["feature_match"]
        + source * WEIGHTS["source_trust"]
    )

    breakdown = ScoreBreakdown(
        price_value=round(price_val, 1),
        year_depreciation=round(year_dep, 1),
        mileage=round(mileage, 1),
        condition=round(condition, 1),
        feature_match=round(feature, 1),
        source_trust=round(source, 1),
        composite=round(composite, 1),
    )

    return ScoredCar(listing=car, scores=breakdown)


def score_cars(cars: list[CarListing], request: SearchRequest) -> list[ScoredCar]:
    """Score and sort a list of cars by composite score (descending)."""
    scored = [score_car(car, request) for car in cars]
    scored.sort(key=lambda s: s.scores.composite, reverse=True)
    return scored
