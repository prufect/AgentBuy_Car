"""
Tests for scoring.py — all sub-score functions and the composite scorer.
"""

import pytest
from models import CarListing, SearchRequest, ScoreBreakdown
from scoring import (
    score_price_value,
    score_year_depreciation,
    score_mileage,
    score_condition,
    score_feature_match,
    score_source_trust,
    score_cars,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_car(**kwargs) -> CarListing:
    defaults = dict(
        title="2022 Toyota RAV4 XLE",
        price=25000,
        year=2022,
        mileage=30000,
        condition="Clean",
        features=[],
        url="https://www.carmax.com/car/1",
        source="CarMax",
        title_status="Clean",
    )
    defaults.update(kwargs)
    return CarListing(**defaults)


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
# score_price_value
# ---------------------------------------------------------------------------

class TestScorePriceValue:
    def test_within_budget_near_sweet_spot(self):
        # Sweet spot is 70% into range: 20000 + (10000 * 0.7) = 27000
        car = make_car(price=27000)
        req = make_request(budget_min=20000, budget_max=30000)
        score = score_price_value(car, req)
        assert score >= 90

    def test_over_budget_penalized(self):
        car = make_car(price=35000)
        req = make_request(budget_min=20000, budget_max=30000)
        score = score_price_value(car, req)
        assert score < 60

    def test_well_over_budget_approaches_zero(self):
        car = make_car(price=60000)
        req = make_request(budget_min=20000, budget_max=30000)
        score = score_price_value(car, req)
        assert score == 0

    def test_under_budget_gets_bonus(self):
        car = make_car(price=15000)
        req = make_request(budget_min=20000, budget_max=30000)
        score = score_price_value(car, req)
        assert score >= 85

    def test_under_budget_capped_at_100(self):
        car = make_car(price=1000)
        req = make_request(budget_min=20000, budget_max=30000)
        score = score_price_value(car, req)
        assert score <= 100

    def test_score_always_between_0_and_100(self):
        req = make_request(budget_min=20000, budget_max=30000)
        for price in [0, 10000, 20000, 25000, 30000, 40000, 100000]:
            score = score_price_value(make_car(price=price), req)
            assert 0 <= score <= 100, f"Out of range for price={price}: {score}"

    def test_equal_budget_min_max_no_crash(self):
        car = make_car(price=25000)
        req = make_request(budget_min=25000, budget_max=25000)
        score = score_price_value(car, req)
        assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# score_year_depreciation
# ---------------------------------------------------------------------------

class TestScoreYearDepreciation:
    def test_unknown_year_returns_neutral(self):
        car = make_car(year=None)
        req = make_request(year_min=2018, year_max=2024)
        assert score_year_depreciation(car, req) == 50.0

    def test_newest_year_returns_100(self):
        car = make_car(year=2024)
        req = make_request(year_min=2018, year_max=2024)
        assert score_year_depreciation(car, req) == 100.0

    def test_oldest_year_returns_20(self):
        car = make_car(year=2018)
        req = make_request(year_min=2018, year_max=2024)
        assert score_year_depreciation(car, req) == 20.0

    def test_mid_range_year_interpolated(self):
        car = make_car(year=2021)
        req = make_request(year_min=2018, year_max=2024)
        score = score_year_depreciation(car, req)
        assert 20 < score < 100

    def test_newer_car_scores_higher_than_older(self):
        req = make_request(year_min=2018, year_max=2024)
        older = score_year_depreciation(make_car(year=2019), req)
        newer = score_year_depreciation(make_car(year=2023), req)
        assert newer > older

    def test_score_always_between_0_and_100(self):
        req = make_request(year_min=2018, year_max=2024)
        for year in [2010, 2018, 2021, 2024, 2026]:
            score = score_year_depreciation(make_car(year=year), req)
            assert 0 <= score <= 100, f"Out of range for year={year}: {score}"

    def test_no_year_bounds_uses_defaults(self):
        car = make_car(year=2020)
        req = make_request(year_min=None, year_max=None)
        score = score_year_depreciation(car, req)
        assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# score_mileage
# ---------------------------------------------------------------------------

class TestScoreMileage:
    def test_unknown_mileage_returns_neutral(self):
        car = make_car(mileage=None)
        req = make_request(mileage_max=100000)
        assert score_mileage(car, req) == 50.0

    def test_zero_miles_scores_highest(self):
        car = make_car(mileage=0)
        req = make_request(mileage_max=100000)
        score = score_mileage(car, req)
        assert score == 100.0

    def test_at_mileage_max_scores_low(self):
        car = make_car(mileage=100000)
        req = make_request(mileage_max=100000)
        score = score_mileage(car, req)
        assert score == 40.0

    def test_over_mileage_max_penalized(self):
        car = make_car(mileage=120000)
        req = make_request(mileage_max=100000)
        score = score_mileage(car, req)
        assert score < 40

    def test_well_over_mileage_max_approaches_zero(self):
        car = make_car(mileage=500000)
        req = make_request(mileage_max=100000)
        score = score_mileage(car, req)
        assert score == 0

    def test_lower_mileage_scores_higher(self):
        req = make_request(mileage_max=100000)
        low = score_mileage(make_car(mileage=10000), req)
        high = score_mileage(make_car(mileage=80000), req)
        assert low > high

    def test_no_mileage_max_uses_default(self):
        car = make_car(mileage=50000)
        req = make_request(mileage_max=None)
        score = score_mileage(car, req)
        assert 0 <= score <= 100

    def test_score_always_between_0_and_100(self):
        req = make_request(mileage_max=100000)
        for mileage in [0, 25000, 100000, 150000, 300000]:
            score = score_mileage(make_car(mileage=mileage), req)
            assert 0 <= score <= 100, f"Out of range for mileage={mileage}: {score}"


# ---------------------------------------------------------------------------
# score_condition
# ---------------------------------------------------------------------------

class TestScoreCondition:
    def test_clean_title_like_new_condition(self):
        car = make_car(title_status="Clean", condition="Like New", accident_count=0)
        req = make_request()
        score = score_condition(car, req)
        assert score >= 90

    def test_salvage_title_scores_low(self):
        car = make_car(title_status="Salvage", condition="Fair")
        req = make_request()
        score = score_condition(car, req)
        assert score < 50

    def test_rebuilt_title_mid_range(self):
        car = make_car(title_status="Rebuilt", condition="Good")
        req = make_request()
        score = score_condition(car, req)
        clean = score_condition(make_car(title_status="Clean", condition="Good"), req)
        salvage = score_condition(make_car(title_status="Salvage", condition="Good"), req)
        assert salvage < score < clean

    def test_no_title_status_assumes_clean(self):
        car = make_car(title_status=None, condition="Clean")
        req = make_request()
        score = score_condition(car, req)
        assert score >= 70

    def test_accidents_reduce_score(self):
        req = make_request()
        no_accidents = score_condition(make_car(accident_count=0), req)
        one_accident = score_condition(make_car(accident_count=1), req)
        two_accidents = score_condition(make_car(accident_count=2), req)
        assert no_accidents > one_accident > two_accidents

    def test_no_accident_count_no_crash(self):
        car = make_car(accident_count=None)
        req = make_request()
        score = score_condition(car, req)
        assert 0 <= score <= 100

    def test_score_always_between_0_and_100(self):
        req = make_request()
        for title, condition in [
            ("Clean", "Like New"), ("Salvage", "Poor"),
            ("Rebuilt", "Fair"), (None, "Good"),
        ]:
            car = make_car(title_status=title, condition=condition, accident_count=5)
            score = score_condition(car, req)
            assert 0 <= score <= 100, f"Out of range for title={title}, condition={condition}: {score}"


# ---------------------------------------------------------------------------
# score_feature_match
# ---------------------------------------------------------------------------

class TestScoreFeatureMatch:
    def test_no_features_required_returns_75(self):
        car = make_car(features=["Backup Camera", "Bluetooth"])
        req = make_request(must_have_features=[])
        assert score_feature_match(car, req) == 75.0

    def test_all_features_matched_returns_100(self):
        car = make_car(features=["Backup Camera", "Bluetooth", "Apple CarPlay"])
        req = make_request(must_have_features=["Backup Camera", "Bluetooth"])
        assert score_feature_match(car, req) == 100.0

    def test_no_features_matched_returns_0(self):
        car = make_car(features=["Sunroof"])
        req = make_request(must_have_features=["Backup Camera", "Bluetooth"])
        assert score_feature_match(car, req) == 0.0

    def test_partial_match(self):
        car = make_car(features=["Backup Camera", "Sunroof"])
        req = make_request(must_have_features=["Backup Camera", "Bluetooth"])
        score = score_feature_match(car, req)
        assert score == 50.0

    def test_case_insensitive_matching(self):
        car = make_car(features=["backup camera", "bluetooth"])
        req = make_request(must_have_features=["Backup Camera", "Bluetooth"])
        assert score_feature_match(car, req) == 100.0

    def test_partial_string_match(self):
        # "Apple CarPlay" contains "CarPlay"
        car = make_car(features=["Apple CarPlay"])
        req = make_request(must_have_features=["CarPlay"])
        assert score_feature_match(car, req) == 100.0

    def test_car_has_no_features(self):
        car = make_car(features=[])
        req = make_request(must_have_features=["Backup Camera"])
        assert score_feature_match(car, req) == 0.0


# ---------------------------------------------------------------------------
# score_source_trust
# ---------------------------------------------------------------------------

class TestScoreSourceTrust:
    def test_carmax_scores_95(self):
        assert score_source_trust(make_car(source="CarMax"), make_request()) == 95.0

    def test_carvana_scores_90(self):
        assert score_source_trust(make_car(source="Carvana"), make_request()) == 90.0

    def test_unknown_source_scores_70(self):
        assert score_source_trust(make_car(source="Autotrader"), make_request()) == 70.0

    def test_carmax_beats_carvana(self):
        req = make_request()
        assert score_source_trust(make_car(source="CarMax"), req) > score_source_trust(make_car(source="Carvana"), req)


# ---------------------------------------------------------------------------
# score_cars (composite + sorting)
# ---------------------------------------------------------------------------

class TestScoreCars:
    def test_returns_same_count(self):
        cars = [make_car(price=25000), make_car(price=26000), make_car(price=27000)]
        req = make_request()
        result = score_cars(cars, req)
        assert len(result) == 3

    def test_sorted_by_composite_descending(self):
        req = make_request()
        # Clearly best car: new, low miles, right price
        best = make_car(price=27000, year=2024, mileage=5000, source="CarMax", title_status="Clean", condition="Like New")
        # Clearly worst car: old, high miles, over budget
        worst = make_car(price=35000, year=2015, mileage=90000, source="Autotrader", title_status="Salvage", condition="Poor")
        mid = make_car(price=25000, year=2020, mileage=40000)

        result = score_cars([worst, mid, best], req)
        composites = [r.scores.composite for r in result]
        assert composites == sorted(composites, reverse=True)
        assert result[0].listing.year == 2024

    def test_composite_is_correct_weighted_average(self):
        from scoring import WEIGHTS
        car = make_car(price=27000, year=2022, mileage=30000, source="CarMax", title_status="Clean", condition="Clean")
        req = make_request()
        result = score_cars([car], req)[0]
        s = result.scores
        expected = round(
            s.price_value * WEIGHTS["price_value"]
            + s.year_depreciation * WEIGHTS["year_depreciation"]
            + s.mileage * WEIGHTS["mileage"]
            + s.condition * WEIGHTS["condition"]
            + s.feature_match * WEIGHTS["feature_match"]
            + s.source_trust * WEIGHTS["source_trust"],
            1,
        )
        assert result.scores.composite == expected

    def test_empty_list_returns_empty(self):
        assert score_cars([], make_request()) == []

    def test_all_scores_between_0_and_100(self):
        cars = [
            make_car(price=27000, year=2022, mileage=30000),
            make_car(price=50000, year=2010, mileage=200000, title_status="Salvage"),
        ]
        req = make_request()
        for scored in score_cars(cars, req):
            s = scored.scores
            for val in [s.price_value, s.year_depreciation, s.mileage, s.condition, s.feature_match, s.source_trust, s.composite]:
                assert 0 <= val <= 100, f"Score out of range: {val}"
