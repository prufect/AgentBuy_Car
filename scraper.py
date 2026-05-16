"""
AutoBrief Scraper — Bright Data Web Unlocker for CarMax & Carvana.

Scrapes car listings from both sites, parses HTML with BeautifulSoup,
and returns normalized CarListing objects.

Strategy:
  1. Try structured JSON extraction first (most reliable for SPAs)
  2. Fall back to DOM parsing with aggressive selectors
  3. Text-based regex extraction as last resort
"""

import json
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
    base = "https://www.carmax.com/cars/all"
    params = []
    body_map = {
        "suv": "SUV", "sedan": "Sedan", "truck": "Truck",
        "coupe": "Coupe", "hatchback": "Hatchback", "van": "Van",
        "wagon": "Wagon", "convertible": "Convertible",
    }
    body = body_map.get(car_type.lower(), car_type)
    params.append(f"body={quote_plus(body)}")
    params.append(f"price={budget_min}-{budget_max}")
    if year_min:
        params.append(f"year={year_min}-{year_max or 2026}")
    if mileage_max:
        params.append(f"mileage=0-{mileage_max}")
    return f"{base}?{'&'.join(params)}"


def _carvana_search_url(car_type: str, budget_min: int, budget_max: int,
                        year_min: Optional[int] = None, year_max: Optional[int] = None,
                        mileage_max: Optional[int] = None) -> str:
    base = "https://www.carvana.com/cars"
    body_map = {
        "suv": "suv", "sedan": "sedan", "truck": "truck",
        "coupe": "coupe", "hatchback": "hatchback", "van": "van",
        "wagon": "wagon", "convertible": "convertible",
    }
    body = body_map.get(car_type.lower(), car_type.lower())
    path = f"{base}/{body}"
    params = [f"priceMin={budget_min}", f"priceMax={budget_max}"]
    if year_min:
        params.append(f"yearMin={year_min}")
    if year_max:
        params.append(f"yearMax={year_max}")
    if mileage_max:
        params.append(f"milesMax={mileage_max}")
    return f"{path}?{'&'.join(params)}"


# ---------------------------------------------------------------------------
# Structured data extraction (JSON in script tags)
# ---------------------------------------------------------------------------

