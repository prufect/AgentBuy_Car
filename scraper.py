"""
AutoBrief Scraper — Bright Data Web Unlocker for CarMax & Carvana.

Scrapes car listings from both sites, parses HTML with BeautifulSoup,
and returns normalized CarListing objects.
"""

import re
import logging
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from models import CarListing

logger = logging.getLogger(__name__)

BRIGHTDATA_API_URL = "https://api.brightdata.com/request"


# ---------------------------------------------------------------------------
# Bright Data Web Unlocker
# ---------------------------------------------------------------------------

async def _fetch_via_brightdata(url: str, api_key: str) -> Optional[str]:
    """Send a URL through Bright Data Web Unlocker and return raw HTML."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                BRIGHTDATA_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "zone": "web_unlocker1",
                    "url": url,
                    "format": "raw",
                },
            )
            if resp.status_code == 200:
                return resp.text
            logger.warning("Bright Data %s for %s: %s", resp.status_code, url, resp.text[:200])
            return None
        except httpx.TimeoutException:
            logger.error("Timeout scraping %s", url)
            return None
        except Exception as exc:
            logger.error("Error scraping %s: %s", url, exc)
            return None


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------

def _carmax_search_url(car_type: str, budget_min: int, budget_max: int,
                       year_min: Optional[int] = None, year_max: Optional[int] = None,
                       mileage_max: Optional[int] = None) -> str:
    """Build a CarMax search URL from user parameters."""
    # CarMax search URL format
    base = "https://www.carmax.com/cars/all"

    params = []
    # Body style mapping
    body_map = {
        "suv": "SUV", "sedan": "Sedan", "truck": "Truck",
        "coupe": "Coupe", "hatchback": "Hatchback", "van": "Van",
        "wagon": "Wagon", "convertible": "Convertible",
    }
    body = body_map.get(car_type.lower(), car_type)
    params.append(f"body={quote_plus(body)}")

    # Price range
    params.append(f"price={budget_min}-{budget_max}")

    # Year range
    if year_min:
        params.append(f"year={year_min}-{year_max or 2026}")

    # Mileage
    if mileage_max:
        params.append(f"mileage=0-{mileage_max}")

    return f"{base}?{'&'.join(params)}"


def _carvana_search_url(car_type: str, budget_min: int, budget_max: int,
                        year_min: Optional[int] = None, year_max: Optional[int] = None,
                        mileage_max: Optional[int] = None) -> str:
    """Build a Carvana search URL from user parameters."""
    base = "https://www.carvana.com/cars"

    # Carvana uses path segments for some filters
    body_map = {
        "suv": "suv", "sedan": "sedan", "truck": "truck",
        "coupe": "coupe", "hatchback": "hatchback", "van": "van",
        "wagon": "wagon", "convertible": "convertible",
    }
    body = body_map.get(car_type.lower(), car_type.lower())
    path = f"{base}/{body}"

    params = []
    params.append(f"priceMin={budget_min}")
    params.append(f"priceMax={budget_max}")

    if year_min:
        params.append(f"yearMin={year_min}")
    if year_max:
        params.append(f"yearMax={year_max}")
    if mileage_max:
        params.append(f"milesMax={mileage_max}")

    return f"{path}?{'&'.join(params)}"


# ---------------------------------------------------------------------------
# HTML parsers
# ---------------------------------------------------------------------------

def _parse_carmax_listings(html: str) -> list[CarListing]:
    """Parse CarMax search results page into CarListing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    # CarMax uses various class patterns; try multiple selectors
    cards = (
        soup.select("[data-testid='search-results'] .car-card")
        or soup.select(".car-tile")
        or soup.select("[class*='vehicle-card']")
        or soup.select("article[class*='car']")
    )

    if not cards:
        # Fallback: look for any elements with car-like data
        cards = soup.select("a[href*='/car/']")

    for card in cards:
        try:
            # Extract title / year / make / model
            title_el = (
                card.select_one("[data-testid='car-title']")
                or card.select_one(".car-title")
                or card.select_one("h2")
                or card.select_one("h3")
                or card.select_one("[class*='title']")
            )
            title = title_el.get_text(strip=True) if title_el else "Unknown Vehicle"

            # Extract price
            price_el = (
                card.select_one("[data-testid='car-price']")
                or card.select_one(".car-price")
                or card.select_one("[class*='price']")
            )
            price = _parse_price(price_el.get_text(strip=True) if price_el else "0")

            # Extract mileage
            mileage_el = (
                card.select_one("[data-testid='car-mileage']")
                or card.select_one(".car-mileage")
                or card.select_one("[class*='mileage']")
            )
            mileage = _parse_mileage(mileage_el.get_text(strip=True) if mileage_el else None)

            # Extract link
            link_el = card.select_one("a[href]") if card.name != "a" else card
            href = link_el.get("href", "") if link_el else ""
            url = f"https://www.carmax.com{href}" if href.startswith("/") else (href or "https://www.carmax.com")

            # Extract image
            img_el = card.select_one("img")
            image_url = img_el.get("src", "") if img_el else None

            # Extract features/highlights
            feature_els = card.select("[class*='feature'], [class*='highlight'], [class*='badge']")
            features = [el.get_text(strip=True) for el in feature_els if el.get_text(strip=True)]

            # Parse year and make/model from title
            year, make, model, trim = _parse_title(title)

            listings.append(CarListing(
                title=title,
                price=price,
                year=year,
                mileage=mileage,
                condition="Clean",
                features=features,
                url=url,
                image_url=image_url,
                source="CarMax",
                make=make,
                model=model,
                trim=trim,
                title_status="Clean",
            ))
        except Exception as exc:
            logger.warning("Failed to parse CarMax card: %s", exc)
            continue

    logger.info("Parsed %d CarMax listings", len(listings))
    return listings


