# Coffee Quality DaaS — CSE540 Data as a Service project

A REST API that serves the CQI Arabica coffee quality dataset (1,310 samples, 36 countries)
as a service. Clients query it over HTTPS; they never touch the database directly.

```
coffee-daas/
├── data/arabica_data_cleaned.csv   raw dataset (CQI, via github.com/jldbc/coffee-quality-database)
├── load_data.py                    cleans CSV -> builds coffee.db (SQLite)
├── coffee.db                       generated database
├── main.py                         FastAPI service (the DaaS API)
├── client_test.py                  concurrent multi-client tester
├── requirements.txt
├── render.yaml                     one-click Render deployment config
└── Dockerfile                      optional container deployment
```

---

## Step 0 — Prerequisites (Mac, no VM needed)

```bash
python3 --version        # need 3.11+. If missing:  brew install python
git --version            # if missing:  xcode-select --install
```
Also create free accounts on **GitHub** and **Render** (render.com → sign up with GitHub).

## Step 1 — Set up the project

```bash
cd ~/Desktop/coffee-daas          # wherever you unzipped it
python3 -m venv .venv
source .venv/bin/activate         # prompt now shows (.venv)
pip install -r requirements.txt
```

## Step 2 — Create the database (brief item 3a)

```bash
python load_data.py
```
Expected output:
```
Raw dataset: 1311 rows x 44 columns
Created coffee.db: 1310 rows, 17 columns, 36 countries
```
📸 **Screenshot 1:** this terminal output.

What the loader does: keeps 17 of 44 columns, drops 1 row with a score of 0, averages
low/high altitude into `altitude_m` and nulls impossible values (<100 m or >3,500 m, e.g.
a 190,164 m typo), converts messy harvest years ("2013/2014", "March 2010") to a single
year, and adds indexes on `country`, `processing_method` and `total_cup_points`.

## Step 3 — Run the API locally (3b, 3c)

```bash
uvicorn main:app --reload
```
Open **http://127.0.0.1:8000/docs** — the Swagger UI lists every endpoint.
Click an endpoint → **Try it out** → **Execute**.

📸 **Screenshot 2:** the Swagger UI endpoint list.
📸 **Screenshot 3:** one executed `/search` request with its JSON response.

Quick checks in a second terminal:
```bash
curl "http://127.0.0.1:8000/health"
curl "http://127.0.0.1:8000/coffees/5"
curl "http://127.0.0.1:8000/search?country=ethiopia&process=natural&min_score=85&limit=2"
curl "http://127.0.0.1:8000/stats/by-country"
curl -o kenya.csv "http://127.0.0.1:8000/export?country=Kenya"
```

### API reference

| Method | Endpoint | Parameters | Purpose |
|---|---|---|---|
| GET | `/` | – | Service info |
| GET | `/health` | – | Status, record count, uptime, requests served |
| GET | `/coffees` | `limit` (1–100), `offset`, `sort_by`, `order` | Paginated list of all samples |
| GET | `/coffees/{id}` | path `id` | One sample; 404 if absent |
| GET | `/search` | `country`, `variety`, `process`, `min_score`, `max_score`, `min_altitude`, `max_altitude`, `year`, `limit`, `offset` | Combined filtering (partial, case-insensitive text match) |
| GET | `/countries` | – | Distinct countries with sample counts |
| GET | `/top` | `n`, `country` | Highest-scoring samples |
| GET | `/stats/by-country` | `min_samples` | Avg/best score and avg altitude per country |
| GET | `/stats/by-process` | – | Avg score, acidity, body per processing method |
| GET | `/export` | `country`, `process`, `min_score` | Filtered data as a CSV download |

Design details worth mentioning in the report:
- Every response carries an `X-Process-Time-ms` header (server-side processing time).
- `sort_by` is checked against a whitelist and all filters use `?` placeholders, so the
  API is safe from SQL injection.
- The DB is opened **read-only** per request, so concurrent clients can't corrupt it.
- Optional API-key auth: set env var `API_KEY`; clients then must send `X-API-Key`
  (401 otherwise).

## Step 4 — Test with multiple clients locally (3e)

Keep the server running; in another terminal:
```bash
python client_test.py --clients 20 --requests 200
```
📸 **Screenshot 4:** the output. (Reference run on a cloud Linux box: 200/200 OK,
~410 req/s, p50 46 ms, p95 62 ms — yours will differ.)

## Step 5 — Push to GitHub