def _extract_json_vehicles(html: str) -> list[dict]:
    """
    Extract vehicle data from embedded JSON in the page.

    Site-specific strategies:
      - CarMax:  `const cars = [...]` JavaScript variable
      - Carvana: Escaped JSON in <script> with `\"vehicles\":[{...}]`
      - Generic: __NEXT_DATA__, ld+json, vehicle array patterns
    """
    vehicles = []

    # ── 1. CarMax: const cars = [{...}, ...] ──────────────────────────
    carmax_match = re.search(
        r'const\s+cars\s*=\s*(\[.*?\])\s*;',
        html, re.DOTALL
    )
    if carmax_match:
        try:
            cars = json.loads(carmax_match.group(1))
            for car in cars[:50]:
                vehicles.append(_normalize_carmax_json(car))
            logger.info("CarMax const cars: extracted %d vehicles", len(cars))
            if vehicles:
                return vehicles  # CarMax data is very complete, no need to continue
        except (json.JSONDecodeError, KeyError) as exc:
            logger.debug("Failed to parse CarMax const cars: %s", exc)

    # ── 2. Carvana: escaped \"vehicles\":[{...}] in script tag ──────
    carvana_vehicles = _extract_carvana_script_vehicles(html)
    if carvana_vehicles:
        vehicles.extend(carvana_vehicles)
        logger.info("Carvana script: extracted %d vehicles", len(carvana_vehicles))
        if vehicles:
            return vehicles

    # ── 3. __NEXT_DATA__ (Next.js SPAs) ───────────────────────────────
    next_data_match = re.search(
        r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    if next_data_match:
        try:
            data = json.loads(next_data_match.group(1))
            found = _find_vehicles_in_json(data)
            vehicles.extend(found)
            if found:
                logger.info("__NEXT_DATA__: extracted %d vehicles", len(found))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.debug("Failed to parse __NEXT_DATA__: %s", exc)

    # ── 4. application/ld+json ────────────────────────────────────────
    ld_json_matches = re.findall(
        r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    for match in ld_json_matches:
        try:
            data = json.loads(match)
            if isinstance(data, dict):
                if data.get("@type") in ("Car", "Vehicle", "Product"):
                    vehicles.append(_normalize_ld_json_vehicle(data))
                if "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") in ("Car", "Vehicle", "Product", "ListItem"):
                            vehicles.append(_normalize_ld_json_vehicle(item))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        vehicles.append(_normalize_ld_json_vehicle(item))
        except (json.JSONDecodeError, KeyError):
            continue

    logger.info("Extracted %d vehicles from JSON (all strategies)", len(vehicles))
    return vehicles


def _extract_carvana_script_vehicles(html: str) -> list[dict]:
    """Extract vehicles from Carvana's escaped JSON in script tags."""
    vehicles = []

    # Carvana embeds: \"vehicles\":[{...}]
    # The JSON keys are escaped with backslash-quotes inside a script tag
    idx = html.find('\\"vehicles\\":[')
    if idx < 0:
        # Try unescaped version
        idx = html.find('"vehicles":[')
    if idx < 0:
        return []

    # Find the start of the array
    array_start = html.find('[', idx)
    if array_start < 0:
        return []

    # Use bracket counting to find the matching end
    depth = 0
    array_end = array_start
    for i in range(array_start, min(array_start + 500000, len(html))):
        if html[i] == '[':
            depth += 1
        elif html[i] == ']':
            depth -= 1
            if depth == 0:
                array_end = i + 1
                break

    raw = html[array_start:array_end]

    # Unescape the Carvana-style escaped JSON
    # \"vehicles\" → "vehicles"
    cleaned = raw.replace('\\"', '"')

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            for item in data[:50]:
                if isinstance(item, dict):
                    vehicles.append(_normalize_carvana_json(item))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.debug("Failed to parse Carvana script vehicles: %s", exc)
        # Try with the raw (maybe already unescaped)
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for item in data[:50]:
                    if isinstance(item, dict):
                        vehicles.append(_normalize_carvana_json(item))
        except (json.JSONDecodeError, KeyError):
            pass

    return vehicles


def _normalize_carmax_json(data: dict) -> dict:
    """Normalize a CarMax const cars vehicle object."""
    year = data.get("year")
    make = data.get("make")
    model = data.get("model")
    trim = data.get("trim")
    title_parts = [str(x) for x in [year, make, model, trim] if x]
    title = " ".join(title_parts) if title_parts else "Unknown Vehicle"

    price = data.get("basePrice") or data.get("originalPrice") or 0
    if isinstance(price, str):
        price = _parse_price(price)

    mileage = data.get("mileage")
    if isinstance(mileage, str):
        mileage = _parse_mileage(mileage)

    url = f"https://www.carmax.com/car/{data.get('stockNumber', '')}"

    image_url = data.get("heroImageUrl") or data.get("heroThumbnailImageUrl") or None

    features = data.get("features") or data.get("highlightedFeatures", "")
    if isinstance(features, str):
        features = [f.strip() for f in features.split(",") if f.strip()]

    highlights = data.get("highlights") or []

    condition = "Clean"
    if data.get("isNewArrival"):
        condition = "Like New"
    prior_use = data.get("priorUseDescriptions", [])
    if prior_use and "rental" in str(prior_use).lower():
        condition = "Rental"

    return {
        "title": title,
        "price": int(price) if price else 0,
        "year": int(year) if year else None,
        "mileage": int(mileage) if mileage else None,
        "condition": condition,
        "features": features[:15],
        "url": url,
        "image_url": image_url,
        "make": make,
        "model": model,
        "trim": trim,
        "exterior_color": data.get("exteriorColor"),
        "interior_color": data.get("interiorColor"),
        "transmission": data.get("transmission"),
        "drive_train": data.get("driveTrain"),
        "mpg_city": data.get("mpgCity"),
        "mpg_highway": data.get("mpgHighway"),
    }


def _normalize_carvana_json(data: dict) -> dict:
    """Normalize a Carvana vehicle object from embedded script JSON."""
    make = data.get("make")
    model = data.get("model") or data.get("parentModel")
    trim = data.get("trim")
    year = data.get("year")
    title_parts = [str(x) for x in [year, make, model, trim] if x]
    title = " ".join(title_parts) if title_parts else "Unknown Vehicle"

    # Carvana price is nested: {"total": 24590, ...}
    price_data = data.get("price", {})
    if isinstance(price_data, dict):
        price = price_data.get("total") or price_data.get("kbbValue") or 0
    elif isinstance(price_data, (int, float)):
        price = price_data
    else:
        price = 0

    mileage = data.get("mileage")
    if isinstance(mileage, str):
        mileage = _parse_mileage(mileage)

    vehicle_id = data.get("vehicleId") or data.get("stockNumber", "")
    url = f"https://www.carvana.com/vehicle/{vehicle_id}?refSource=srp" if vehicle_id else ""

    # Image — prefer hero/textless URLs over relative imageUrl paths
    image_url = None
    # textlessUrl and heroImageUrl are absolute URLs
    for img_key in ["textlessUrl", "heroImageUrl", "heroThumbnailImageUrl"]:
        candidate = data.get(img_key)
        if candidate and isinstance(candidate, str) and candidate.startswith("http"):
            image_url = candidate
            break
    # Fall back to imageUrl (may be relative path like /2004424783/post-large/...)
    if not image_url:
        img_path = data.get("imageUrl")
        if img_path and isinstance(img_path, str):
            image_url = f"https://cdn.carvana.io{img_path}" if img_path.startswith("/") else img_path
    # Fall back to jellyBeanDesktopUrl (stock image, always absolute)
    if not image_url:
        image_url = data.get("jellyBeanDesktopUrl") or data.get("jellyBeanMobileUrl")
    # Fall back to images array
    images = data.get("images") or []
    if not image_url and images and isinstance(images, list):
        if isinstance(images[0], str):
            image_url = images[0]
        elif isinstance(images[0], dict):
            image_url = images[0].get("url") or images[0].get("heroImageUrl")

    features = data.get("features") or data.get("options") or []
    if isinstance(features, str):
        features = [f.strip() for f in features.split(",") if f.strip()]

    condition = "Clean"
    if data.get("isCertified"):
        condition = "Certified"

    return {
        "title": title,
        "price": int(price) if price else 0,
        "year": int(year) if year else None,
        "mileage": int(mileage) if mileage else None,
        "condition": condition,
        "features": features[:15],
        "url": url,
        "image_url": image_url,
        "make": make,
        "model": model,
        "trim": trim,
        "exterior_color": data.get("color"),
        "interior_color": data.get("interiorColor"),
        "transmission": data.get("transmission"),
        "drive_train": data.get("driveTrain"),
        "fuel_type": data.get("fuelType"),
        "mpg": data.get("milesPerGallon"),
    }


def _find_vehicles_in_json(data, depth=0) -> list[dict]:
    """Recursively search JSON structure for vehicle arrays."""
    if depth > 8:
        return []

    vehicles = []

    if isinstance(data, dict):
        # Check if this looks like a vehicle object
        if any(k in data for k in ("vehicleId", "stockNumber", "vin", "year", "make", "model")):
            if any(k in data for k in ("price", "msrp", "askingPrice")):
                vehicles.append(_normalize_json_vehicle(data))
                return vehicles

        # Check known container keys
        for key in ("vehicles", "inventory", "cars", "listings", "results", "items", "data"):
            if key in data and isinstance(data[key], list):
                for item in data[key][:50]:
                    if isinstance(item, dict):
                        vehicles.append(_normalize_json_vehicle(item))
                if vehicles:
                    return vehicles

        # Recurse into values
        for val in data.values():
            if isinstance(val, (dict, list)):
                vehicles.extend(_find_vehicles_in_json(val, depth + 1))
                if len(vehicles) >= 50:
                    break

    elif isinstance(data, list):
        for item in data[:50]:
            if isinstance(item, dict):
                vehicles.extend(_find_vehicles_in_json(item, depth + 1))
                if len(vehicles) >= 50:
                    break

    return vehicles


def _normalize_json_vehicle(data: dict) -> dict:
    """Normalize a JSON vehicle object into a standard dict."""
    # Title construction
    year = data.get("year") or data.get("Year") or data.get("modelYear")
    make = data.get("make") or data.get("Make") or data.get("makeName")
    model = data.get("model") or data.get("Model") or data.get("modelName")
    trim = data.get("trim") or data.get("Trim") or data.get("trimName") or data.get("trimDescription")

    title = data.get("title") or data.get("name") or data.get("headline") or data.get("displayName")
    if not title and year and make and model:
        parts = [str(year), make, model]
        if trim:
            parts.append(trim)
        title = " ".join(parts)

    # Price
    price = data.get("price") or data.get("Price") or data.get("askingPrice") or \
            data.get("msrp") or data.get("salePrice") or data.get("listPrice") or \
            data.get("internetPrice") or data.get("retailPrice")
    if isinstance(price, dict):
        price = price.get("amount") or price.get("value") or price.get("total")
    if isinstance(price, str):
        price = _parse_price(price)

    # Mileage
    mileage = data.get("mileage") or data.get("Mileage") or data.get("odometer") or \
              data.get("miles") or data.get("mileageNumber")
    if isinstance(mileage, str):
        mileage = _parse_mileage(mileage)

    # URL
    url = data.get("url") or data.get("vehicleUrl") or data.get("link") or data.get("href") or ""
    if url and not url.startswith("http"):
        url = f"https://www.carvana.com{url}" if "/vehicle/" in url else f"https://www.carmax.com{url}"

    # Image
    image_url = data.get("imageUrl") or data.get("image") or data.get("thumbnail") or \
                data.get("photoUrl") or data.get("primaryPhotoUrl") or data.get("img")
    if isinstance(image_url, dict):
        image_url = image_url.get("url") or image_url.get("src")
    if isinstance(image_url, list) and image_url:
        image_url = image_url[0] if isinstance(image_url[0], str) else image_url[0].get("url", "")

    # Features
    features = data.get("features") or data.get("options") or data.get("highlights") or \
               data.get("equipment") or data.get("accessories") or []
    if isinstance(features, str):
        features = [features]
    elif isinstance(features, list):
        features = [str(f) if not isinstance(f, str) else f for f in features[:15]]

    # Condition
    condition = data.get("condition") or data.get("Condition") or "Clean"
    if isinstance(condition, dict):
        condition = condition.get("description") or condition.get("label") or "Clean"

    return {
        "title": title or "Unknown Vehicle",
        "price": int(price) if price else 0,
        "year": int(year) if year else None,
        "mileage": int(mileage) if mileage else None,
        "condition": str(condition),
        "features": features,
        "url": url,
        "image_url": image_url,
        "make": make,
        "model": model,
        "trim": trim,
    }


def _normalize_ld_json_vehicle(data: dict) -> dict:
    """Normalize an ld+json vehicle entry."""
    title = data.get("name") or data.get("item", {}).get("name") or ""
    url = data.get("url") or data.get("item", {}).get("url") or ""
    image_url = data.get("image") or data.get("item", {}).get("image") or ""
    if isinstance(image_url, list) and image_url:
        image_url = image_url[0]

    # Try to get offer/price
    offers = data.get("offers", {})
    if isinstance(offers, list) and offers:
        offers = offers[0]
    price = 0
    if isinstance(offers, dict):
        price = offers.get("price") or offers.get("lowPrice") or 0

    return {
        "title": title,
        "price": int(price) if price else 0,
        "year": None,
        "mileage": None,
        "condition": "Clean",
        "features": [],
        "url": url,
        "image_url": image_url if isinstance(image_url, str) else "",
        "make": None,
        "model": None,
        "trim": None,
    }


# ---------------------------------------------------------------------------
# DOM parsers (fallback when JSON extraction fails)
# ---------------------------------------------------------------------------

def _parse_carmax_listings(html: str) -> list[CarListing]:
    """Parse CarMax search results page into CarListing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Try structured data first
    json_vehicles = _extract_json_vehicles(html)
    if json_vehicles:
        logger.info("CarMax: using %d vehicles from JSON data", len(json_vehicles))
        for v in json_vehicles[:50]:
            try:
                year, make, model, trim = _parse_title(v.get("title", ""))
                # Prefer JSON-extracted fields, fall back to title-parsed
                listings.append(CarListing(
                    title=v.get("title") or "Unknown Vehicle",
                    price=v.get("price", 0),
                    year=v.get("year") or year,
                    mileage=v.get("mileage"),
                    condition=v.get("condition", "Clean"),
                    features=v.get("features", []),
                    url=v.get("url") or "https://www.carmax.com",
                    image_url=v.get("image_url"),
                    source="CarMax",
                    make=v.get("make") or make,
                    model=v.get("model") or model,
                    trim=v.get("trim") or trim,
                    title_status="Clean",
                ))
            except Exception as exc:
                logger.warning("Failed to create CarMax listing from JSON: %s", exc)
        if listings:
            return listings

    # DOM fallback — try many selector strategies
    card_selectors = [
        "[data-testid='search-results'] .car-card",
        ".car-tile",
        "[class*='vehicle-card']",
        "[class*='VehicleCard']",
        "article[class*='car']",
        "[class*='result-card']",
        "[class*='listing']",
    ]
    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            logger.info("CarMax DOM: matched selector '%s' -> %d cards", sel, len(cards))
            break

    if not cards:
        cards = soup.select("a[href*='/car/']")
        if cards:
            logger.info("CarMax DOM: fallback to link selector -> %d cards", len(cards))

    for card in cards:
        try:
            title = _extract_text(card, [
                "[data-testid='car-title']", ".car-title", "h2", "h3",
                "[class*='title']", "[class*='Title']", "[class*='heading']",
                "[class*='Heading']", "a",
            ])

            price = _extract_price_from_element(card)
            mileage = _extract_mileage_from_element(card)

            # Link
            href = ""
            if card.name == "a" and card.get("href"):
                href = card["href"]
            else:
                link = card.select_one("a[href]")
                href = link["href"] if link else ""
            url = f"https://www.carmax.com{href}" if href.startswith("/") else (href or "https://www.carmax.com")

            # Image
            img_el = card.select_one("img")
            image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

            # Features
            feature_els = card.select("[class*='feature'], [class*='highlight'], [class*='badge'], li")
            features = [el.get_text(strip=True) for el in feature_els if el.get_text(strip=True) and len(el.get_text(strip=True)) < 60]

            year, make, model, trim = _parse_title(title)

            listings.append(CarListing(
                title=title, price=price, year=year, mileage=mileage,
                condition="Clean", features=features[:15], url=url,
                image_url=image_url, source="CarMax",
                make=make, model=model, trim=trim, title_status="Clean",
            ))
        except Exception as exc:
            logger.warning("Failed to parse CarMax card: %s", exc)

    logger.info("CarMax: parsed %d listings total", len(listings))
    return listings


def _parse_carvana_listings(html: str) -> list[CarListing]:
    """Parse Carvana search results page into CarListing objects."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Try structured data first
    json_vehicles = _extract_json_vehicles(html)
    if json_vehicles:
        logger.info("Carvana: using %d vehicles from JSON data", len(json_vehicles))
        for v in json_vehicles[:50]:
            try:
                year, make, model, trim = _parse_title(v.get("title", ""))
                listings.append(CarListing(
                    title=v.get("title") or "Unknown Vehicle",
                    price=v.get("price", 0),
                    year=v.get("year") or year,
                    mileage=v.get("mileage"),
                    condition=v.get("condition", "Clean"),
                    features=v.get("features", []),
                    url=v.get("url") or "https://www.carvana.com",
                    image_url=v.get("image_url"),
                    source="Carvana",
                    make=v.get("make") or make,
                    model=v.get("model") or model,
                    trim=v.get("trim") or trim,
                    title_status="Clean",
                ))
            except Exception as exc:
                logger.warning("Failed to create Carvana listing from JSON: %s", exc)
        if listings:
            return listings

    # DOM fallback
    card_selectors = [
        "[data-qa='search-results'] .result-tile",
        ".vehicle-card",
        "[class*='result-item']",
        "[class*='resultItem']",
        "[class*='VehicleCard']",
        "[class*='vehicle-card']",
        "[class*='inventory']",
        "[class*='listing']",
    ]
    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            logger.info("Carvana DOM: matched selector '%s' -> %d cards", sel, len(cards))
            break

    if not cards:
        cards = soup.select("a[href*='/vehicle/']")
        if cards:
            logger.info("Carvana DOM: fallback to link selector -> %d cards", len(cards))

    for card in cards:
        try:
            title = _extract_text(card, [
                "[data-qa='heading']", ".vehicle-name", "h2", "h3",
                "[class*='title']", "[class*='Title']", "[class*='heading']",
                "[class*='Heading']", "a",
            ])

            price = _extract_price_from_element(card)
            mileage = _extract_mileage_from_element(card)

            # Link
            href = ""
            if card.name == "a" and card.get("href"):
                href = card["href"]
            else:
                link = card.select_one("a[href]")
                href = link["href"] if link else ""
            url = f"https://www.carvana.com{href}" if href.startswith("/") else (href or "https://www.carvana.com")

            # Image
            img_el = card.select_one("img")
            image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

            # Features
            feature_els = card.select("[class*='feature'], [class*='highlight'], li")
            features = [el.get_text(strip=True) for el in feature_els if el.get_text(strip=True) and len(el.get_text(strip=True)) < 60]

            year, make, model, trim = _parse_title(title)

            listings.append(CarListing(
                title=title, price=price, year=year, mileage=mileage,
                condition="Clean", features=features[:15], url=url,
                image_url=image_url, source="Carvana",
                make=make, model=model, trim=trim, title_status="Clean",
            ))
        except Exception as exc:
            logger.warning("Failed to parse Carvana card: %s", exc)

    # Ultimate fallback: regex extraction from raw text
    if not listings:
        listings = _regex_extract_vehicles(html, "Carvana")

    logger.info("Carvana: parsed %d listings total", len(listings))
    return listings


# ---------------------------------------------------------------------------
# Aggressive text-based extraction helpers
# ---------------------------------------------------------------------------

def _extract_text(parent, selectors: list[str]) -> str:
    """Try multiple selectors to extract text from a parent element."""
    for sel in selectors:
        el = parent.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text and len(text) > 2:
                return text
    # Last resort: get all text, try to find a vehicle-like string
    all_text = parent.get_text(" ", strip=True)
    # Look for year + make pattern
    match = re.search(r'(20\d{2}\s+[A-Z][a-zA-Z]+\s+\w+)', all_text)
    if match:
        return match.group(1)
    return "Unknown Vehicle"


def _extract_price_from_element(parent) -> int:
    """Aggressively extract price from any element."""
    # Try specific selectors first
    for sel in ["[class*='price']", "[class*='Price']", "[data-qa='price']",
                "[class*='cost']", "[class*='amount']"]:
        el = parent.select_one(sel)
        if el:
            price = _parse_price(el.get_text(strip=True))
            if price > 0:
                return price

    # Regex search in all text
    text = parent.get_text(" ", strip=True)
    # Look for dollar amounts
    price_matches = re.findall(r'\$\s*([\d,]+)', text)
    if price_matches:
        # Return the first reasonable price (between 500 and 500000)
        for p in price_matches:
            val = int(p.replace(",", ""))
            if 500 <= val <= 500000:
                return val
    return 0


def _extract_mileage_from_element(parent) -> Optional[int]:
    """Aggressively extract mileage from any element."""
    for sel in ["[class*='mileage']", "[class*='Mileage']", "[class*='miles']",
                "[data-qa='mileage']", "[class*='odometer']"]:
        el = parent.select_one(sel)
        if el:
            mileage = _parse_mileage(el.get_text(strip=True))
            if mileage:
                return mileage

    # Regex search in all text
    text = parent.get_text(" ", strip=True)
    mile_match = re.search(r'([\d,]+)\s*(?:miles?|mi\.?)\b', text, re.IGNORECASE)
    if mile_match:
        return int(mile_match.group(1).replace(",", ""))

    # Look for numbers that could be mileage (1000-300000)
    numbers = re.findall(r'\b(\d{1,3}(?:,\d{3})+|\d{4,6})\b', text)
    for n in numbers:
        val = int(n.replace(",", ""))
        if 1000 <= val <= 300000:
            return val
    return None


def _regex_extract_vehicles(html: str, source: str) -> list[CarListing]:
    """Last resort: extract vehicle data using regex from raw HTML text."""
    listings = []
    soup = BeautifulSoup(html, "lxml")

    # Remove script/style
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")

    # Find patterns like "2022 Toyota RAV4 $28,990"
    vehicle_pattern = re.compile(
        r'(20\d{2})\s+([A-Z][a-zA-Z]+)\s+(\w+(?:\s+\w+)?)\s+.*?\$\s*([\d,]+)',
        re.MULTILINE
    )
    for match in vehicle_pattern.finditer(text[:200000]):
        year = int(match.group(1))
        make = match.group(2)
        model = match.group(3).strip()
        price = int(match.group(4).replace(",", ""))

        if price < 500 or price > 500000:
            continue

        title = f"{year} {make} {model}"
        listings.append(CarListing(
            title=title, price=price, year=year, mileage=None,
            condition="Clean", features=[], url="",
            image_url=None, source=source,
            make=make, model=model, trim=None, title_status="Clean",
        ))
        if len(listings) >= 50:
            break

    logger.info("Regex extraction found %d vehicles from %s", len(listings), source)
    return listings


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_price(text: str) -> int:
    if not text:
        return 0
    numbers = re.findall(r'\d+', text.replace(',', ''))
    return int(numbers[0]) if numbers else 0


def _parse_mileage(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    numbers = re.findall(r'\d+', text.replace(',', ''))
    return int(numbers[0]) if numbers else None


def _parse_title(title: str) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    year = None
    make = None
    model = None
    trim = None

    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', title)
    if year_match:
        year = int(year_match.group(1))

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

    if remaining:
        parts = remaining.split()
        if len(parts) >= 1 and make:
            model = parts[0]
        if len(parts) >= 2:
            trim = " ".join(parts[1:])

    return year, make, model, trim


# ---------------------------------------------------------------------------
# Debug endpoint helper
# ---------------------------------------------------------------------------

def get_scrape_debug_info(html: str, source: str) -> dict:
    """Return debug info about what was found in the HTML."""
    if not html:
        return {"source": source, "html_length": 0, "findings": "No HTML returned"}

    soup = BeautifulSoup(html, "lxml")
    findings = {
        "source": source,
        "html_length": len(html),
        "has_next_data": bool(re.search(r'__NEXT_DATA__', html)),
        "has_ld_json": bool(re.search(r'application/ld\+json', html)),
        "link_car": len(soup.select("a[href*='/car/']")),
        "link_vehicle": len(soup.select("a[href*='/vehicle/']")),
        "h2_count": len(soup.find_all("h2")),
        "h3_count": len(soup.find_all("h3")),
        "dollar_signs": len(re.findall(r'\$\s*[\d,]+', html[:100000])),
        "year_patterns": len(re.findall(r'\b20\d{2}\s+[A-Z][a-z]', html[:100000])),
        "title_tag": soup.title.string if soup.title else None,
    }
    return findings


# ---------------------------------------------------------------------------
# Public scraper functions
# ---------------------------------------------------------------------------

async def scrape_carmax(
    car_type: str, budget_min: int, budget_max: int, api_key: str,
    year_min: Optional[int] = None, year_max: Optional[int] = None,
    mileage_max: Optional[int] = None,
) -> list[CarListing]:
    url = _carmax_search_url(car_type, budget_min, budget_max, year_min, year_max, mileage_max)
    logger.info("Scraping CarMax: %s", url)

    html = await _fetch_via_brightdata(url, api_key)
    if not html:
        logger.warning("CarMax scrape returned no HTML")
        return []

    # Log debug info
    debug = get_scrape_debug_info(html, "CarMax")
    logger.info("CarMax debug: %s", json.dumps(debug, default=str))

    return _parse_carmax_listings(html)


async def scrape_carvana(
    car_type: str, budget_min: int, budget_max: int, api_key: str,
    year_min: Optional[int] = None, year_max: Optional[int] = None,
    mileage_max: Optional[int] = None,
) -> list[CarListing]:
    url = _carvana_search_url(car_type, budget_min, budget_max, year_min, year_max, mileage_max)
    logger.info("Scraping Carvana: %s", url)

    html = await _fetch_via_brightdata(url, api_key)
    if not html:
        logger.warning("Carvana scrape returned no HTML")
        return []

    # Log debug info
    debug = get_scrape_debug_info(html, "Carvana")
    logger.info("Carvana debug: %s", json.dumps(debug, default=str))

    return _parse_carvana_listings(html)
