"""
Step 5 of the DaaS project: access the service from many clients at once.

Simulates N concurrent clients, each sending requests to a mix of endpoints,
then reports success rate and latency statistics.

Usage:
  python client_test.py                                   # local server
  python client_test.py https://coffee-daas.onrender.com  # deployed server
  python client_test.py <URL> --clients 50 --requests 500
  python client_test.py <URL> --key mysecret              # if API_KEY is set
"""
import argparse
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

ENDPOINTS = [
    "/coffees?limit=10",
    "/coffees/42",
    "/search?country=Ethiopia&min_score=85",
    "/search?process=Natural&min_altitude=1500",
    "/top?n=5",
    "/countries",
    "/stats/by-country",
    "/stats/by-process",
]


def one_request(base, path, headers, client_id):
    t0 = time.perf_counter()
    try:
        r = requests.get(base + path, headers=headers, timeout=60)
        status = r.status_code
    except requests.RequestException as e:
        status = f"ERR:{type(e).__name__}"
    return client_id, path, status, (time.perf_counter() - t0) * 1000


def pct(data, p):
    data = sorted(data)
    k = max(0, min(len(data) - 1, round(p / 100 * (len(data) - 1))))
    return data[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default="http://127.0.0.1:8000")
    ap.add_argument("--clients", type=int, default=20, help="concurrent clients")
    ap.add_argument("--requests", type=int, default=200, help="total requests")
    ap.add_argument("--key", default=None, help="X-API-Key value, if enabled")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    headers = {"X-API-Key": a.key} if a.key else {}

    # Warm-up request: measures cold start on free-tier hosting separately
    print(f"Target: {base}")
    _, _, s, ms = one_request(base, "/health", headers, 0)
    print(f"Warm-up /health -> {s} in {ms:.0f} ms (includes cold start if the server was asleep)\n")

    jobs = [(base, ENDPOINTS[i % len(ENDPOINTS)], headers, i % a.clients)
            for i in range(a.requests)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.clients) as pool:
        results = list(pool.map(lambda j: one_request(*j), jobs))
    wall = time.perf_counter() - t0

    lat = [r[3] for r in results]
    codes = Counter(r[2] for r in results)
    ok = codes.get(200, 0)
    print(f"Concurrent clients : {a.clients}")
    print(f"Total requests     : {a.requests}")
    print(f"Successful (200)   : {ok}/{a.requests} ({100 * ok / a.requests:.1f}%)")
    print(f"Status codes       : {dict(codes)}")
    print(f"Wall time          : {wall:.2f} s")
    print(f"Throughput         : {a.requests / wall:.1f} req/s")
    print(f"Latency ms         : avg {statistics.mean(lat):.0f} | p50 {pct(lat, 50):.0f} | "
          f"p95 {pct(lat, 95):.0f} | max {max(lat):.0f}\n")

    per = defaultdict(list)
    for _, path, _, ms in results:
        per[path].append(ms)
    print(f"{'Endpoint':45} {'n':>4} {'avg ms':>8} {'p95 ms':>8}")
    for path, v in per.items():
        print(f"{path:45} {len(v):>4} {statistics.mean(v):>8.0f} {pct(v, 95):>8.0f}")


if __name__ == "__main__":
    main()
