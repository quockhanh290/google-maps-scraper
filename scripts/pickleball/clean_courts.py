#!/usr/bin/env python3
"""Clean raw Google Maps results into pickleball court candidates.

Inputs  (all under out/):
  raw/batch-*.jsonl, raw/retry-*.jsonl  sanitized scraper output (see run_batches.py)
  raw/batches.csv        batch log (used for retrieved_at)
  queries-manifest.csv   query id -> province of the query
  tinh-34.csv            34 new provinces with their former provinces

Outputs (UTF-8 with BOM so Excel opens them correctly):
  courts-candidates.csv  kept courts, columns of the app's `courts` table
  loai-bo.csv            rejected places with the reason
  clean-stats.json       counts used by out/README.md

Nothing is written to any database.
"""

import collections
import csv
import difflib
import json
import math
import pathlib
import re
import sys
import unicodedata
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "out"

DEDUP_RADIUS_M = 150
NAME_SIMILARITY = 0.80
NEAREST_PROVINCE_KM = 15  # fallback: borrow province from a resolved court this close
VN_BBOX = (8.0, 102.0, 23.5, 110.0)  # min lat, min lon, max lat, max lon (mainland + coast)

COLUMNS = [
    "name", "address", "city", "province_new", "province_old", "lat", "lng", "phone",
    "hours_open", "hours_close", "price_per_hour", "booking_url", "google_maps_url",
    "rating", "rating_count", "place_id", "category", "retrieved_at", "confidence", "notes",
]
REJECT_COLUMNS = [
    "name", "address", "category", "categories", "lat", "lng", "place_id",
    "google_maps_url", "reason", "query_ids",
]

# Category keywords (unaccented, lower case).
VENUE_CATS = [
    "san pickleball", "san the thao", "to hop the thao", "trung tam the thao",
    "khu the thao", "khu lien hop the thao", "nha thi dau", "san tennis",
    "san quan vot", "cau lac bo quan vot", "san cau long", "san bong",
    "cau lac bo the thao", "phong tap", "co so the thao", "san choi", "cong vien",
    "khu vui choi", "khu nghi duong", "khach san", "truong hoc the thao",
    "sports complex", "sports club", "pickleball court", "tennis court",
]
STORE_CATS = [
    "cua hang", "nha ban le", "nha cung cap", "nha phan phoi", "nha san xuat",
    "dai ly", "shop", "store", "nha ban buon", "cong ty", "dich vu sua chua",
]
COACH_CATS = ["huan luyen vien", "truong day", "lop hoc", "giao vien", "coach"]
TENNIS_CATS = ["san tennis", "san quan vot", "cau lac bo quan vot", "tennis court"]
CLUB_ONLY_CATS = ["cau lac bo the thao", "sports club"]

# Host substrings of real booking sites. Social links (facebook, zalo, ...) never count.
BOOKING_HOSTS = [
    "alobo", "datsan", "dat-san", "datlich", "bookingsport", "courtbooking",
    "booking", "courtreserve", "playo", "reserve",
]
SOCIAL_HOSTS = ["facebook", "fb.com", "zalo", "tiktok", "instagram", "youtu", "wa.me", "google.com"]

# Pickleball and common misspellings seen in place names (normalized text).
PB_NAME_RE = re.compile(
    r"pickleball|pickle ball|pickcleball|pikeball|pikleball|pickellball|pickelball|"
    r"pickeball|pickerball|picklebal\b|pickle\b"
)


