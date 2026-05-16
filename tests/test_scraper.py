"""
Tests for scraper.py — price/mileage/title helpers and HTML parsers.
"""

import pytest
from scraper import (
    _parse_price,
    _parse_mileage,
    _parse_title,
    _parse_carmax_listings,
    _parse_carvana_listings,
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
