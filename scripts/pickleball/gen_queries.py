#!/usr/bin/env python3
"""Generate Google Maps queries for pickleball courts across Vietnam.

Reads out/tinh-34.csv and writes:
  out/queries.txt         one query per line, "<text> #!#<id>" (scraper input format)
  out/queries-manifest.csv id, kind, province_new, area, query, depth, grid_bbox

Kinds:
  province  - 3 queries per new province name
  old       - 2 queries per former province name merged into a new one
  district  - 1 query per former district / large ward in the 5 big cities
  grid      - 1 query per city, run with -grid-bbox over the urban core
"""

import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "out"

PROVINCE_DEPTH = 3  # ~3 scrolls -> up to ~60 results per query
OLD_DEPTH = 2
DISTRICT_DEPTH = 2
GRID_DEPTH = 1

# Former districts / large wards (addresses and Maps still use these names).
DISTRICTS = {
    "Hồ Chí Minh": [
        "Quận 1", "Quận 3", "Quận 4", "Quận 5", "Quận 6", "Quận 7", "Quận 8",
        "Quận 10", "Quận 11", "Quận 12", "Bình Thạnh", "Gò Vấp", "Phú Nhuận",
        "Tân Bình", "Tân Phú", "Bình Tân", "Thủ Đức", "Thảo Điền", "Thủ Thiêm",
        "Củ Chi", "Hóc Môn", "Bình Chánh", "Nhà Bè", "Cần Giờ",
        "Thủ Dầu Một", "Dĩ An", "Thuận An", "Bến Cát", "Tân Uyên",
        "Vũng Tàu", "Bà Rịa", "Phú Mỹ",
    ],
    "Hà Nội": [
        "Ba Đình", "Hoàn Kiếm", "Đống Đa", "Hai Bà Trưng", "Tây Hồ", "Cầu Giấy",
        "Thanh Xuân", "Hoàng Mai", "Long Biên", "Bắc Từ Liêm", "Nam Từ Liêm",
        "Hà Đông", "Sơn Tây", "Gia Lâm", "Đông Anh", "Thanh Trì", "Hoài Đức",
        "Đan Phượng", "Thường Tín", "Mê Linh", "Sóc Sơn", "Chương Mỹ",
        "Thạch Thất", "Quốc Oai", "Ecopark",
    ],
    "Đà Nẵng": [
        "Hải Châu", "Thanh Khê", "Sơn Trà", "Ngũ Hành Sơn", "Liên Chiểu",
        "Cẩm Lệ", "Hòa Vang", "Hội An", "Tam Kỳ", "Điện Bàn",
    ],
    "Hải Phòng": [
        "Lê Chân", "Ngô Quyền", "Hồng Bàng", "Hải An", "Kiến An", "Dương Kinh",
        "Đồ Sơn", "Thủy Nguyên", "An Dương", "TP Hải Dương", "Chí Linh",
        "Kinh Môn",
    ],
    "Cần Thơ": [
        "Ninh Kiều", "Cái Răng", "Bình Thủy", "Ô Môn", "Thốt Nốt",
        "TP Sóc Trăng", "Vị Thanh", "Ngã Bảy",
    ],
}

# Urban cores scanned with -grid-bbox (minLat,minLon,maxLat,maxLon).
GRIDS = {
    "Hồ Chí Minh": "10.70,106.60,10.90,106.82",
    "Hà Nội": "20.95,105.74,21.10,105.90",
    "Đà Nẵng": "15.97,108.14,16.10,108.27",
    "Hải Phòng": "20.80,106.62,20.88,106.75",
    "Cần Thơ": "9.98,105.71,10.07,105.80",
}


def main() -> int:
    provinces = list(csv.DictReader(open(OUT / "tinh-34.csv", encoding="utf-8")))
    rows = []

    def add(kind, prov, area, query, depth, bbox=""):
        rows.append({
            "id": f"q{len(rows) + 1:03d}",
            "kind": kind,
            "province_new": prov,
            "area": area,
            "query": query,
            "depth": depth,
            "grid_bbox": bbox,
        })

    for p in provinces:
        name = p["new_name"]
        for tmpl in ("sân pickleball {}", "pickleball {}", "pickleball court {}"):
            add("province", name, name, tmpl.format(name), PROVINCE_DEPTH)

    for p in provinces:
        name = p["new_name"]
        for old in (o.strip() for o in p["old_names"].split(";")):
            if old and old != name:
                for tmpl in ("sân pickleball {}", "pickleball {}"):
                    add("old", name, old, tmpl.format(old), OLD_DEPTH)

    for city, districts in DISTRICTS.items():
        for d in districts:
            add("district", city, d, f"sân pickleball {d}, {city}", DISTRICT_DEPTH)

    for city, bbox in GRIDS.items():
        add("grid", city, city, "sân pickleball", GRID_DEPTH, bbox)

    with open(OUT / "queries-manifest.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    with open(OUT / "queries.txt", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{r['query']} #!#{r['id']}\n")

    counts = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    print(f"{len(rows)} queries: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
