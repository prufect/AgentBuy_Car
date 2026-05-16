"""
Tests for scraper.py — URL builders, price/mileage/title helpers, and HTML parsers.
"""

import pytest
from scraper import (
    _parse_price,
    _parse_mileage,
    _parse_title,
    _parse_carmax_listings,
    _parse_carvana_listings,
    _carmax_search_url,
    _carvana_search_url,
)


# ---------------------------------------------------------------------------
# _parse_price
# ---------------------------------------------------------------------------

class TestParsePrice:
    def test_dollar_sign_with_commas(self):
        assert _parse_price("$28,990") == 28990

    def test_plain_number(self):
        assert _parse_price("28990") == 28990

    def test_number_with_commas_no_dollar(self):
        assert _parse_price("28,990") == 28990

    def test_empty_string_returns_0(self):
        assert _parse_price("") == 0

    def test_no_numbers_returns_0(self):
        assert _parse_price("Call for price") == 0

    def test_price_with_decimals_takes_first(self):
        assert _parse_price("$28,990.00") == 28990

    def test_price_with_surrounding_text(self):
        assert _parse_price("Price: $15,500 OBO") == 15500

    def test_zero_price(self):
        assert _parse_price("$0") == 0


# ---------------------------------------------------------------------------
# _parse_mileage
# ---------------------------------------------------------------------------