def _parse_carvana_listings(html: str) -> list[CarListing]:
    """Parse Carvana search results page into CarListing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Carvana uses different selectors
    cards = (
        soup.select("[data-qa='search-results'] .result-tile")
        or soup.select(".vehicle-card")
        or soup.select("[class*='result-item']")
        or soup.select("div[class*='inventory']")
    )

    if not cards:
        # Fallback: look for elements with car-like links
        cards = soup.select("a[href*='/vehicle/']")

    for card in cards:
        try:
            # Extract title
            title_el = (
                card.select_one("[data-qa='heading']")
                or card.select_one(".vehicle-name")
                or card.select_one("h2")
                or card.select_one("h3")
                or card.select_one("[class*='title']")
            )
            title = title_el.get_text(strip=True) if title_el else "Unknown Vehicle"

            # Extract price
            price_el = (
                card.select_one("[data-qa='price']")
                or card.select_one(".vehicle-price")
                or card.select_one("[class*='price']")
            )
            price = _parse_price(price_el.get_text(strip=True) if price_el else "0")

            # Extract mileage
            mileage_el = (
                card.select_one("[data-qa='mileage']")
                or card.select_one(".vehicle-mileage")
                or card.select_one("[class*='mileage']")
            )
            mileage = _parse_mileage(mileage_el.get_text(strip=True) if mileage_el else None)

            # Extract link
            link_el = card.select_one("a[href]") if card.name != "a" else card
            href = link_el.get("href", "") if link_el else ""
            url = f"https://www.carvana.com{href}" if href.startswith("/") else (href or "https://www.carvana.com")

            # Extract image
            img_el = card.select_one("img")
            image_url = img_el.get("src", "") if img_el else None

            # Features
            feature_els = card.select("[class*='feature'], [class*='highlight']")
            features = [el.get_text(strip=True) for el in feature_els if el.get_text(strip=True)]

            year, make, model, trim = _parse_title(title)

            listings.append(CarListing(
                title=title,
                price=price,
                year=year,
                mileage=mileage,
                condition="Clean",
                features=features,
                url=url,
                image_url=image_url,
                source="Carvana",
                make=make,
                model=model,
                trim=trim,
                title_status="Clean",
            ))
        except Exception as exc:
            logger.warning("Failed to parse Carvana card: %s", exc)
            continue

    logger.info("Parsed %d Carvana listings", len(listings))
    return listings


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_price(text: str) -> int:
    """Extract integer price from text like '$28,990' or '28990'."""
    if not text:
        return 0
    numbers = re.findall(r'\d+', text.replace(',', ''))
    return int(numbers[0]) if numbers else 0


def _parse_mileage(text: Optional[str]) -> Optional[int]:
    """Extract integer mileage from text like '24,500 mi' or '24500'."""
    if not text:
        return None
    numbers = re.findall(r'\d+', text.replace(',', ''))
    return int(numbers[0]) if numbers else None


def _parse_title(title: str) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    """
    Parse a title like '2022 Toyota RAV4 XLE' into (year, make, model, trim).
    """
    year = None
    make = None
    model = None
    trim = None

    # Extract year
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', title)
    if year_match:
        year = int(year_match.group(1))

    # Common makes for matching
    common_makes = [
        "Toyota", "Honda", "Ford", "Chevrolet", "Chevy", "Hyundai", "Kia",
        "Nissan", "Volkswagen", "VW", "Subaru", "Mazda", "BMW", "Mercedes",
        "Mercedes-Benz", "Audi", "Lexus", "Acura", "Infiniti", "Buick",
        "Cadillac", "Chrysler", "Dodge", "GMC", "Jeep", "Lincoln", "Ram",
        "Tesla", "Volvo", "Porsche", "MINI", "Mitsubishi", "Suzuki",
    ]

    remaining = title
    if year_match:
        remaining = title[year_match.end():].strip()

    for m in common_makes:
        if remaining.lower().startswith(m.lower()):
            make = m
            remaining = remaining[len(m):].strip()
            break

    # Remaining is model + trim
    if remaining:
        parts = remaining.split()
        if len(parts) >= 1 and make:
            model = parts[0]
        if len(parts) >= 2:
            trim = " ".join(parts[1:])

    return year, make, model, trim


# ---------------------------------------------------------------------------
# Public scraper functions
# ---------------------------------------------------------------------------

async def scrape_carmax(
    car_type: str,
    budget_min: int,
    budget_max: int,
    api_key: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    mileage_max: Optional[int] = None,
) -> list[CarListing]:
    """Scrape CarMax for car listings matching the given criteria."""
    url = _carmax_search_url(car_type, budget_min, budget_max, year_min, year_max, mileage_max)
    logger.info("Scraping CarMax: %s", url)

    html = await _fetch_via_brightdata(url, api_key)
    if not html:
        logger.warning("CarMax scrape returned no HTML")
        return []

    return _parse_carmax_listings(html)


async def scrape_carvana(
    car_type: str,
    budget_min: int,
    budget_max: int,
    api_key: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    mileage_max: Optional[int] = None,
) -> list[CarListing]:
    """Scrape Carvana for car listings matching the given criteria."""
    url = _carvana_search_url(car_type, budget_min, budget_max, year_min, year_max, mileage_max)
    logger.info("Scraping Carvana: %s", url)

    html = await _fetch_via_brightdata(url, api_key)
    if not html:
        logger.warning("Carvana scrape returned no HTML")
        return []

    return _parse_carvana_listings(html)
