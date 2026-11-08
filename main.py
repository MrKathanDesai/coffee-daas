"""
Step 2 of the DaaS project: the service layer.

A REST API (FastAPI) that exposes the coffee database to clients.
Clients never touch the database directly; they only call these endpoints.

Run locally:  uvicorn main:app --reload
Docs (Swagger UI):  http://127.0.0.1:8000/docs
"""
import csv
import io
import os
import sqlite3
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

DB_PATH = os.environ.get("DB_PATH", "coffee.db")
API_KEY = os.environ.get("API_KEY")          # if set, clients must send X-API-Key
START_TIME = time.time()
REQUEST_COUNT = 0

app = FastAPI(
    title="Coffee Quality DaaS",
    description="Data as a Service: CQI Arabica coffee quality data (1,310 samples, "
                "36 countries) exposed through a REST API.",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"],
                   allow_headers=["*"])

# Columns a client may sort by (whitelist prevents SQL injection via ORDER BY)
SORTABLE = {"id", "country", "altitude_m", "harvest_year", "aroma", "flavor",
            "acidity", "body", "total_cup_points"}


# ---------- helpers ----------
def query(sql: str, args=()):
    """Open a read-only connection per request (safe under concurrent clients)."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def check_key(x_api_key: Optional[str] = Header(default=None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")


@app.middleware("http")
async def timing(request: Request, call_next):
    """Adds X-Process-Time-ms to every response; useful for the report."""
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-ms"] = f"{(time.perf_counter() - t0) * 1000:.2f}"
    return response


def build_filters(country, variety, process, min_score, max_score,
                  min_altitude, max_altitude, year):
    where, args = [], []
    if country:
        where.append("country LIKE ?"); args.append(f"%{country}%")
    if variety:
        where.append("variety LIKE ?"); args.append(f"%{variety}%")
    if process:
        where.append("processing_method LIKE ?"); args.append(f"%{process}%")
    if min_score is not None:
        where.append("total_cup_points >= ?"); args.append(min_score)
    if max_score is not None:
        where.append("total_cup_points <= ?"); args.append(max_score)
    if min_altitude is not None:
        where.append("altitude_m >= ?"); args.append(min_altitude)
    if max_altitude is not None:
        where.append("altitude_m <= ?"); args.append(max_altitude)
    if year is not None:
        where.append("harvest_year = ?"); args.append(year)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, args


# ---------- service info ----------
@app.get("/", tags=["Service"])
def root():
    return {
        "service": "Coffee Quality DaaS",
        "docs": "/docs",
        "endpoints": ["/health", "/coffees", "/coffees/{id}", "/search", "/countries",
                      "/top", "/stats/by-country", "/stats/by-process", "/export"],
    }


@app.get("/health", tags=["Service"])
def health():
    rows = query("SELECT COUNT(*) AS n FROM coffee")[0]["n"]
    return {"status": "ok", "records": rows,
            "uptime_s": round(time.time() - START_TIME, 1),
            "requests_served": REQUEST_COUNT}


# ---------- retrieval ----------
@app.get("/coffees", tags=["Retrieve"], dependencies=[Depends(check_key)])
def list_coffees(limit: int = Query(20, ge=1, le=100),
                 offset: int = Query(0, ge=0),
                 sort_by: str = "id",
                 order: str = Query("asc", pattern="^(asc|desc)$")):
    """List all samples with pagination and sorting."""
    if sort_by not in SORTABLE:
        raise HTTPException(400, f"sort_by must be one of {sorted(SORTABLE)}")
    total = query("SELECT COUNT(*) AS n FROM coffee")[0]["n"]
    items = query(f"SELECT * FROM coffee ORDER BY {sort_by} {order} LIMIT ? OFFSET ?",
                  (limit, offset))
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/coffees/{coffee_id}", tags=["Retrieve"], dependencies=[Depends(check_key)])
def get_coffee(coffee_id: int):
    """Get one sample by its id."""
    rows = query("SELECT * FROM coffee WHERE id = ?", (coffee_id,))
    if not rows:
        raise HTTPException(404, f"Coffee {coffee_id} not found")
    return rows[0]


# ---------- search ----------
@app.get("/search", tags=["Search"], dependencies=[Depends(check_key)])
def search(country: Optional[str] = None,
           variety: Optional[str] = None,
           process: Optional[str] = Query(None, description="e.g. Washed, Natural, honey"),
           min_score: Optional[float] = Query(None, ge=0, le=100),
           max_score: Optional[float] = Query(None, ge=0, le=100),
           min_altitude: Optional[float] = None,
           max_altitude: Optional[float] = None,
           year: Optional[int] = None,
           limit: int = Query(50, ge=1, le=500),
           offset: int = Query(0, ge=0)):
    """Filter samples by any combination of fields. Text filters are partial, case-insensitive."""
    clause, args = build_filters(country, variety, process, min_score, max_score,
                                 min_altitude, max_altitude, year)
    total = query(f"SELECT COUNT(*) AS n FROM coffee{clause}", args)[0]["n"]
    items = query(f"SELECT * FROM coffee{clause} ORDER BY total_cup_points DESC "
                  f"LIMIT ? OFFSET ?", args + [limit, offset])
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/countries", tags=["Search"], dependencies=[Depends(check_key)])
def countries():
    """Distinct countries with sample counts (useful for building client dropdowns)."""
    return query("SELECT country, COUNT(*) AS samples FROM coffee "
                 "GROUP BY country ORDER BY samples DESC")


@app.get("/top", tags=["Search"], dependencies=[Depends(check_key)])
def top(n: int = Query(10, ge=1, le=100), country: Optional[str] = None):
    """Highest-scoring samples, optionally within one country."""
    clause, args = build_filters(country, None, None, None, None, None, None, None)
    return query(f"SELECT id, country, region, variety, processing_method, "
                 f"total_cup_points FROM coffee{clause} "
                 f"ORDER BY total_cup_points DESC LIMIT ?", args + [n])


# ---------- aggregates ----------
@app.get("/stats/by-country", tags=["Statistics"], dependencies=[Depends(check_key)])
def stats_by_country(min_samples: int = Query(5, ge=1)):
    """Average cupping scores per country (countries with at least min_samples)."""
    return query("""
        SELECT country, COUNT(*) AS samples,
               ROUND(AVG(total_cup_points), 2) AS avg_score,
               ROUND(MAX(total_cup_points), 2) AS best_score,
               ROUND(AVG(altitude_m), 0)       AS avg_altitude_m
        FROM coffee GROUP BY country HAVING COUNT(*) >= ?
        ORDER BY avg_score DESC""", (min_samples,))


@app.get("/stats/by-process", tags=["Statistics"], dependencies=[Depends(check_key)])
def stats_by_process():
    """Average scores per processing method."""
    return query("""
        SELECT COALESCE(processing_method, 'Unknown') AS processing_method,
               COUNT(*) AS samples,
               ROUND(AVG(total_cup_points), 2) AS avg_score,
               ROUND(AVG(acidity), 2) AS avg_acidity,
               ROUND(AVG(body), 2)    AS avg_body
        FROM coffee GROUP BY processing_method ORDER BY avg_score DESC""")


# ---------- export ----------
@app.get("/export", tags=["Export"], dependencies=[Depends(check_key)])
def export_csv(country: Optional[str] = None, process: Optional[str] = None,
               min_score: Optional[float] = None):
    """Download filtered data as CSV (same data, a second delivery format)."""
    clause, args = build_filters(country, None, process, min_score, None, None, None, None)
    rows = query(f"SELECT * FROM coffee{clause} ORDER BY id", args)
    if not rows:
        raise HTTPException(404, "No rows match these filters")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader(); writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=coffee.csv"})
