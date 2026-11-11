#!/usr/bin/env python3
"""Run the scraper over out/queries-manifest.csv in small, resumable batches.

- Batches of BATCH_SIZE queries that share the same depth (grid queries run
  one city per batch with -grid-bbox).
- Low concurrency, a pause between batches.
- After each batch the raw scraper output is sanitized (reviews, reviewer
  names, owner account ids, images, emails dropped) and written to
  out/raw/batch-NNN.jsonl; the unsanitized file is deleted right away.
- A batch whose out/raw file already exists is skipped, so the script can be
  re-run after an interruption.
- If the log shows signs of a captcha / block, the script stops immediately.

Env:
  GMS_BIN                 path to the scraper binary (default: bin/gms)
  GMS_WORKDIR             scratch dir for unsanitized output (default: /tmp/gms)
  PLAYWRIGHT_DRIVER_PATH  / PLAYWRIGHT_BROWSERS_PATH are passed through.
"""

import csv
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "out"
RAW = OUT / "raw"

BATCH_SIZE = 20
CONCURRENCY = 2
PAUSE_BETWEEN_BATCHES_S = 45
INACTIVITY = "90s"
LANG = "vi"
GRID_CELL_KM = 4
GRID_ZOOM = 14
BATCH_TIMEOUT_S = 60 * 60

# Fields kept from the scraper output: business information only.
KEEP_FIELDS = [
    "input_id", "link", "cid", "title", "categories", "category", "address",
    "open_hours", "web_site", "phone", "plus_code", "review_count",
    "review_rating", "latitude", "longtitude", "status", "description",
    "timezone", "price_range", "data_id", "place_id", "reservations",
    "order_online", "menu", "complete_address", "about",
]

BLOCK_PATTERNS = re.compile(
    r"captcha|unusual traffic|/sorry/|recaptcha|429 Too Many|detected unusual",
    re.IGNORECASE,
)


def make_batches(rows):
    batches = []
    current = []
    for r in rows:
        if r["kind"] == "grid":
            if current:
                batches.append(current)
                current = []
            batches.append([r])
            continue
        if current and (len(current) >= BATCH_SIZE or current[0]["depth"] != r["depth"]):
            batches.append(current)
            current = []
        current.append(r)
    if current:
        batches.append(current)
    return batches


def sanitize(src: pathlib.Path, dst: pathlib.Path) -> int:
    n = 0
    with open(src, encoding="utf-8") as fin, open(dst, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            clean = {k: rec.get(k) for k in KEEP_FIELDS}
            fout.write(json.dumps(clean, ensure_ascii=False) + "\n")
            n += 1
    return n


def main() -> int:
    gms = os.environ.get("GMS_BIN", str(ROOT / "bin" / "gms"))
    work = pathlib.Path(os.environ.get("GMS_WORKDIR", "/tmp/gms"))
    work.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(open(OUT / "queries-manifest.csv", encoding="utf-8")))
    batches = make_batches(rows)
    print(f"{len(rows)} queries in {len(batches)} batches", flush=True)

    status_path = RAW / "batches.csv"
    done_ids = set()
    if status_path.exists():
        done_ids = {r["batch"] for r in csv.DictReader(open(status_path, encoding="utf-8"))}

    for i, batch in enumerate(batches, start=1):
        bid = f"batch-{i:03d}"
        dst = RAW / f"{bid}.jsonl"
        if bid in done_ids and dst.exists():
            continue

        qfile = work / f"{bid}.txt"
        qfile.write_text("".join(f"{r['query']} #!#{r['id']}\n" for r in batch), encoding="utf-8")
        tmp_out = work / f"{bid}.json"
        log_path = work / f"{bid}.log"

        cmd = [
            gms, "-input", str(qfile), "-results", str(tmp_out), "-json",
            "-lang", LANG, "-depth", batch[0]["depth"], "-c", str(CONCURRENCY),
            "-exit-on-inactivity", INACTIVITY,
        ]
        if batch[0]["kind"] == "grid":
            cmd += ["-grid-bbox", batch[0]["grid_bbox"], "-grid-cell", str(GRID_CELL_KM),
                    "-zoom", str(GRID_ZOOM)]

        started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        t0 = time.time()
        with open(log_path, "w", encoding="utf-8") as lf:
            try:
                proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=BATCH_TIMEOUT_S)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                rc = -1
        elapsed = time.time() - t0

        log = log_path.read_text(encoding="utf-8", errors="replace")
        n_err = len(re.findall(r'"status":"failed"|"level":"error"', log))
        blocked = bool(BLOCK_PATTERNS.search(log))

        n = sanitize(tmp_out, dst) if tmp_out.exists() else 0
        if tmp_out.exists():
            tmp_out.unlink()  # never keep unsanitized output

        if blocked or rc != 0:
            dst.unlink(missing_ok=True)  # batch must be re-run on resume
            print(f"STOP: {'possible captcha/block' if blocked else 'scraper exit code ' + str(rc)} "
                  f"in {bid} ({n} results, {n_err} errors); see {log_path}", flush=True)
            return 2

        new_file = not status_path.exists()
        with open(status_path, "a", encoding="utf-8", newline="") as sf:
            w = csv.writer(sf)
            if new_file:
                w.writerow(["batch", "query_ids", "depth", "kind", "results", "errors",
                            "exit_code", "started_at", "elapsed_s", "command"])
            w.writerow([bid, " ".join(r["id"] for r in batch), batch[0]["depth"], batch[0]["kind"],
                        n, n_err, rc, started, f"{elapsed:.0f}",
                        " ".join(c if " " not in c else repr(c) for c in cmd[1:])])

        print(f"{bid}: {len(batch)} queries, {n} results, {n_err} errors, rc={rc}, {elapsed:.0f}s", flush=True)

        if i < len(batches):
            time.sleep(PAUSE_BETWEEN_BATCHES_S)

    print("all batches done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
