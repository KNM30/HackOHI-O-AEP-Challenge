# Outage Concierge (HackOHI/O 2026, AEP challenge)

This is a customer-facing prototype. A customer selects an anonymized premise and sees how it is supplied, along with
its outage risk, restoration range, preparation guidance and alert previews. Every result separates **confirmed facts**,
**scenario assumptions**, **model estimates** and **recommended actions**.

> This prototype is built on anonymized, historical challenge data. It is not an official AEP service and does not show
> live outage information.

## Status

| Milestone | State |
|---|---|
| M1: data inspection, CIR18 subset, premise selector, map and network context | **done** |
| M2: risk band + confidence, damage-to-premise impact scenarios, step-restoration possibilities | **done** |
| M3: repair jobs from the labor workbook (×4.5 once), crew scheduler, restoration ranges, fixed scenarios | **done** |
| M4: preparation guidance, alert rules and simulated messages, grounded AI assistant with fallback | **done** |
| M5: real AI integration verified, answer validation reviewed, journey layout for judging | **done** |

Cards that are not built yet say **"Not calculated yet"**. They never show placeholder numbers.

## Layout

```
challenge_repo/        organiser repo (git clone, never modified; archives extracted inside data/extracted/)
pipeline/              reproducible data steps (extract -> inspect -> build subset)
data/processed/        generated subset consumed by the backend (allowlisted fields only)
backend/app/           FastAPI service: network logic, response schemas (= field allowlist)
backend/tests/         pytest: upstream dependencies, missing data, matching cap, API privacy
frontend/              React + Vite + TypeScript + Leaflet
docs/                  data_inspection_report.md, assumptions.md
```

## Windows setup (PowerShell)

Prerequisites: Python 3.12+ (tested with 3.14), Node 20+ (tested with 24), and Git.

```powershell
# 0. From the project root, get the challenge data (about 33 MB of archives)
git clone https://github.com/hackohio/aep_challenge_hack26 challenge_repo

# 1. Python environment
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt

# 2. Data pipeline (about 1 minute each)
.\.venv\Scripts\python pipeline\extract.py         # unzip without overwriting; shapefile companions stay together
.\.venv\Scripts\python pipeline\inspect_data.py    # -> docs\data_inspection_report.md
.\.venv\Scripts\python pipeline\build_subset.py    # -> data\processed\ (default: circuits 0000018 and 0000109)
.\.venv\Scripts\python pipeline\build_labor.py     # -> data\processed\labor_reference.json (workbook extract)

# 3. Backend (terminal 1)
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 4. Frontend (terminal 2)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173/?premise=PRM-00770FFC> to load the demo premise. You can also use **Load demo premise**.

Deep links for repeatable demos (the scenario runs once with its default locations):

- `?premise=PRM-00340340&severity=severe&scenario=neighbouring_branch`
- `?premise=PRM-00770FFC&scenario=local_branch`
- `?premise=PRM-00770FFC&scenario=historical_replay&crews=3`
- `?premise=PRM-0D322A0F&scenario=historical_replay&crews=1` (Circuit 109: ambulance and fire station affected; their
  repairs already come first, and the card says so)
- `?premise=PRM-0D322A0F&scenario=critical_facility&crews=1` (Circuit 109 operator view: a small repair feeding the fire
  station against a larger branch. Add `&priority=off` and the fire station comes back about 1.5 h later)

Risk bands differ between premises at the same severity. With `severity=moderate`, `PRM-00340340` is **moderate**
(score 42) and `PRM-00770FFC` is **high** (61). At `severity=severe` every Circuit 18 premise is high, because all of
them share 3.5 km of overhead line that only the substation breaker protects (see [docs/risk_model.md](docs/risk_model.md)).

Optional: `crews`, `crew_size`, `access_delay`, `access_scope=all`, `priority=off` (critical-facility priority),
`restring=off` (drop the team's assumed time for replacing wire and show workbook-only lower bounds).

Line repairs include one labelled **team assumption**: 0.3 - 0.8 direct hours per phase per 100 ft to pull in
replacement wire, because AEP's labor workbook has no entry for it. Every estimate that uses it says so and also
shows the workbook-only figure. See [docs/assumptions.md](docs/assumptions.md#conductor-re-stringing-team-assumption-not-aep-data).

The processed data includes two circuits: 18 (main demo) and 109 (the only well-mapped circuit near a fire and an
ambulance station). The historical replay uses each circuit's own largest storm event.

Tests:

```powershell
cd backend; ..\.venv\Scripts\python -m pytest -q      # pipeline, network, risk, scenarios, API privacy
cd frontend; npm test                                  # scenario state: reset and stale-response guard
```

Notes:
- If you prefer an activated venv and PowerShell blocks `Activate.ps1`, run
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. Calling `.venv\Scripts\python` directly, as above, avoids this.
- To build more circuits, run `python pipeline\build_subset.py --circuits 0000018 0000072`. The app then shows a
  circuit picker.
- The Vite dev server proxies `/api` to `http://127.0.0.1:8000`. To use a different backend address, set
  `VITE_API_TARGET`.

