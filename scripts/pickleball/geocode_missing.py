#!/usr/bin/env python3
"""Reverse-geocode courts whose Google address has no street (plus code only).

Uses OpenStreetMap Nominatim (https://nominatim.org/release-docs/latest/api/Reverse/)
within its usage policy: one request per second, a descriptive User-Agent,
results cached in out/geocode-osm.json so each place is asked only once.

Only street-level parts are kept (house number, road, hamlet/quarter); ward and
province stay as Google gave them. clean_courts.py merges the cache into
`address` and flags those rows in `notes`.

Data © OpenStreetMap contributors, ODbL 1.0.
"""

import csv
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import clean_courts as cc  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "out"
CACHE = OUT / "geocode-osm.json"

ENDPOINT = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "pickleball-court-candidates/1.0 (google-maps-scraper scripts/pickleball)"
MIN_INTERVAL_S = 1.1  # Nominatim policy: max 1 request/second


def needs_street(addr: str) -> bool:
    addr = cc.nfc(addr or "")
    return not addr or bool(cc.PLUS_CODE_RE.match(addr))


def main() -> int:
    keep = {r["place_id"]: r for r in csv.DictReader(open(OUT / "courts-candidates.csv", encoding="utf-8-sig"))}
    todo = {}
    for f in sorted(OUT.glob("raw/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            rec = json.loads(line)
            pid = rec.get("place_id")
            if pid in keep and pid not in todo and needs_street(rec.get("address")):
                todo[pid] = (rec["latitude"], rec["longtitude"])

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    pending = [p for p in todo if p not in cache]
    print(f"{len(todo)} courts without street address, {len(pending)} not cached yet", flush=True)

    last = 0.0
    for i, pid in enumerate(pending, 1):
        lat, lng = todo[pid]
        qs = urllib.parse.urlencode({
            "format": "jsonv2", "lat": f"{lat:.7f}", "lon": f"{lng:.7f}",
            "zoom": 18, "addressdetails": 1, "accept-language": "vi",
        })
        wait = MIN_INTERVAL_S - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.time()
        req = urllib.request.Request(f"{ENDPOINT}?{qs}", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
        except Exception as e:  # noqa: BLE001 - keep going, record the failure
            print(f"{pid}: {e}", flush=True)
            if "429" in str(e) or "403" in str(e):
                print("STOP: rate limited / refused by Nominatim", flush=True)
                break
            continue
        a = data.get("address") or {}
        cache[pid] = {
            "house_number": a.get("house_number", ""),
            "road": a.get("road", ""),
            "area": a.get("quarter") or a.get("hamlet") or a.get("neighbourhood") or a.get("village") or "",
            "osm_lat": float(data["lat"]) if data.get("lat") else None,
            "osm_lng": float(data["lon"]) if data.get("lon") else None,
            "display_name": data.get("display_name", ""),
        }
        if i % 50 == 0:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{i}/{len(pending)}", flush=True)

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"cached {len(cache)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
