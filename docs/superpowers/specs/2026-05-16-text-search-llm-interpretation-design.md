# Text Search LLM Interpretation Design

## Goal

Replace the structured search form as the primary input with a natural-language search brief. The system should use the existing LLM integration to convert that brief into the existing structured `SearchRequest` shape, and it should ask the user clarifying questions only when required search fields cannot be confidently inferred.

## Current State

The frontend currently collects `car_type`, `budget_min`, `budget_max`, optional year and mileage limits, optional condition, and selected must-have features through discrete controls in `static/app.js`. It submits that structured payload to `POST /search`, which validates budget values, starts an async job, scrapes CarMax and Carvana, scores listings, and optionally uses the LLM to summarize top results.

The backend already has provider fallback logic in `agent.py` through `_call_llm`, `_call_qwen`, and `_call_tokenrouter`. That LLM path is only used after search results exist, so there is no current way to interpret a user brief before scraping.

## User Experience

The search panel should present a text area where the user describes what they want in ordinary language, for example:

> I need a reliable family SUV under $35k, 2019 or newer, low mileage, with CarPlay and blind spot monitoring.

When the user submits the brief, the frontend calls a new interpretation endpoint. If the backend can infer the required fields, the frontend starts the existing `/search` job with the structured request. If required fields are missing or ambiguous, the frontend shows only the necessary questions, collects short answers, appends those answers to the original brief, and interprets again. The app should not ask optional preference questions before searching.

The required fields remain:

- `car_type`
- `budget_min`
- `budget_max`

Optional fields may be inferred when present:

- `year_min`
- `year_max`
- `mileage_max`
- `must_have_features`
- `condition`

## Backend Design

Add request and response models for interpretation in `models.py`:

- `SearchInterpretRequest`: includes `query: str`.
- `SearchClarifyingQuestion`: includes `id`, `question`, and `field`.
- `SearchInterpretResponse`: includes `status`, optional `search_params`, a list of `questions`, optional `summary`, and optional `source`.

Add a new `POST /search/interpret` endpoint in `main.py`. It accepts `SearchInterpretRequest`, delegates to an LLM interpretation helper, and returns either:

- `status: "ready"` with a valid `SearchRequest`, or
- `status: "needs_clarification"` with required-field questions.

Add interpretation helpers in `agent.py`:

- Build a strict prompt that asks the LLM to return JSON only.
- Parse JSON defensively, including extracting JSON from extra text if a provider adds it.
- Validate the proposed params with the existing `SearchRequest` model.
- Generate deterministic fallback questions when required fields are missing.
- Provide lightweight local extraction as a fallback if no LLM API key is configured or if parsing fails.

The local fallback should recognize common body styles, budget phrases such as `under $35k` or `$15k-$30k`, year phrases such as `2019 or newer`, mileage phrases such as `under 60k miles`, known feature names from the current frontend set, and known condition labels. It should still ask questions when required fields are missing.

## Frontend Design

Update `static/app.js` so `SearchPanel` uses a text area as the primary search input instead of the discrete form grid and feature chips. Quick presets can remain, but applying a preset should populate natural-language text rather than internal structured fields.

On submit:

1. Validate that the text brief is not empty.
2. Call `POST /search/interpret`.
3. If the response is `needs_clarification`, render the returned questions as compact text inputs and wait for the user to answer.
4. Re-run interpretation using the original brief plus the answered questions.
5. If the response is `ready`, submit `search_params` to the existing `/search` endpoint and keep the current polling/results flow.

The demo path should use the same interpretation flow, then call `/search/test` with the interpreted `SearchRequest`.

## Error Handling

If interpretation fails unexpectedly, the UI should show a clear error and avoid starting a scrape. If the LLM returns invalid or incomplete data, the backend should fall back to local extraction and required-field questions rather than returning a provider error to the user.

Budget validation remains in `/search`, and `/search/interpret` should also reject empty briefs.

## Testing

Add focused backend tests for the interpretation helper:

- A complete natural-language brief returns `ready` with expected structured fields.
- A brief missing budget returns `needs_clarification` with a budget question.
- A brief missing body style returns `needs_clarification` with a body-style question.
- Local fallback understands compact money units such as `$35k`.

Add route-level tests for `/search/interpret` to verify successful JSON shape and empty-query validation. Frontend behavior can be verified manually in the browser after the backend tests pass.

## Scope

This change does not alter scraping, scoring, result cards, polling, or the existing `/search` contract. It changes how the user creates the structured request before search begins.
