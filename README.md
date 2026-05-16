# AutoBrief — AI-Powered Car Buying Advisor

AutoBrief scrapes live listings from CarMax and Carvana, scores every car across six weighted factors, and generates AI-written summaries explaining why each car fits your budget and preferences.

## How it works

1. You describe the car you want in plain English
2. The LLM structures the brief into search parameters, asking only for missing required details
3. The backend scrapes CarMax and Carvana in parallel via Bright Data Web Unlocker
4. Every listing is scored 0–100 across six factors (price value, year, mileage, condition, features, source trust)
5. The top 5 results are sent to an LLM that writes a 2-sentence value proposition for each car
6. Results are returned ranked by composite score with a full score breakdown per car

## Tech stack

- **Backend:** Python 3.12, FastAPI, Uvicorn
- **Scraping:** BeautifulSoup + Bright Data Web Unlocker (anti-bot bypass)
- **AI summaries:** AgentField API (primary), TokenRouter (fallback)
- **Frontend:** Vanilla JS, HTML5, CSS3 (dark theme, no framework)
- **Data validation:** Pydantic v2

## Project structure

```
AutoBrief/
├── main.py          # FastAPI server, endpoints, job orchestration
├── agent.py         # Pipeline runner: scrape → score → LLM summarize
├── scraper.py       # CarMax & Carvana HTML parsers
├── scoring.py       # Weighted multi-factor scoring engine
├── models.py        # Pydantic data models (shared contract)
├── requirements.txt
├── Dockerfile
├── .env.example
└── static/
    ├── index.html
    ├── app.js
    └── style.css
```

## Setup

**1. Clone and install dependencies**

```bash
pip install -r requirements.txt
```

**2. Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys:

```
BRIGHTDATA_API_KEY=your_key_here
AGENTFIELD_API_KEY=your_key_here
TOKENROUTER_API_KEY=your_key_here   # optional fallback
LLM_MODEL=qwen-plus
```

**3. Run the server**

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## Docker

```bash
docker build -t autobrief .
docker run -p 8000:8000 --env-file .env autobrief
```

## Scoring weights

| Factor | Weight | Logic |
|---|---|---|
| Price Value | 25% | Sweet spot at 70% of budget range; penalizes over-budget |
| Year | 20% | Linear interpolation between year_min and year_max |
| Mileage | 20% | Inverse ratio to mileage_max; heavy penalty if exceeded |
| Condition | 15% | Title status + condition label + accident history |
| Feature Match | 10% | Ratio of must-have features found in the listing |
| Source Trust | 10% | CarMax: 95, Carvana: 90, unknown: 70 |

## API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/search/interpret` | POST | Convert a natural-language brief into search params or required questions |
| `/search` | POST | Start a search job; returns `job_id` |
| `/search/{job_id}` | GET | Poll job status and results |
| `/search/test` | POST | Mock endpoint with hardcoded results (dev mode) |
| `/health` | GET | Health check |

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `BRIGHTDATA_API_KEY` | Yes | Web Unlocker API key for scraping |
| `AGENTFIELD_API_KEY` | Yes | Primary LLM API key |
| `AGENTFIELD_URL` | No | Override AgentField endpoint |
| `TOKENROUTER_API_KEY` | No | Fallback LLM API key |
| `TOKENROUTER_URL` | No | Override TokenRouter endpoint |
| `LLM_MODEL` | No | Model name (default: `qwen-plus`) |