1. github.com → **New repository** → name `coffee-daas` → Public → Create.
2. In the project folder:
```bash
git init
git add .
git commit -m "Coffee DaaS: dataset, loader, API, tests"
git branch -M main
git remote add origin https://github.com/<your-username>/coffee-daas.git
git push -u origin main
```
(If git asks for a password, use a GitHub Personal Access Token, or install the
GitHub CLI: `brew install gh && gh auth login`.)

## Step 6 — Deploy on Render (3d)

1. render.com → **New +** → **Blueprint** → select the `coffee-daas` repo.
   Render reads `render.yaml` and fills in everything:
   - Build: `pip install -r requirements.txt && python load_data.py`
   - Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Health check: `/health`
2. Click **Apply**. Wait ~2–4 minutes for “Your service is live”.
   *(Alternative: New + → Web Service → pick the repo → enter the build/start commands above, Instance type: Free.)*
3. Your URL looks like `https://coffee-daas-xxxx.onrender.com`. Open `/docs` on it.

📸 **Screenshot 5:** Render build/deploy logs showing the loader output and “live”.
📸 **Screenshot 6:** Swagger UI on the public URL.

Optional API key: Render dashboard → service → **Environment** → add `API_KEY` = any
secret → Save (auto-redeploys). In Swagger, use the header field; with curl add
`-H "X-API-Key: <secret>"`.

## Step 7 — Verify the deployed service from multiple clients (3e)

Use at least three different client types:
```bash
# 1. Concurrent Python clients
python client_test.py https://coffee-daas-xxxx.onrender.com --clients 20 --requests 200

# 2. curl from the terminal
curl -i "https://coffee-daas-xxxx.onrender.com/top?n=3&country=Kenya"

# 3. Browser — open on your phone (mobile data, not Wi-Fi, to prove it's public):
#    https://coffee-daas-xxxx.onrender.com/stats/by-process
```
📸 **Screenshots 7–9:** the test output, the curl output with headers, the phone browser.
📸 **Screenshot 10:** `/health` after the tests (shows `requests_served` increased).

To measure cold start: leave the service idle for 15+ minutes, then run `client_test.py`
again — the warm-up line shows the cold-start time separately.

---

## Report outline (brief item 4)

**a. Architecture**
```
 Clients                         Render (cloud, free web service)
 ┌──────────────────┐   HTTPS    ┌─────────────────────────────────────────┐
 │ Browser/Swagger  │──────────▶ │ Uvicorn (ASGI server)                   │
 │ curl             │  GET+JSON  │   └─ FastAPI app (main.py)              │
 │ Python clients ×N│◀────────── │        validation · auth · timing       │
 └──────────────────┘            │        └─ SQLite coffee.db (read-only)  │
                                 └─────────────────────────────────────────┘
          GitHub repo ──(auto-deploy on push: build runs load_data.py)──▶ Render
```
Three tiers: data layer (SQLite), service layer (FastAPI REST API), client layer.
DaaS property: data is centrally managed and delivered on demand through a standard
interface (HTTP + JSON/CSV); consumers need no DB access, drivers or schema knowledge.

**b. Dataset** — Coffee Quality Institute Arabica reviews (scraped by J. LeDoux, 2018;
github.com/jldbc/coffee-quality-database). Raw: 1,311 × 44. After cleaning: 1,310 × 17,
36 countries. Include the table schema from `load_data.py` and the cleaning list from Step 2.

**c. Service/API** — the API reference table above + 2–3 sample request/response pairs.

**d. Screenshots** — 1–10 above.

**e. Observations** (fill in with your measured numbers):
- Local vs cloud latency (local p50 vs Render p50 — the difference is network RTT
  from your location to Render's region).
- Cold start: Render's free tier spins down after 15 min without traffic and takes about
  a minute to wake (render.com/docs/free); compare your warm-up vs warm requests.
- Concurrency: success rate and p95 at 20 vs 50 clients (`--clients 50 --requests 500`).
- Free-tier filesystem is ephemeral — fine here because the DB is read-only and rebuilt at
  each build; a writable DaaS would need managed Postgres instead.
- SQLite vs Postgres: SQLite is ideal for small read-heavy data; it serializes writes,
  so write-heavy or multi-instance services need a client-server DB.
- Security: read-only DB, parameterized SQL, whitelisted sort, optional API key.
  Missing: rate limiting, per-user keys, key rotation.
- CI/CD: every `git push` auto-redeploys.

## Optional — Docker

```bash
docker build -t coffee-daas .
docker run -p 8000:8000 coffee-daas
```