def strip_accents(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def haversine_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- provinces

def load_provinces():
    """Return {normalized variant: (new_name, old_name_or_empty)}."""
    variants = {}
    rows = list(csv.DictReader(open(OUT / "tinh-34.csv", encoding="utf-8")))
    for r in rows:
        new = r["new_name"]
        for old in [o.strip() for o in r["old_names"].split(";") if o.strip()]:
            variants[norm(old)] = (new, "" if old == new else old)
        variants[norm(new)] = (new, "")
    extra = {
        "thanh pho ho chi minh": ("Hồ Chí Minh", ""), "tp ho chi minh": ("Hồ Chí Minh", ""),
        "tp hcm": ("Hồ Chí Minh", ""), "hcm": ("Hồ Chí Minh", ""), "sai gon": ("Hồ Chí Minh", ""),
        "ho chi minh city": ("Hồ Chí Minh", ""),
        "thua thien hue": ("Huế", "Thừa Thiên Huế"), "thanh pho hue": ("Huế", ""),
        "ba ria vung tau": ("Hồ Chí Minh", "Bà Rịa - Vũng Tàu"),
        "br vt": ("Hồ Chí Minh", "Bà Rịa - Vũng Tàu"),
        "dak lak": ("Đắk Lắk", ""), "daklak": ("Đắk Lắk", ""), "dac lac": ("Đắk Lắk", ""),
        "dak nong": ("Lâm Đồng", "Đắk Nông"), "daknong": ("Lâm Đồng", "Đắk Nông"),
        "bac can": ("Thái Nguyên", "Bắc Kạn"), "kon tum": ("Quảng Ngãi", "Kon Tum"),
        "kontum": ("Quảng Ngãi", "Kon Tum"), "ha noi": ("Hà Nội", ""), "hanoi": ("Hà Nội", ""),
        "da nang": ("Đà Nẵng", ""), "danang": ("Đà Nẵng", ""), "thanh hoa": ("Thanh Hóa", ""),
        "khanh hoa": ("Khánh Hòa", ""), "hoa binh": ("Phú Thọ", "Hòa Bình"),
    }
    for k, v in extra.items():
        variants.setdefault(k, v)
    # Normalize prefixes like "tinh", "thanh pho", "tp" when matching.
    return variants, [r["new_name"] for r in rows]


PREFIX_RE = re.compile(r"^(tinh|thanh pho|tp)\s+")


def province_from_address(rec, variants):
    """Return (new, old, source) using the trailing address components."""
    candidates = []
    addr = rec.get("address") or ""
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    tail = [p for p in reversed(parts) if norm(p) not in ("viet nam", "vietnam")][:2]
    for p in tail:
        candidates.append(re.sub(r"\b\d{5,6}\b", "", p))
    ca = rec.get("complete_address") or {}
    for key in ("city", "state"):
        v = ca.get(key) or ""
        if v:
            candidates.append(v.split(",")[-1])
    for c in candidates:
        n = PREFIX_RE.sub("", norm(c))
        n = re.sub(r"\s*\d+$", "", n).strip()
        if n in variants:
            new, old = variants[n]
            return new, old, "address"
    return "", "", ""


# ---------------------------------------------------------------- classification

def has_any(text, words):
    return any(w in text for w in words)


def classify(rec):
    """Return (keep: bool, confidence, reason_or_note)."""
    title = norm(rec.get("title"))
    cats = [norm(c) for c in (rec.get("categories") or [])]
    primary = norm(rec.get("category"))
    if primary and primary not in cats:
        cats.insert(0, primary)
    cat_text = " | ".join(cats)
    desc = norm(" ".join(filter(None, [rec.get("description") or "",
                                        json.dumps(rec.get("about") or "", ensure_ascii=False)])))
    pb_name = bool(PB_NAME_RE.search(title))
    pb_cat = "pickleball" in cat_text
    court_cat_primary = primary in ("san pickleball", "pickleball court")
    court_cat_any = any(c in ("san pickleball", "pickleball court") for c in cats)
    venue = has_any(cat_text, VENUE_CATS)
    # "Cửa hàng cà phê" (cafe) is not an equipment store; many courts are cafes.
    store_primary = has_any(primary, STORE_CATS) and "ca phe" not in primary
    coach_primary = has_any(primary, COACH_CATS)
    status = norm(rec.get("status"))
    name_says_court = bool(re.search(r"\b(san|court|courts|arena|center|centre|park|complex)\b", title))
    name_says_shop = bool(re.search(r"\b(shop|store|cua hang|vot|paddle|sport shop|dung cu)\b", title))

    lat, lng = rec.get("latitude"), rec.get("longtitude")
    if not lat or not lng:
        return False, "", "không có toạ độ"
    if not (VN_BBOX[0] <= lat <= VN_BBOX[2] and VN_BBOX[1] <= lng <= VN_BBOX[3]):
        return False, "", "ngoài lãnh thổ Việt Nam"
    country = ((rec.get("complete_address") or {}).get("country") or "").upper()
    if country and country != "VN":
        return False, "", f"quốc gia {country}"
    if "vinh vien" in status or "permanently" in status:
        return False, "", "đã đóng cửa vĩnh viễn"

    if store_primary and not court_cat_any:
        if pb_name and name_says_court and not name_says_shop:
            return True, "low", f"danh mục '{rec.get('category')}' nhưng tên ghi là sân — cần kiểm tra"
        return False, "", "cửa hàng/nhà cung cấp dụng cụ, không phải sân"
    if name_says_shop and not court_cat_any and not name_says_court:
        return False, "", "tên cho thấy cửa hàng dụng cụ"
    if coach_primary and not court_cat_any and not name_says_court:
        return False, "", "huấn luyện viên/lớp học, không phải sân"

    if court_cat_primary:
        return True, "high", ""
    if court_cat_any:
        return True, ("high" if pb_name else "medium"), "danh mục phụ là Sân pickleball"
    if pb_name and venue:
        if has_any(primary, CLUB_ONLY_CATS) and not name_says_court:
            return True, "low", "danh mục CLB thể thao — cần kiểm tra có sân riêng"
        if has_any(cat_text, TENNIS_CATS):
            return True, "medium", "danh mục sân tennis, tên có pickleball"
        return True, "medium", ("" if name_says_court else "tên không ghi rõ là sân")
    if pb_name and not primary:
        return True, "low", "không có danh mục"
    if pb_name:
        return True, "low", f"danh mục '{rec.get('category')}' không phải sân thể thao — cần kiểm tra"
    if pb_cat:
        return False, "", "danh mục pickleball nhưng không phải sân (HLV/khác)"
    if "pickleball" in desc and venue:
        return True, "low", "chỉ mô tả nhắc pickleball"
    if has_any(cat_text, TENNIS_CATS):
        return False, "", "sân tennis thuần, không nhắc pickleball"
    return False, "", "không liên quan pickleball"


# ---------------------------------------------------------------- fields

HOUR_RE = re.compile(r"(\d{1,2})(?:[:.h](\d{2}))?\s*(SA|CH|AM|PM)?", re.IGNORECASE)
DAY_ORDER = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def to_hhmm(h, m, ampm):
    h, m = int(h), int(m or 0)
    if ampm:
        a = ampm.upper()
        if a in ("CH", "PM") and h < 12:
            h += 12
        if a in ("SA", "AM") and h == 12:
            h = 0
    if h == 24:
        h, m = 23, 59
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return ""
    return f"{h:02d}:{m:02d}"


def parse_slot(slot: str):
    s = slot.replace(" ", " ").replace(" ", " ")
    n = norm(s)
    if "ca ngay" in n or "24 gio" in n or "open 24" in n:
        return ("00:00", "23:59")
    if "dong cua" in n or n == "closed":
        return None
    parts = re.split(r"\s*[–—-]\s*|\s+to\s+", s)
    if len(parts) != 2:
        return None
    a, b = HOUR_RE.search(parts[0]), HOUR_RE.search(parts[1])
    if not a or not b:
        return None
    ampm_b = b.group(3)
    ampm_a = a.group(3) or ampm_b
    o, c = to_hhmm(a.group(1), a.group(2), ampm_a), to_hhmm(b.group(1), b.group(2), ampm_b)
    return (o, c) if o and c else None


def parse_hours(open_hours):
    """Return (open, close, note)."""
    if not open_hours:
        return "", "", ""
    per_day = {}
    for day, slots in open_hours.items():
        parsed = [parse_slot(s) for s in (slots or [])]
        parsed = [p for p in parsed if p]
        if parsed:
            per_day[day] = (min(p[0] for p in parsed), max(p[1] for p in parsed), len(parsed) > 1)
        else:
            per_day[day] = None
    spans = collections.Counter((v[0], v[1]) for v in per_day.values() if v)
    if not spans:
        return "", "", "giờ: " + "; ".join(f"{d}: {', '.join(s)}" for d, s in open_hours.items())
    (o, c), _ = spans.most_common(1)[0]
    differs = len(spans) > 1 or any(v is None for v in per_day.values()) or any(v and v[2] for v in per_day.values())
    note = ""
    if differs:
        ordered = sorted(open_hours.items(), key=lambda kv: DAY_ORDER.index(kv[0]) if kv[0] in DAY_ORDER else 99)
        note = "giờ theo ngày: " + "; ".join(f"{d}: {', '.join(s)}" for d, s in ordered)
    return o, c, note


PRICE_RE = re.compile(
    r"(\d{2,3}(?:[.,]\d{3})+|\d{2,3}\s*k)\s*(?:vnd|vnđ|đ|d)?\s*/\s*(?:1\s*)?(?:giờ|gio|h|tiếng|tieng)\b",
    re.IGNORECASE,
)


def parse_price(rec):
    text = " ".join(filter(None, [rec.get("description") or "",
                                   json.dumps(rec.get("about") or "", ensure_ascii=False)]))
    m = PRICE_RE.search(text)
    if not m:
        return ""
    v = m.group(1).lower().replace(" ", "")
    if v.endswith("k"):
        return str(int(v[:-1]) * 1000)
    return re.sub(r"[.,]", "", v)


def booking_url(rec):
    # Google lists booking partners (e.g. alobo.vn) under reservations / order_online.
    for res in (rec.get("reservations"), rec.get("order_online")):
        if not isinstance(res, list):
            continue
        for r in res:
            link = (r or {}).get("link") if isinstance(r, dict) else None
            if link:
                return link
    site = rec.get("web_site") or ""
    host = urllib.parse.urlparse(site).netloc.lower()
    path = urllib.parse.urlparse(site).path.lower()
    if not site or any(k in host for k in SOCIAL_HOSTS):
        return ""
    if any(k in host for k in BOOKING_HOSTS) or any(k in path for k in ("booking", "dat-san", "datsan")):
        return site
    return ""


def maps_url(rec):
    pid = rec.get("place_id") or ""
    if pid:
        q = urllib.parse.quote(rec.get("title") or "")
        return f"https://www.google.com/maps/search/?api=1&query={q}&query_place_id={pid}"
    return (rec.get("link") or "").split("&g_ep=")[0]


# ---------------------------------------------------------------- normalization

def nfc(obj):
    """Unicode-NFC every string in a JSON value (Google mixes NFC and NFD)."""
    if isinstance(obj, str):
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", obj)).strip()
    if isinstance(obj, list):
        return [nfc(v) for v in obj]
    if isinstance(obj, dict):
        return {k: nfc(v) for k, v in obj.items()}
    return obj


# "pickle ball", "PickleBall", "Pickelball", ... -> "Pickleball"
PB_SPELLING_RE = re.compile(
    r"\b(?:pickerball|pickle\s*balls?|pick(?:el|e|c?le)?balls?|picklebal|pikl?eballs?|pickellballs?)\b",
    re.IGNORECASE,
)
KEEP_UPPER = {"CLB", "TT", "TTTT", "TDTT", "VN", "KDC", "KCN", "KĐT", "ĐH", "THPT", "THCS", "UBND", "HCM"}


def _title_word(w: str) -> str:
    core = re.sub(r"[^\wÀ-ỹ]", "", w)
    if not core or any(ch.isdigit() for ch in core) or core in KEEP_UPPER:
        return w
    if len(core) <= 3 and not re.search(r"[AĂÂEÊIOÔƠUƯYÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ]", core):
        return w  # consonant-only short tokens are acronyms: TLT, PSC, HPC
    return w[:1] + w[1:].lower()


def normalize_name(name: str) -> str:
    n = nfc(name)
    letters = [c for c in n if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.9 and len(letters) > 3:
        n = " ".join(_title_word(w) for w in n.split(" "))
    else:
        # Mixed case: still fix ALL-CAPS Vietnamese words ("Sân HỘI HỢP"), keep short
        # ASCII acronyms such as PPA, UMT, MD.
        def fix(w):
            core = re.sub(r"[^\wÀ-ỹ]", "", w)
            if core.isupper() and core not in KEEP_UPPER and not any(ch.isdigit() for ch in core) and (
                    len(core) >= 4 or not core.isascii()):
                return _title_word(w)
            return w
        n = " ".join(fix(w) for w in n.split(" "))
    n = n.replace(" | ", " - ")
    n = PB_SPELLING_RE.sub("Pickleball", n)
    n = re.sub(r"\bclb\b", "CLB", n, flags=re.IGNORECASE)
    n = re.sub(r"\bsân\b", "Sân", n) if n.lower().startswith("sân") else n
    return n[:1].upper() + n[1:]


PLUS_CODE_RE = re.compile(r"^[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,3}\b\s*")
ADDR_ABBR = [
    (r"\bĐ\.\s*", "Đường "), (r"\bP\.\s*", "Phố "), (r"\bNg\.\s*", "Ngõ "),
    (r"\bNgh\.\s*", "Ngách "), (r"\bK[Pp]\.\s*", "Khu phố "), (r"\bTX\.\s*", "Thị xã "),
    (r"\bTT\.\s*", "Thị trấn "), (r"\bTP\.\s*", "Thành phố "), (r"\bQL\s*(\d)", r"Quốc lộ \1"),
    (r"\bTL\s*(\d)", r"Tỉnh lộ \1"),
]


def normalize_address(addr: str, name: str) -> str:
    """Drop country, postal codes and a leading 'PLUSCODE <place name>' part; expand abbreviations."""
    a = nfc(addr)
    if not a:
        return ""
    parts = [p.strip() for p in a.split(",") if p.strip()]
    if parts and norm(parts[-1]) in ("viet nam", "vietnam"):
        parts = parts[:-1]
    parts = [re.sub(r"\s+\d{5,6}$", "", p) for p in parts]
    if parts and PLUS_CODE_RE.match(parts[0]):
        rest = PLUS_CODE_RE.sub("", parts[0]).strip()
        # Google puts the place name after the plus code; that is not a street address.
        if not rest or difflib.SequenceMatcher(None, norm(rest), norm(name)).ratio() >= 0.6 \
                or "pickle" in norm(rest):
            parts = parts[1:]
        else:
            parts[0] = rest
    out = ", ".join(parts)
    for pat, rep in ADDR_ABBR:
        out = re.sub(pat, rep, out)
    return re.sub(r"\s+", " ", out).strip(" ,")


def normalize_phone(phone: str) -> str:
    """E.164 without spaces, e.g. +84798256666."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if digits.startswith("84"):
        return "+" + digits
    if digits.startswith("0"):
        return "+84" + digits[1:]
    return "+" + digits


TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|mibextid|igsh|igshid|ref|rdid|share_url|si)$", re.I)


def clean_url(url: str) -> str:
    if not url:
        return ""
    u = urllib.parse.urlsplit(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path, urllib.parse.urlencode(q), ""))


def iso_utc(ts: str) -> str:
    """'2026-11-11T13:04:07+0000' -> '2026-11-11T13:04:07Z'."""
    return re.sub(r"\+0000$|\+00:00$", "Z", ts or "")


STREET_RE = re.compile(
    r"\d|\b(Đường|Phố|Ngõ|Ngách|Hẻm|Kiệt|Quốc lộ|Tỉnh lộ|Đường tỉnh|Đại lộ|ĐT|QL|DT)\b", re.IGNORECASE)
AREA_RE = re.compile(
    r"^(Thôn|Ấp|Xóm|Bản|Làng|Khu|Khóm|Tổ|Khu phố|Khu dân cư|Khu đô thị|Khu du lịch|Khu công nghiệp|KDC|KĐT|KCN)\b",
    re.IGNORECASE)
OSM_MAX_DIST_M = 300  # ignore an OSM street farther than this from the court


def osm_street_prefix(rec, osm, addr_norm):
    """Street part from the OSM cache for courts Google gave no street for."""
    raw = nfc(rec.get("address") or "")
    if raw and not PLUS_CODE_RE.match(raw):
        return ""
    g = osm.get(rec.get("place_id") or "")
    if not g or g.get("osm_lat") is None:
        return ""
    if not addr_norm:
        # Google gave nothing at all: use OSM's full address minus country / postcode.
        parts = [p.strip() for p in nfc(g.get("display_name", "")).split(",")]
        parts = [re.sub(r"^(Thành phố|Tỉnh)\s+", "", p) for p in parts
                 if p and norm(p) not in ("viet nam", "vietnam") and not p.isdigit()]
        return ", ".join(parts)
    if haversine_m((rec["latitude"], rec["longtitude"]), (g["osm_lat"], g["osm_lng"])) > OSM_MAX_DIST_M:
        return ""
    lead = [p.strip() for p in addr_norm.split(",")[:-2]]  # everything before ward + province
    # Only add a street when Google's leading parts are clearly areas (Thôn, Ấp, Khu ...);
    # a bare name such as "Nguyễn Huệ" may already be the street.
    if any(STREET_RE.search(p) or not AREA_RE.match(p) for p in lead):
        return ""
    street = " ".join(p for p in (nfc(g.get("house_number", "")), nfc(g.get("road", ""))) if p)
    parts = [p for p in (street, nfc(g.get("area", ""))) if p and norm(p) not in norm(addr_norm)]
    return ", ".join(parts)


def completeness(rec):
    keys = ["phone", "web_site", "open_hours", "address", "category", "review_count"]
    return sum(1 for k in keys if rec.get(k)) + (rec.get("review_count") or 0) / 1e6


# ---------------------------------------------------------------- main

def main() -> int:
    variants, _ = load_provinces()
    manifest = {r["id"]: r for r in csv.DictReader(open(OUT / "queries-manifest.csv", encoding="utf-8"))}
    batch_time = {}
    bpath = OUT / "raw" / "batches.csv"
    if bpath.exists():
        for r in csv.DictReader(open(bpath, encoding="utf-8")):
            batch_time[r["batch"]] = r["started_at"]

    osm_path = OUT / "geocode-osm.json"
    osm = json.loads(osm_path.read_text(encoding="utf-8")) if osm_path.exists() else {}

    raw = []
    for f in sorted([*(OUT / "raw").glob("batch-*.jsonl"), *(OUT / "raw").glob("retry-*.jsonl")]):
        retrieved = batch_time.get(f.stem, "")
        for line in open(f, encoding="utf-8"):
            if line.strip():
                rec = nfc(json.loads(line))
                rec["_retrieved_at"] = iso_utc(retrieved)
                qid = (rec.get("input_id") or "").split("-")[0]
                rec["_qid"] = qid
                rec["_query_province"] = manifest.get(qid, {}).get("province_new", "")
                raw.append(rec)
    n_raw = len(raw)

    # 1) exact dedup on place_id / data_id / cid before classifying
    by_key = {}
    for rec in raw:
        key = rec.get("place_id") or rec.get("data_id") or rec.get("cid") or rec.get("link")
        if key in by_key:
            by_key[key]["_qids"].add(rec["_qid"])
            continue
        rec["_qids"] = {rec["_qid"]}
        by_key[key] = rec
    unique = list(by_key.values())
    n_unique_pid = len(unique)

    # 2) classify
    kept, rejected = [], []
    for rec in unique:
        keep, conf, why = classify(rec)
        if keep:
            rec["_conf"], rec["_note"] = conf, why
            kept.append(rec)
        else:
            rec["_reason"] = why
            rejected.append(rec)
    n_kept = len(kept)

    # 2b) coordinates that OpenStreetMap places outside Vietnam (bad Google pins)
    still = []
    for rec in kept:
        g = osm.get(rec.get("place_id") or "")
        dn = norm((g or {}).get("display_name", ""))
        if g and dn and not dn.endswith("viet nam"):
            rec["_reason"] = f"toạ độ nằm ngoài Việt Nam ({g['display_name']}) — ghim sai trên Google"
            rejected.append(rec)
        else:
            still.append(rec)
    kept = still
    n_kept = len(kept)

    # 3) fuzzy dedup: similar name and < 150 m apart
    kept.sort(key=completeness, reverse=True)
    merged = []
    for rec in kept:
        p = (rec["latitude"], rec["longtitude"])
        nm = norm(rec.get("title")).replace("pickleball", "").replace("san ", "").strip()
        dup_of = None
        for m in merged:
            if haversine_m(p, (m["latitude"], m["longtitude"])) >= DEDUP_RADIUS_M:
                continue
            mn = norm(m.get("title")).replace("pickleball", "").replace("san ", "").strip()
            sim = difflib.SequenceMatcher(None, nm, mn).ratio()
            if sim >= NAME_SIMILARITY or (nm and mn and (nm in mn or mn in nm)):
                dup_of = m
                break
        if dup_of is not None:
            dup_of["_qids"] |= rec["_qids"]
            dup_of.setdefault("_merged", []).append(rec.get("place_id") or rec.get("title"))
            rec["_reason"] = f"trùng với {dup_of.get('title')} ({dup_of.get('place_id')}) cách < {DEDUP_RADIUS_M} m"
            rejected.append(rec)
            continue
        merged.append(rec)
    n_dedup = len(merged)

    # 4) province: address first, then nearest resolved court, then query province
    for rec in merged:
        new, old, src = province_from_address(rec, variants)
        rec["_prov"], rec["_prov_old"], rec["_prov_src"] = new, old, src
    resolved = [r for r in merged if r["_prov"]]
    for rec in merged:
        if rec["_prov"]:
            continue
        p = (rec["latitude"], rec["longtitude"])
        best = min(resolved, key=lambda r: haversine_m(p, (r["latitude"], r["longtitude"])), default=None)
        if best and haversine_m(p, (best["latitude"], best["longtitude"])) <= NEAREST_PROVINCE_KM * 1000:
            rec["_prov"], rec["_prov_src"] = best["_prov"], "nearest"
        else:
            rec["_prov"], rec["_prov_src"] = rec["_query_province"], "query"

    # 5) write
    out_rows = []
    for rec in merged:
        notes = [rec["_note"]] if rec["_note"] else []
        o, c, hnote = parse_hours(rec.get("open_hours"))
        if hnote:
            notes.append(hnote)
        if rec["_prov_src"] == "nearest":
            notes.append("tỉnh suy từ sân gần nhất (địa chỉ không ghi tỉnh)")
        elif rec["_prov_src"] == "query":
            notes.append("tỉnh suy từ truy vấn (địa chỉ không ghi tỉnh)")
        status = norm(rec.get("status"))
        if "tam thoi" in status or "temporarily" in status:
            notes.append("tạm thời đóng cửa")
        site = rec.get("web_site") or ""
        burl = booking_url(rec)
        site, burl = clean_url(site), clean_url(burl)
        if site and site != burl:
            notes.append(f"website: {site}")
        name = normalize_name(rec.get("title") or "")
        if name != (rec.get("title") or ""):
            notes.append(f"tên gốc trên Google: {rec.get('title')}")
        if rec.get("_merged"):
            notes.append("gộp trùng: " + ", ".join(map(str, rec["_merged"])))
        conf = rec["_conf"]
        if rec["_prov_src"] == "query" and conf == "high":
            conf = "medium"
        address = normalize_address(rec.get("address") or "", rec.get("title") or "")
        street = osm_street_prefix(rec, osm, address)
        if street:
            address = f"{street}, {address}" if address else street
            notes.append(f"đường/số nhà suy từ toạ độ (OpenStreetMap), cần kiểm tra: {street}")
        out_rows.append({
            "name": name,
            "address": address,
            "city": rec["_prov"],
            "province_new": rec["_prov"],
            "province_old": rec["_prov_old"],
            "lat": f"{rec['latitude']:.7f}",
            "lng": f"{rec['longtitude']:.7f}",
            "phone": normalize_phone(rec.get("phone")),
            "hours_open": o,
            "hours_close": c,
            "price_per_hour": parse_price(rec),
            "booking_url": burl,
            "google_maps_url": maps_url(rec),
            "rating": f"{float(rec['review_rating']):.1f}" if rec.get("review_rating") else "",
            "rating_count": int(rec["review_count"]) if rec.get("review_count") else "",
            "place_id": rec.get("place_id") or "",
            "category": rec.get("category") or "",
            "retrieved_at": rec["_retrieved_at"],
            "confidence": conf,
            "notes": " | ".join(notes),
        })
    out_rows.sort(key=lambda r: (r["province_new"], r["name"]))

    with open(OUT / "courts-candidates.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out_rows)

    with open(OUT / "loai-bo.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REJECT_COLUMNS)
        w.writeheader()
        for rec in sorted(rejected, key=lambda r: (r["_reason"], r.get("title") or "")):
            w.writerow({
                "name": rec.get("title") or "",
                "address": rec.get("address") or "",
                "category": rec.get("category") or "",
                "categories": "; ".join(rec.get("categories") or []),
                "lat": rec.get("latitude") or "",
                "lng": rec.get("longtitude") or "",
                "place_id": rec.get("place_id") or "",
                "google_maps_url": maps_url(rec),
                "reason": rec["_reason"],
                "query_ids": " ".join(sorted(rec["_qids"])),
            })

    by_prov = collections.Counter(r["province_new"] for r in out_rows)
    stats = {
        "raw_rows": n_raw,
        "unique_place_id": n_unique_pid,
        "after_filter": n_kept,
        "after_dedup": n_dedup,
        "rejected_by_reason": collections.Counter(
            re.sub(r"trùng với .*", "trùng (tên giống, < 150 m)", r["_reason"]) for r in rejected).most_common(),
        "by_province": by_prov.most_common(),
        "confidence": collections.Counter(r["confidence"] for r in out_rows).most_common(),
        "province_source": collections.Counter(r["_prov_src"] for r in merged).most_common(),
        "filled": {c: sum(1 for r in out_rows if r[c] not in ("", None)) for c in COLUMNS},
    }
    (OUT / "clean-stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("raw_rows", "unique_place_id", "after_filter", "after_dedup")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