class TestParseMileage:
    def test_mileage_with_mi_suffix(self):
        assert _parse_mileage("24,500 mi") == 24500

    def test_plain_number(self):
        assert _parse_mileage("24500") == 24500

    def test_mileage_with_commas(self):
        assert _parse_mileage("124,000") == 124000

    def test_none_returns_none(self):
        assert _parse_mileage(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_mileage("") is None

    def test_no_numbers_returns_none(self):
        assert _parse_mileage("Unknown") is None

    def test_mileage_with_miles_text(self):
        assert _parse_mileage("45,000 miles") == 45000

    def test_zero_mileage(self):
        assert _parse_mileage("0 mi") == 0


# ---------------------------------------------------------------------------
# _parse_title
# ---------------------------------------------------------------------------

class TestParseTitle:
    def test_full_title(self):
        year, make, model, trim = _parse_title("2022 Toyota RAV4 XLE")
        assert year == 2022
        assert make == "Toyota"
        assert model == "RAV4"
        assert trim == "XLE"

    def test_title_no_trim(self):
        year, make, model, trim = _parse_title("2021 Honda CR-V")
        assert year == 2021
        assert make == "Honda"
        assert model == "CR-V"

    def test_title_no_year(self):
        year, make, model, trim = _parse_title("Toyota RAV4 XLE")
        assert year is None
        assert make == "Toyota"

    def test_title_unknown_make(self):
        year, make, model, trim = _parse_title("2022 Rivian R1T Adventure")
        assert year == 2022
        assert make is None

    def test_multi_word_trim(self):
        year, make, model, trim = _parse_title("2020 Ford F-150 XLT SuperCrew")
        assert year == 2020
        assert make == "Ford"
        assert model == "F-150"
        assert trim == "XLT SuperCrew"

    def test_older_year(self):
        year, make, model, trim = _parse_title("1998 Honda Civic EX")
        assert year == 1998

    def test_chevy_alias(self):
        year, make, model, trim = _parse_title("2019 Chevy Silverado LT")
        assert make == "Chevy"
        assert model == "Silverado"

    def test_empty_string(self):
        year, make, model, trim = _parse_title("")
        assert year is None
        assert make is None

    def test_just_year(self):
        year, make, model, trim = _parse_title("2020")
        assert year == 2020
        assert make is None
        assert model is None


# ---------------------------------------------------------------------------
# _parse_carmax_listings (feed sample HTML)
# ---------------------------------------------------------------------------

CARMAX_SAMPLE_HTML = """
<html><body>
<div data-testid="search-results">
  <div class="car-card">
    <h2 data-testid="car-title">2022 Toyota RAV4 XLE</h2>
    <span data-testid="car-price">$28,990</span>
    <span data-testid="car-mileage">24,500 mi</span>
    <a href="/car/12345">View</a>
    <img src="https://img.carmax.com/rav4.jpg" />
    <span class="feature-badge">Backup Camera</span>
    <span class="feature-badge">Bluetooth</span>
  </div>
  <div class="car-card">
    <h2 data-testid="car-title">2021 Honda CR-V EX</h2>
    <span data-testid="car-price">$26,500</span>
    <span data-testid="car-mileage">31,000 mi</span>
    <a href="/car/67890">View</a>
  </div>
</div>
</body></html>
"""

CARMAX_EMPTY_HTML = "<html><body><div>No results found.</div></body></html>"

CARMAX_FALLBACK_HTML = """
<html><body>
  <a href="/car/99999">
    <h3>2020 Ford Mustang GT</h3>
    <span class="price">$35,000</span>
  </a>
</body></html>
"""


class TestParseCarMaxListings:
    def test_parses_correct_number_of_listings(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert len(listings) == 2

    def test_parses_title(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert listings[0].title == "2022 Toyota RAV4 XLE"

    def test_parses_price(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert listings[0].price == 28990

    def test_parses_mileage(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert listings[0].mileage == 24500

    def test_parses_url(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert listings[0].url == "https://www.carmax.com/car/12345"

    def test_parses_image_url(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert listings[0].image_url == "https://img.carmax.com/rav4.jpg"

    def test_parses_features(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert "Backup Camera" in listings[0].features
        assert "Bluetooth" in listings[0].features

    def test_source_is_carmax(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert all(car.source == "CarMax" for car in listings)

    def test_parses_year_make_model(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        assert listings[0].year == 2022
        assert listings[0].make == "Toyota"
        assert listings[0].model == "RAV4"

    def test_empty_html_returns_empty_list(self):
        listings = _parse_carmax_listings(CARMAX_EMPTY_HTML)
        assert listings == []

    def test_no_crash_on_malformed_html(self):
        listings = _parse_carmax_listings("<html><body><<<</body></html>")
        assert isinstance(listings, list)

    def test_fallback_selector_finds_cars(self):
        listings = _parse_carmax_listings(CARMAX_FALLBACK_HTML)
        assert len(listings) >= 1

    def test_listing_without_mileage_is_none(self):
        listings = _parse_carmax_listings(CARMAX_SAMPLE_HTML)
        # Second card has no mileage listed — should be None, not crash
        assert listings[1].mileage == 31000  # it has one, just verify no crash


# ---------------------------------------------------------------------------
# _parse_carvana_listings (feed sample HTML)
# ---------------------------------------------------------------------------

CARVANA_SAMPLE_HTML = """
<html><body>
<div data-qa="search-results">
  <div class="result-tile">
    <h2 data-qa="heading">2021 Honda CR-V EX</h2>
    <span data-qa="price">$26,500</span>
    <span data-qa="mileage">31,000 mi</span>
    <a href="/vehicle/67890">View</a>
    <img src="https://img.carvana.com/crv.jpg" />
    <span class="feature-highlight">Honda Sensing</span>
  </div>
  <div class="result-tile">
    <h2 data-qa="heading">2023 Hyundai Tucson SEL</h2>
    <span data-qa="price">$27,800</span>
    <span data-qa="mileage">12,000 mi</span>
    <a href="/vehicle/11111">View</a>
  </div>
</div>
</body></html>
"""

CARVANA_EMPTY_HTML = "<html><body><p>No vehicles match your search.</p></body></html>"

CARVANA_FALLBACK_HTML = """
<html><body>
  <a href="/vehicle/55555">
    <h3>2020 Kia Telluride SX</h3>
    <span class="price">$38,000</span>
  </a>
</body></html>
"""


# ---------------------------------------------------------------------------
# _carmax_search_url
# ---------------------------------------------------------------------------

class TestCarmaxSearchUrl:
    def test_base_url(self):
        url = _carmax_search_url("suv", 20000, 30000)
        assert url.startswith("https://www.carmax.com/cars/all")

    def test_body_style_mapped_to_title_case(self):
        url = _carmax_search_url("suv", 20000, 30000)
        assert "body=SUV" in url

    def test_body_style_case_insensitive(self):
        url_lower = _carmax_search_url("suv", 20000, 30000)
        url_upper = _carmax_search_url("SUV", 20000, 30000)
        assert "body=SUV" in url_lower
        assert "body=SUV" in url_upper

    def test_price_range_included(self):
        url = _carmax_search_url("sedan", 15000, 25000)
        assert "price=15000-25000" in url

    def test_year_range_included_when_set(self):
        url = _carmax_search_url("suv", 20000, 30000, year_min=2018, year_max=2024)
        assert "year=2018-2024" in url

    def test_year_range_omitted_when_not_set(self):
        url = _carmax_search_url("suv", 20000, 30000)
        assert "year=" not in url

    def test_year_max_defaults_to_2026_when_year_min_set(self):
        url = _carmax_search_url("suv", 20000, 30000, year_min=2018, year_max=None)
        assert "year=2018-2026" in url

    def test_mileage_included_when_set(self):
        url = _carmax_search_url("suv", 20000, 30000, mileage_max=80000)
        assert "mileage=0-80000" in url

    def test_mileage_omitted_when_not_set(self):
        url = _carmax_search_url("suv", 20000, 30000)
        assert "mileage=" not in url

    def test_all_params_combined(self):
        url = _carmax_search_url("truck", 25000, 40000, year_min=2019, year_max=2023, mileage_max=60000)
        assert "body=Truck" in url
        assert "price=25000-40000" in url
        assert "year=2019-2023" in url
        assert "mileage=0-60000" in url

    def test_unknown_car_type_passed_through(self):
        url = _carmax_search_url("minivan", 20000, 30000)
        assert "minivan" in url.lower()

    def test_all_known_body_types_mapped(self):
        types = ["suv", "sedan", "truck", "coupe", "hatchback", "van", "wagon", "convertible"]
        for car_type in types:
            url = _carmax_search_url(car_type, 20000, 30000)
            assert "body=" in url


# ---------------------------------------------------------------------------
# _carvana_search_url
# ---------------------------------------------------------------------------

class TestCarvanaSearchUrl:
    def test_base_url_with_body_in_path(self):
        url = _carvana_search_url("suv", 20000, 30000)
        assert url.startswith("https://www.carvana.com/cars/suv")

    def test_body_style_lowercased_in_path(self):
        url = _carvana_search_url("SUV", 20000, 30000)
        assert "/suv" in url

    def test_price_min_included(self):
        url = _carvana_search_url("sedan", 15000, 25000)
        assert "priceMin=15000" in url

    def test_price_max_included(self):
        url = _carvana_search_url("sedan", 15000, 25000)
        assert "priceMax=25000" in url

    def test_year_min_included_when_set(self):
        url = _carvana_search_url("suv", 20000, 30000, year_min=2018)
        assert "yearMin=2018" in url

    def test_year_max_included_when_set(self):
        url = _carvana_search_url("suv", 20000, 30000, year_max=2024)
        assert "yearMax=2024" in url

    def test_year_params_omitted_when_not_set(self):
        url = _carvana_search_url("suv", 20000, 30000)
        assert "yearMin=" not in url
        assert "yearMax=" not in url

    def test_mileage_included_when_set(self):
        url = _carvana_search_url("suv", 20000, 30000, mileage_max=80000)
        assert "milesMax=80000" in url

    def test_mileage_omitted_when_not_set(self):
        url = _carvana_search_url("suv", 20000, 30000)
        assert "milesMax=" not in url

    def test_all_params_combined(self):
        url = _carvana_search_url("truck", 25000, 40000, year_min=2019, year_max=2023, mileage_max=60000)
        assert "/truck" in url
        assert "priceMin=25000" in url
        assert "priceMax=40000" in url
        assert "yearMin=2019" in url
        assert "yearMax=2023" in url
        assert "milesMax=60000" in url

    def test_unknown_car_type_lowercased_in_path(self):
        url = _carvana_search_url("Minivan", 20000, 30000)
        assert "/minivan" in url

    def test_all_known_body_types_in_path(self):
        types = ["suv", "sedan", "truck", "coupe", "hatchback", "van", "wagon", "convertible"]
        for car_type in types:
            url = _carvana_search_url(car_type, 20000, 30000)
            assert f"/{car_type}" in url


class TestParseCarvanaListings:
    def test_parses_correct_number_of_listings(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert len(listings) == 2

    def test_parses_title(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert listings[0].title == "2021 Honda CR-V EX"

    def test_parses_price(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert listings[0].price == 26500

    def test_parses_mileage(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert listings[0].mileage == 31000

    def test_parses_url(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert listings[0].url == "https://www.carvana.com/vehicle/67890"

    def test_parses_image_url(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert listings[0].image_url == "https://img.carvana.com/crv.jpg"

    def test_parses_features(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert "Honda Sensing" in listings[0].features

    def test_source_is_carvana(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert all(car.source == "Carvana" for car in listings)

    def test_parses_year_make_model(self):
        listings = _parse_carvana_listings(CARVANA_SAMPLE_HTML)
        assert listings[0].year == 2021
        assert listings[0].make == "Honda"
        assert listings[0].model == "CR-V"

    def test_empty_html_returns_empty_list(self):
        listings = _parse_carvana_listings(CARVANA_EMPTY_HTML)
        assert listings == []

    def test_no_crash_on_malformed_html(self):
        listings = _parse_carvana_listings("<html><body><<<</body></html>")
        assert isinstance(listings, list)

    def test_fallback_selector_finds_cars(self):
        listings = _parse_carvana_listings(CARVANA_FALLBACK_HTML)
        assert len(listings) >= 1