## Optional AI assistant

The assistant works without any AI provider. It then gives deterministic "standard answers" built from the same
calculations. To enable AI explanations, start the backend with these environment variables:

```powershell
cd backend
$env:AI_PROVIDER = "anthropic"
$env:ANTHROPIC_API_KEY = "<your key>"     # or another credential source the Anthropic SDK supports
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

You can instead copy `backend/.env.example` to `backend/.env`, which is git-ignored, and run
`..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000 --env-file .env`.

- Defaults, all overridable:
  - `AI_MODEL=claude-haiku-5-5` (the economical current model; short explanations do not need a larger one)
  - `AI_EFFORT=low`, `AI_MAX_TOKENS=2000`
  - `AI_TIMEOUT_S=15` and `AI_MAX_RETRIES=1`, so the worst case is about 30 s before the standard answer is shown
- The call uses the stable Messages API with JSON-schema output. There is no server-side model fallback, so the
  answering model is always the one configured. A refusal is shown as a standard answer.
- Keys stay on the server and are never logged or returned. The frontend never sees them.
- Each answer shows its status: AI explanation, or a standard answer because AI is not configured, the provider
  failed, or the AI wording failed the check against the calculations. Technical details are under "Developer
  details".
- Verified on 2026-10-24 against the official model, structured-output and refusal docs, with live calls (see
  [docs/alerts_and_guidance.md](docs/alerts_and_guidance.md#5-grounded-assistant-assistantpy)).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | build status |
| `GET /api/circuits` | processed circuits |
| `GET /api/circuits/{id}/premises` | anonymized premise list |
| `GET /api/circuits/{id}/map` | primary lines, service transformers, protective devices (allowlisted) |
| `GET /api/premises/{id}` | confirmed network context, historical damage relations, data quality, pending prediction cards |
| `GET /api/premises/{id}/risk?severity=minor\|moderate\|severe` | pre-storm risk band, heuristic score, factors, separate confidence ([docs/risk_model.md](docs/risk_model.md)) |
| `GET /api/premises/{id}/scenarios` | available what-if damage scenarios and candidate locations |
| `POST /api/premises/{id}/scenario` `{scenario_id, location_ids?}` | simulated impact: interrupted / waits for repair / possible earlier restoration / unresolved (stateless) |
| `POST /api/circuits/{id}/simulation` `{premise_id, scenario_id, scenario_label, location_ids, crew}` | fixed scenario: impact + repair jobs, crew schedule, restoration range ([docs/restoration_model.md](docs/restoration_model.md)) |
| `POST /api/briefing` `{premise_id, severity, simulation?, preferences, alerts, events, last_notified?}` | guidance, alert eligibility, message previews ([docs/alerts_and_guidance.md](docs/alerts_and_guidance.md)) |
| `POST /api/assistant` `{briefing, question, previous?}` | grounded answer (AI when configured, otherwise a labelled standard answer) |

Interactive docs are at <http://127.0.0.1:8000/docs>.

## Privacy

- Premise IDs are salted hashes. Source premise numbers, road names, city, house-number annotations, SCADA IDs and raw
  location numbers never reach the browser. `backend/app/schemas.py` is the allowlist, and a test checks responses for
  leaks.
- The life-support flag in the customer layer (`critical_c`) is never used. Medical and accessibility needs will come
  only from what the user declares.
- The map overview shows service transformers rather than homes. Historical damage points are rounded to about 100 m.

See [docs/data_inspection_report.md](docs/data_inspection_report.md) and [docs/assumptions.md](docs/assumptions.md).
