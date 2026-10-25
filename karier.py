"""Tracking Loker: lowongan dari situs karier perusahaan.

Dipakai update.py untuk emiten besar BEI dan anak usahanya yang terdaftar di perusahaan.json.
Setiap perusahaan memakai salah satu "platform" di bawah. Kebanyakan perusahaan besar memakai
sistem rekrutmen (ATS) yang sama, jadi satu adapter melayani banyak perusahaan.

  workday          Workday (*.myworkdayjobs.com), API JSON yang dipakai halaman kariernya sendiri
  smartrecruiters  SmartRecruiters, API publik postings
  workable         Workable, API widget publik
  successfactors   SAP SuccessFactors (situs karier RMK), halaman hasil pencarian
  oracle           Oracle Recruiting Cloud, API CandidateExperience
  radancy          Radancy/TalentBrew (mis. careers.unilever.com), halaman lowongan per negara
  jsonld           Situs apa pun yang memasang data JobPosting (schema.org) di halaman lowongannya
  html             Halaman daftar lowongan biasa: judul dari teks tautan, judul kartu, baris tabel, atau
                   halaman detailnya; lokasi dan batas lamaran dari teks di sekitar kartu

Selain itu ada mode cek (python3 update.py --cek) yang memeriksa situs karier semua perusahaan
dan menulis cek-karier.json: platform yang terdeteksi, tautan lowongan, dan hasil uji adapter.
Hasilnya dipakai untuk melengkapi perusahaan.json.

Hanya pustaka standar Python.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

WIB = timezone(timedelta(hours=7))
UA = "Mozilla/5.0 (compatible; TrackingLoker/1.0; +https://github.com/trackingloker/Tracking-Loker)"
MAX_BYTES = 4_000_000
DEFAULT_CAP = 300          # batas lowongan per perusahaan per hari
DETAIL_CAP = 40            # halaman detail baru (jsonld) per perusahaan per hari
DESC_CAP = 120            # deskripsi baru yang diambil per perusahaan per hari (sisanya besok)
DESC_BUDGET_SEC = 6 * 60  # batas waktu mengambil deskripsi per perusahaan
DESC_LIMIT = 8000         # panjang maksimal deskripsi yang disimpan
SUPPORTED = {"workday", "smartrecruiters", "workable", "successfactors", "oracle", "radancy", "jsonld", "html"}


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- jaringan

def _open(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 25):
    """Satu permintaan HTTP. Mengembalikan (status, url_akhir, content_type, isi_bytes)."""
    req = Request(url, data=data, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        **(headers or {}),
    })
    with urlopen(req, timeout=timeout) as res:
        return res.status, res.geturl(), res.headers.get("Content-Type", ""), res.read(MAX_BYTES)


# Diganti di pengujian.
http = _open
sleep = time.sleep


def request(url: str, data: bytes | None = None, headers: dict | None = None, tries: int = 2, timeout: int = 25):
    last: Exception | None = None
    for attempt in range(tries):
        try:
            return http(url, data=data, headers=headers, timeout=timeout)
        except HTTPError as err:
            last = err
            if err.code < 500 and err.code not in (408, 429):
                raise
        except (URLError, TimeoutError, ConnectionError, OSError) as err:
            last = err
        if attempt + 1 < tries:
            sleep(2 + attempt * 3)
    if isinstance(last, HTTPError):
        raise last
    raise RuntimeError(f"{url}: {last}")


def _decode(body: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "")
    try:
        return body.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def get_text(url: str, params: dict | None = None) -> tuple[str, str]:
    """(isi, url_akhir)."""
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    _, final, ctype, body = request(url)
    return _decode(body, ctype), final


def get_json(url: str, params: dict | None = None):
    text, _ = get_text(url, params)
    return json.loads(text)


def post_json(url: str, payload: dict):
    _, _, ctype, body = request(url, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "Accept": "application/json"})
    return json.loads(_decode(body, ctype))


# ---------------------------------------------------------------- bantuan

def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def strip_tags(text: str) -> str:
    return clean(re.sub(r"<[^>]+>", " ", text or ""))


BULAN = {"januari": "January", "februari": "February", "maret": "March", "mei": "May", "juni": "June", "juli": "July",
         "agustus": "August", "oktober": "October", "desember": "December", "agu": "Aug", "agt": "Aug", "okt": "Oct",
         "des": "Dec", "nopember": "November", "pebruari": "February"}


def epoch(value, now: datetime | None = None, fmt: str = "") -> int:
    """Tanggal dalam berbagai bentuk menjadi detik epoch. 0 jika tak terbaca. fmt: format strptime khusus."""
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value / 1000) if value > 10_000_000_000 else int(value)
    text = clean(value)
    text = re.sub(r"\b(" + "|".join(BULAN) + r")\b\.?", lambda m: BULAN[m.group(1).lower()], text, flags=re.I)
    if fmt:
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=WIB).timestamp())
        except ValueError:
            return 0
    now = now or datetime.now(WIB)
    low = text.lower()
    # Workday: "Posted Today", "Posted Yesterday", "Posted 5 Days Ago", "Posted 30+ Days Ago"
    if "today" in low or "hari ini" in low:
        return int(now.timestamp())
    if "yesterday" in low or "kemarin" in low:
        return int((now - timedelta(days=1)).timestamp())
    m = re.search(r"(\d+)\+?\s*(day|hari)", low)
    if m and ("ago" in low or "lalu" in low or "posted" in low):
        return int((now - timedelta(days=int(m.group(1)))).timestamp())
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return int((dt if dt.tzinfo else dt.replace(tzinfo=WIB)).timestamp())
    except ValueError:
        pass
    for form in ("%b %d, %Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%d/%m/%Y", "%Y/%m/%d", "%a, %d %b %Y %H:%M:%S %z",
                 "%a, %d %b %Y %H:%M:%S %Z", "%d-%m-%Y", "%b %Y, %d", "%B %Y, %d", "%d %b, %Y", "%d %B, %Y"):
        try:
            dt = datetime.strptime(text, form)
            return int((dt if dt.tzinfo else dt.replace(tzinfo=WIB)).timestamp())
        except ValueError:
            continue
    return 0


def raw_job(ident, title, link, loc="", posted=0, kind="", function="", expires=0, edu="", smin=0, smax=0, desc="") -> dict:
    return {"id": clean(ident), "title": clean(title), "link": clean(link), "loc": clean(loc), "posted": posted or 0,
            "type": clean(kind), "function": clean(function), "expires": expires or 0, "edu": clean(edu),
            "smin": smin or 0, "smax": smax or 0, "desc": desc or ""}


def html_to_text(markup, limit: int = DESC_LIMIT) -> str:
    """HTML deskripsi lowongan menjadi teks rapi: paragraf dipisah baris kosong, butir daftar diberi •."""
    if not markup:
        return ""
    text = str(markup)
    if "&lt;" in text and "<" not in text.replace("&lt;", ""):
        text = html.unescape(text)  # Greenhouse mengirim HTML yang di-escape
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<li\b[^>]*>", "\n\u2022 ", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|ul|ol|h[1-6]|tr|section|li|table)>|<h[1-6]\b[^>]*>|<p\b[^>]*>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    if LEFTOVER_ENTITY.search(text):
        text = html.unescape(text)  # entitas ganda, mis. "&amp;#xa;" dari Workday Japfa
    return _tidy_lines(text, limit)


LEFTOVER_ENTITY = re.compile(r"&(#x?[0-9a-fA-F]{1,6}|amp|nbsp|lt|gt|quot|apos);")


def _tidy_lines(text: str, limit: int = DESC_LIMIT) -> str:
    """Spasi dirapikan, satu baris kosong antarparagraf, butir daftar diawali •."""
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    bullet = False
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line == "\u2022":
            bullet = True
            continue
        if not line:
            if out and out[-1]:
                out.append("")
            continue
        if bullet and not line.startswith("\u2022"):
            line = "\u2022 " + line
        bullet = False
        if out and out[-1] == "" and line.startswith("\u2022") and len(out) > 1 and out[-2].startswith("\u2022"):
            out.pop()  # butir berurutan tidak dipisah baris kosong
        out.append(line)
    text = "\n".join(out).strip()
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0].rstrip() + "\n\u2026"
    return text


# ---------------------------------------------------------------- label fresh graduate / management trainee

TAG_FRESH = 1      # terbuka untuk fresh graduate / tanpa pengalaman, menurut judul, deskripsi, atau kualifikasinya
TAG_MT = 2         # program Management Trainee / ODP / sejenisnya
TAG_CHECKED = 4    # deskripsinya sudah diperiksa (lowongan tanpa label pun ditandai supaya tidak diperiksa ulang)
TAG_NATIONAL = 8   # penempatan di seluruh Indonesia (lokasinya memang tidak satu kota/provinsi)
NATIONWIDE = re.compile(
    r"seluruh (wilayah |kota di |daerah di |cabang di )?indonesia|se-?indonesia|seluruh (wilayah|cabang|area) (kerja|operasional)?|"
    r"wilayah operasional|nationwide|all over indonesia|across indonesia|berbagai (kota|wilayah|daerah|provinsi)|"
    r"(penempatan|lokasi)[^.\n]{0,20}\bnasional\b", re.I)
INTERN_TITLE = re.compile(r"intern(ship)?|magang|\bpkl\b|praktik kerja|kerja praktek", re.I)

FRESH_SAYS = re.compile(
    r"fresh ?grad|lulusan baru|baru lulus|baru saja lulus|tanpa pengalaman|belum (memiliki |punya |ada )?pengalaman|"
    r"tidak (harus|wajib|perlu|diwajibkan|disyaratkan|membutuhkan) (memiliki |punya )?(pengalaman|berpengalaman)|"
    r"pengalaman (kerja )?(tidak (wajib|harus|diperlukan|disyaratkan|dibutuhkan)|bukan syarat)|"
    r"(tidak|non) berpengalaman (dipersilakan|boleh|bisa|diterima)|berpengalaman (atau|maupun|/) (tidak|belum)|"
    r"no (prior |previous |work )?experiences? (is )?(required|needed|necessary)|experience (is )?not (required|necessary)|"
    r"entry[ -]level|new graduates?|recent graduates?|(?<![\d.,])0\s*(?:[-\u2013]\s*\d+\s*)?(tahun|thn|years?)|"
    r"(terbuka|dibuka|cocok|welcome) (untuk|bagi|for) (fresh|lulusan|pemula|para lulusan)", re.I)
# Judul yang jelas bukan untuk lulusan baru, kecuali judulnya sendiri menyebut fresh graduate.
SENIOR_TITLE = re.compile(
    r"\b(manager|manajer|head|kepala|lead|leader|senior|sr\.?|supervisor|spv|superintendent|koordinator|coordinator|"
    r"director|direktur|chief|vp|avp|gm|general manager|principal|expert|ahli madya|ahli utama)\b", re.I)
MT_TITLE = re.compile(
    r"management trainee|(?<![a-z])mt(?![a-z])|(?<![a-z])odp(?![a-z])|officer development|management development program|"
    r"(?<![a-z])(mdp|gdp|cdp|bdp|ldp)(?![a-z])|graduate (trainee|development|management) program|leadership development program|"
    r"future leaders? program|young leaders? program|program pengembangan (calon )?(pemimpin|staf|karyawan)|"
    r"(?<![a-z])(pcpm|pps|pkp) (bri|bni)|staff development program|ikatan dinas", re.I)
MT_TEXT = re.compile(
    r"program management trainee|management trainee program|(program|batch) (mt|odp)\b|officer development program|"
    r"management development program|graduate development program|leadership development program", re.I)


NEEDS_EXP = re.compile(
    r"(pengalaman|berpengalaman|experience)[^.\n]{0,40}?(minimal|min\.?|minimum|at least|lebih dari|sekurang[- ]kurangnya)\s*"
    r"([1-9]|satu|dua|tiga)|(minimal|min\.?|minimum|at least)\s*([1-9]\d?)\s*\+?\s*(tahun|thn|years?)|"
    r"(?<![\d.,])([1-9]\d?)\s*\+?\s*(tahun|thn|years?) (pengalaman|of experience|experience|berpengalaman)", re.I)


def needs_experience(text: str) -> bool:
    """Deskripsi mensyaratkan pengalaman minimal 1 tahun atau lebih."""
    return bool(NEEDS_EXP.search(text or ""))


def is_senior(title: str) -> bool:
    return bool(SENIOR_TITLE.search(title or ""))


def job_tags(title: str, text: str = "", function: str = "", categories: str = "") -> int:
    """Label lowongan dari judul, deskripsi, dan kualifikasinya (bukan tebakan dari judul saja).

    Fresh graduate: judul atau isinya menyebut terbuka untuk lulusan baru / tanpa pengalaman / pengalaman 0 tahun,
    atau bidangnya di sumber "Fresh Graduate", atau kategorinya Fresh Graduate tanpa syarat pengalaman minimal.
    Judul senior (manager, supervisor, kepala, dst.) tidak ikut kecuali judulnya sendiri menyebut fresh graduate.
    Management trainee: judulnya program MT/ODP/sejenis, bidangnya "Management Trainee", atau isinya menjelaskan
    program itu dan judulnya bukan posisi senior.
    """
    title = title or ""
    body = text or ""
    tags = TAG_CHECKED
    senior = is_senior(title)
    needs_exp = needs_experience(body)
    if FRESH_SAYS.search(title) or (not senior and (FRESH_SAYS.search(body) or function == "Fresh Graduate"
                                                     or (re.search(r"fresh ?grad", categories, re.I) and not needs_exp))):
        tags |= TAG_FRESH
    # Kategori MT dari situs pengumpul berlaku untuk satu artikel; posisi magang di dalamnya bukan program MT.
    from_category = bool(re.search(r"(?<![a-z])(mt|odp)(?![a-z])|management trainee", categories, re.I)) \
        and not INTERN_TITLE.search(title)
    if not senior and (MT_TITLE.search(title) or function == "Management Trainee" or MT_TEXT.search(body) or from_category):
        tags |= TAG_MT
    return tags


def _is_heading(line: str) -> bool:
    line = line.strip()
    return len(line) <= 45 and not line.startswith("\u2022") and not re.search(r"[.;!?]\s*$|[.;!?]\s", line)


def tidy_desc(text: str) -> str:
    """Deskripsi siap tampil. Sisa entitas HTML dibersihkan, dan deskripsi yang hanya berisi judul bagian
    tanpa isi (mis. "Job Summary / Education / Certification" di beberapa lowongan Petrosea) dianggap kosong."""
    text = (text or "").strip()
    if not text:
        return ""
    if LEFTOVER_ENTITY.search(text):
        text = _tidy_lines(html.unescape(text))
    lines = [line for line in text.split("\n") if line.strip()]
    skeleton = len(lines) >= 3 and all(_is_heading(line) for line in lines)
    return "" if skeleton else text


TYPE_NAMES = {
    "full time": "Full time", "full-time": "Full time", "fulltime": "Full time", "permanent": "Full time",
    "regular": "Full time", "pkwtt": "Full time", "tetap": "Full time", "karyawan tetap": "Full time",
    "contract": "Kontrak", "kontrak": "Kontrak", "direct contract": "Kontrak", "fixed term": "Kontrak",
    "fixed-term": "Kontrak", "temporary": "Kontrak", "pkwt": "Kontrak", "contractor": "Kontrak",
    "internship": "Magang", "intern": "Magang", "magang": "Magang", "trainee": "Magang",
    "part time": "Part time", "part-time": "Part time", "parttime": "Part time", "freelance": "Freelance",
}


def norm_type(name) -> str:
    name = clean(name)
    return TYPE_NAMES.get(name.lower().replace("_", " "), name)


def cap_of(company: dict) -> int:
    try:
        return int(company.get("maks") or DEFAULT_CAP)
    except (TypeError, ValueError):
        return DEFAULT_CAP


# ---------------------------------------------------------------- lokasi

PROVINCE_EN = {
    "west java": "Jawa Barat", "central java": "Jawa Tengah", "east java": "Jawa Timur", "north sumatra": "Sumatera Utara",
    "north sumatera": "Sumatera Utara", "south sumatra": "Sumatera Selatan", "south sumatera": "Sumatera Selatan",
    "west sumatra": "Sumatera Barat", "west sumatera": "Sumatera Barat", "riau islands": "Kepulauan Riau",
    "bangka belitung": "Kepulauan Bangka Belitung", "west kalimantan": "Kalimantan Barat",
    "central kalimantan": "Kalimantan Tengah", "south kalimantan": "Kalimantan Selatan", "east kalimantan": "Kalimantan Timur",
    "north kalimantan": "Kalimantan Utara", "north sulawesi": "Sulawesi Utara", "central sulawesi": "Sulawesi Tengah",
    "south sulawesi": "Sulawesi Selatan", "southeast sulawesi": "Sulawesi Tenggara", "south east sulawesi": "Sulawesi Tenggara",
    "west sulawesi": "Sulawesi Barat", "west nusa tenggara": "Nusa Tenggara Barat", "east nusa tenggara": "Nusa Tenggara Timur",
    "special region of yogyakarta": "Daerah Istimewa Yogyakarta", "di yogyakarta": "Daerah Istimewa Yogyakarta",
    "north maluku": "Maluku Utara", "west papua": "Papua Barat", "jakarta raya": "DKI Jakarta", "dki jakarta": "DKI Jakarta",
    "jabodetabek": "DKI Jakarta",
}
# kata kunci -> (kota sesuai daftar Karirhub, provinsi)
CITY_ALIASES = {
    "south jakarta": ("Kota Adm. Jakarta Selatan", "DKI Jakarta"), "jakarta selatan": ("Kota Adm. Jakarta Selatan", "DKI Jakarta"),
    "central jakarta": ("Kota Adm. Jakarta Pusat", "DKI Jakarta"), "jakarta pusat": ("Kota Adm. Jakarta Pusat", "DKI Jakarta"),
    "west jakarta": ("Kota Adm. Jakarta Barat", "DKI Jakarta"), "jakarta barat": ("Kota Adm. Jakarta Barat", "DKI Jakarta"),
    "east jakarta": ("Kota Adm. Jakarta Timur", "DKI Jakarta"), "jakarta timur": ("Kota Adm. Jakarta Timur", "DKI Jakarta"),
    "north jakarta": ("Kota Adm. Jakarta Utara", "DKI Jakarta"), "jakarta utara": ("Kota Adm. Jakarta Utara", "DKI Jakarta"),
    "jakarta": ("Jakarta", "DKI Jakarta"),
    "bsd": ("Kota Tangerang Selatan", "Banten"), "serpong": ("Kota Tangerang Selatan", "Banten"),
    "south tangerang": ("Kota Tangerang Selatan", "Banten"), "tangerang selatan": ("Kota Tangerang Selatan", "Banten"),
    "tangerang": ("Kota Tangerang", "Banten"), "cikarang": ("Kab. Bekasi", "Jawa Barat"), "bekasi": ("Kota Bekasi", "Jawa Barat"),
    "karawang": ("Kab. Karawang", "Jawa Barat"), "cilegon": ("Kota Cilegon", "Banten"), "serang": ("Kota Serang", "Banten"),
    "depok": ("Kota Depok", "Jawa Barat"), "bogor": ("Kota Bogor", "Jawa Barat"), "bandung": ("Kota Bandung", "Jawa Barat"),
    "cirebon": ("Kota Cirebon", "Jawa Barat"), "surabaya": ("Kota Surabaya", "Jawa Timur"), "gresik": ("Kab. Gresik", "Jawa Timur"),
    "sidoarjo": ("Kab. Sidoarjo", "Jawa Timur"), "pasuruan": ("Kab. Pasuruan", "Jawa Timur"), "malang": ("Kota Malang", "Jawa Timur"),
    "kediri": ("Kota Kediri", "Jawa Timur"), "semarang": ("Kota Semarang", "Jawa Tengah"), "solo": ("Kota Surakarta", "Jawa Tengah"),
    "surakarta": ("Kota Surakarta", "Jawa Tengah"), "kudus": ("Kab. Kudus", "Jawa Tengah"),
    "yogyakarta": ("Kota Yogyakarta", "Daerah Istimewa Yogyakarta"), "jogja": ("Kota Yogyakarta", "Daerah Istimewa Yogyakarta"),
    "denpasar": ("Kota Denpasar", "Bali"), "medan": ("Kota Medan", "Sumatera Utara"), "batam": ("Kota Batam", "Kepulauan Riau"),
    "palembang": ("Kota Palembang", "Sumatera Selatan"), "pekanbaru": ("Kota Pekanbaru", "Riau"), "padang": ("Kota Padang", "Sumatera Barat"),
    "lampung": ("Kota Bandar Lampung", "Lampung"), "jambi": ("Kota Jambi", "Jambi"), "makassar": ("Kota Makassar", "Sulawesi Selatan"),
    "manado": ("Kota Manado", "Sulawesi Utara"), "kendari": ("Kota Kendari", "Sulawesi Tenggara"),
    "morowali": ("Kab. Morowali", "Sulawesi Tengah"), "sorowako": ("Kab. Luwu Timur", "Sulawesi Selatan"),
    "east luwu": ("Kab. Luwu Timur", "Sulawesi Selatan"), "luwu timur": ("Kab. Luwu Timur", "Sulawesi Selatan"),
    "balikpapan": ("Kota Balikpapan", "Kalimantan Timur"), "samarinda": ("Kota Samarinda", "Kalimantan Timur"),
    "banjarmasin": ("Kota Banjarmasin", "Kalimantan Selatan"), "pontianak": ("Kota Pontianak", "Kalimantan Barat"),
    "tabalong": ("Kab. Tabalong", "Kalimantan Selatan"), "sumbawa": ("Kab. Sumbawa Barat", "Nusa Tenggara Barat"),
    "mataram": ("Kota Mataram", "Nusa Tenggara Barat"), "kupang": ("Kota Kupang", "Nusa Tenggara Timur"),
    "timika": ("Kab. Mimika", "Papua Tengah"), "jayapura": ("Kota Jayapura", "Papua"), "ambon": ("Kota Ambon", "Maluku"),
    "halmahera": ("Kab. Halmahera Selatan", "Maluku Utara"),
}
FOREIGN = re.compile(r"\b(singapore|malaysia|kuala lumpur|thailand|bangkok|vietnam|philippines|manila|india|china|japan|"
                     r"australia|united states|usa|united kingdom|london|hong kong|taiwan|korea|netherlands|germany|"
                     r"switzerland|dubai|uae|brazil|mexico|canada|france|spain|italy|poland)\b")
_index_cache: dict[int, list] = {}
# Nama kota/kabupaten yang juga kata sehari-hari ("Kotabaru" → "baru", "Kota Batu" → "batu bara").
AMBIGUOUS = {"baru", "batu", "bone", "buru", "pati", "raya", "jaya", "ende", "sigi", "muna", "alor", "kaur", "bima"}


def _city_index(refs: dict) -> list:
    """[(kunci, nama_kota, provinsi)] dari daftar kota Karirhub, kunci terpanjang dulu."""
    key = id(refs)
    if key in _index_cache:
        return _index_cache[key]
    provinces = refs.get("provinces") or {}
    seen: dict[str, tuple[str, str]] = {}
    for name, pid in (refs.get("cities") or {}).values():
        base = re.sub(r"^(kota adm\.|kota administrasi|kota|kabupaten|kab\.)\s+", "", name.lower()).strip()
        if len(base) < 4 or base in AMBIGUOUS:
            continue
        # Nama yang sama untuk kota dan kabupaten: kota didahulukan.
        if base not in seen or name.lower().startswith("kota"):
            seen[base] = (name, provinces.get(pid, ""))
    index = sorted(((k, *v) for k, v in seen.items()), key=lambda x: -len(x[0]))
    _index_cache[key] = index
    return index


def place(text: str, refs: dict | None = None, strict: bool = False) -> tuple[str, str] | None:
    """(kota, provinsi) dari teks lokasi bebas.

    Bila ada beberapa nama tempat, yang paling awal di teks dipakai (teks disusun dari yang paling dekat
    dengan judul lowongan). None bila lokasinya jelas di luar Indonesia. strict=True (perusahaan
    multinasional) juga menolak lokasi yang tidak dikenali sama sekali.
    """
    refs = refs or {}
    low = " " + clean(text).lower() + " "
    if not low.strip():
        return None if strict else ("", "")
    provinces = refs.get("provinces") or {}
    found = []  # (posisi, prioritas, -panjang, kota, provinsi)
    # Nama lengkap "Kabupaten X" / "Kab. X" / "Kota X" paling tepat, jadi tidak tertukar kabupaten dengan kotanya.
    for name, pid in (refs.get("cities") or {}).values():
        n = name.lower()
        for v in {n, n.replace("kab. ", "kabupaten "), n.replace("kota adm. ", "kota ")}:
            i = low.find(v)
            if len(v) > 8 and i != -1:
                found.append((i, 0, -len(v), name, provinces.get(pid, "")))
    for key, value in CITY_ALIASES.items():
        m = re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", low)
        if m:
            found.append((m.start(), 1, -len(key), *value))
    for key, name, prov in _city_index(refs):
        m = re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", low)
        if m:
            found.append((m.start(), 2, -len(key), name, prov))
    if found:
        best = min(found, key=lambda x: (x[0], x[2], x[1]))
        return best[3], best[4]
    prov_names = {p.lower(): p for p in provinces.values()}
    hits = []
    for key in {**prov_names, **PROVINCE_EN}:
        m = re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", low)
        if m:
            hits.append((m.start(), -len(key), PROVINCE_EN.get(key) or prov_names[key]))
    for key in ("bali", "banten", "aceh", "riau", "papua", "maluku", "gorontalo", "bengkulu"):
        m = re.search(rf"(?<![a-z]){key}(?![a-z])", low)
        if m:
            hits.append((m.start(), -len(key), key.title()))
    if hits:
        return "", min(hits)[2]
    if re.search(r"indonesia|\bidn\b|, id\b|\(id\)", low):
        return "", ""
    if FOREIGN.search(low) or strict:
        return None
    return "", ""


# ---------------------------------------------------------------- adapter

def workday(company: dict, now: datetime | None = None) -> list[dict]:
    """company.url: https://{tenant}.wdN.myworkdayjobs.com/[locale/]{site}"""
    parts = urlsplit(company["url"])
    host = parts.netloc
    tenant = host.split(".")[0]
    segs = [s for s in parts.path.split("/") if s]
    site = next((s for s in segs if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", s)), "")
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": company.get("cari", "")}
    first = post_json(api, body)
    facet = _workday_country(first.get("facets") or [])
    filtered = bool(facet)
    if facet:
        body["appliedFacets"] = {facet[0]: [facet[1]]}
        first = post_json(api, body)
    total = int(first.get("total") or 0)
    posts = list(first.get("jobPostings") or [])
    cap = cap_of(company)
    while len(posts) < min(total, cap):
        body["offset"] = len(posts)
        sleep(0.3)
        page = post_json(api, body).get("jobPostings") or []
        if not page:
            break
        posts += page
    out = []
    for p in posts[:cap]:
        path = p.get("externalPath") or ""
        loc = p.get("locationsText") or ""
        if filtered and re.fullmatch(r"\d+ (locations|lokasi)", loc.strip().lower()):
            loc = "Indonesia"
        ident = (p.get("bulletFields") or [path.rsplit("_", 1)[-1]])[0]
        out.append(raw_job(ident, p.get("title"), f"https://{host}/{site}{path}", loc, epoch(p.get("postedOn"), now)))
    return out


def _workday_country(facets: list) -> tuple[str, str] | None:
    """Cari nilai filter 'Indonesia' pada facet negara/lokasi Workday."""
    found = []

    def walk(items, param=""):
        for f in items or []:
            p = f.get("facetParameter") or param
            for v in f.get("values") or []:
                if v.get("facetParameter"):
                    walk([v], p)
                elif re.search(r"\bindonesia\b", str(v.get("descriptor") or ""), re.I) and v.get("id"):
                    found.append((v.get("facetParameter") or p, v["id"]))
    walk(facets)
    found.sort(key=lambda x: 0 if "ountry" in x[0] else 1)
    return found[0] if found else None


def smartrecruiters(company: dict, now=None) -> list[dict]:
    slug = company["slug"]
    out, offset, cap = [], 0, cap_of(company)
    while offset < cap:
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                        {"limit": 100, "offset": offset, "country": "id"})
        rows = data.get("content") or []
        for p in rows:
            loc = p.get("location") or {}
            text = loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
            if str(loc.get("country") or "").lower() == "id" and "indonesia" not in text.lower():
                text += ", Indonesia"
            out.append(raw_job(
                p.get("id"), p.get("name"), f"https://jobs.smartrecruiters.com/{slug}/{p.get('id')}", text,
                epoch(p.get("releasedDate")), (p.get("typeOfEmployment") or {}).get("label", ""),
                (p.get("function") or {}).get("label") or (p.get("department") or {}).get("label", "")))
        offset += 100
        if not rows or offset >= int(data.get("totalFound") or 0):
            break
        sleep(0.3)
    return out[:cap]


def workable(company: dict, now=None) -> list[dict]:
    slug = company["slug"]
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", {"details": "true"})
    out = []
    for j in data.get("jobs") or []:
        locs = j.get("locations") or [{"city": j.get("city"), "region": j.get("state"), "country": j.get("country")}]
        text = "; ".join(", ".join(filter(None, [l.get("city"), l.get("region"), l.get("country")])) for l in locs)
        code = j.get("shortcode") or j.get("code") or j.get("id")
        out.append(raw_job(code, j.get("title"), j.get("url") or f"https://apply.workable.com/{slug}/j/{code}/", text,
                           epoch(j.get("published_on") or j.get("created_at")), j.get("employment_type", ""),
                           j.get("function") or j.get("department") or "", edu=j.get("education", ""),
                           desc=html_to_text("".join(j.get(k) or "" for k in ("description", "requirements", "benefits")))))
    return out[:cap_of(company)]


SF_ROW = re.compile(r'<tr[^>]*class="[^"]*data-row[^"]*"[^>]*>(.*?)</tr>', re.S)


def successfactors(company: dict, now=None, known: dict | None = None) -> list[dict]:
    """Situs karier SuccessFactors RMK: halaman /search/ (25 baris per halaman).

    Bila tabel hasil pencarian tak terbaca, daftar diambil dari sitemap.xml dan isinya dari halaman detail
    (judul dan lokasi ditandai microdata itemprop di situs RMK).
    """
    base = company["url"].rstrip("/")
    out, start, cap = [], 0, cap_of(company)
    while start < cap:
        page, _ = get_text(f"{base}/search/", {"q": "", "locationsearch": company.get("lokasi", "Indonesia"),
                                                "startrow": start})
        rows = SF_ROW.findall(page)
        for row in rows:
            a = re.search(r'<a[^>]*class="[^"]*jobTitle-link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', row, re.S)
            if not a:
                continue
            href = urljoin(base + "/", html.unescape(a.group(1)))
            loc = re.search(r'class="[^"]*jobLocation[^"]*"[^>]*>(.*?)</span>', row, re.S)
            date = re.search(r'class="[^"]*jobDate[^"]*"[^>]*>(.*?)</span>', row, re.S)
            ident = re.search(r"/(\d+)/?$", href)
            out.append(raw_job(ident.group(1) if ident else href, strip_tags(a.group(2)), href,
                               strip_tags(loc.group(1)) if loc else "", epoch(strip_tags(date.group(1)) if date else "")))
        if len(rows) < 10:
            break
        start += len(rows)
        sleep(0.4)
    if not out:
        out = _sf_sitemap(base, company, known or {})
    seen, uniq = set(), []
    for j in out:
        if j["id"] not in seen:
            seen.add(j["id"])
            uniq.append(j)
    return uniq[:cap]


def _sf_sitemap(base: str, company: dict, known: dict) -> list[dict]:
    text, _ = get_text(base + "/sitemap.xml")
    links = [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text) if re.search(r"/job/[^/]+/\d+/?$", u)]
    out, fresh = [], 0
    for link in links[:cap_of(company)]:
        ident = re.search(r"/(\d+)/?$", link).group(1)
        if link in known:
            old = known[link]
            out.append(raw_job(ident, old["title"], link, f"{old.get('city', '')} {old.get('province', '')}", old.get("posted", 0)))
            continue
        if fresh >= int(company.get("detail") or DETAIL_CAP):
            continue
        fresh += 1
        try:
            page, _ = get_text(link)
        except Exception:  # noqa: BLE001
            continue
        prop = lambda name: re.search(rf'itemprop=["\']{name}["\'][^>]*?(?:content=["\']([^"\']+)["\'][^>]*>|>(.*?)</)', page, re.S)  # noqa: E731
        title = prop("title")
        title = strip_tags(title.group(1) or title.group(2)) if title else ""
        if not title:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
            title = strip_tags(m.group(1)) if m else ""
        where = prop("addressLocality") or prop("jobLocation")
        posted = prop("datePosted")
        slug = link.split("/job/")[1].split("/")[0].replace("-", " ")
        out.append(raw_job(ident, title, link, strip_tags((where.group(1) or where.group(2)) if where else slug),
                           epoch((posted.group(1) or posted.group(2)) if posted else "")))
        sleep(0.3)
    return [j for j in out if j["title"]]


def oracle(company: dict, now=None) -> list[dict]:
    """company.url: https://{host}/hcmUI/CandidateExperience/en/sites/{site}"""
    parts = urlsplit(company["url"])
    m = re.search(r"/sites/([^/?#]+)", parts.path)
    site = m.group(1) if m else "CX_1"
    host = parts.netloc
    out, offset, cap = [], 0, cap_of(company)
    while offset < cap:
        finder = (f"findReqs;siteNumber={site},facetsList=LOCATIONS,limit=25,offset={offset},"
                  f"sortBy=POSTING_DATES_DESC")
        data = get_json(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                        {"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder})
        item = (data.get("items") or [{}])[0]
        rows = item.get("requisitionList") or []
        for r in rows:
            loc = ", ".join(filter(None, [r.get("PrimaryLocation"), r.get("PrimaryLocationCountry")]))
            if str(r.get("PrimaryLocationCountry") or "").upper() == "ID":
                loc += ", Indonesia"
            out.append(raw_job(r.get("Id"), r.get("Title"),
                               f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{r.get('Id')}",
                               loc, epoch(r.get("PostedDate")), r.get("WorkplaceType") or "",
                               r.get("JobFamily") or r.get("Organization") or ""))
        offset += 25
        if not rows or offset >= int(item.get("TotalJobsCount") or 0):
            break
        sleep(0.3)
    return out[:cap]


TB_LINK = re.compile(r'<a[^>]+href="((?:https?://[^"/]+)?(?:/[a-z]{2}(?:-[a-z]{2})?)?/job/[^"]+/\d+/\d+)"[^>]*>(.*?)</a>',
                     re.S | re.I)


def radancy(company: dict, now=None) -> list[dict]:
    """Radancy/TalentBrew. company.url: halaman lowongan negara, mis. .../location/indonesia-jobs/34155/1643084/2"""
    base = company["url"].split("?")[0]
    out, seen, cap = [], set(), cap_of(company)
    for page_no in range(1, 30):
        page, _ = get_text(base, {"p": page_no} if page_no > 1 else None)
        found = 0
        for href, inner in TB_LINK.findall(page):
            link = urljoin(base, href)
            ident = href.rstrip("/").rsplit("/", 1)[-1]
            if ident in seen:
                continue
            seen.add(ident)
            found += 1
            title = re.search(r"<h[23][^>]*>(.*?)</h[23]>", inner, re.S)
            loc = re.search(r'class="[^"]*job-location[^"]*"[^>]*>(.*?)</', inner, re.S)
            date = re.search(r'class="[^"]*job-date[^"]*"[^>]*>(.*?)</', inner, re.S)
            city_from_url = href.split("/job/")[1].split("/")[0].replace("-", " ")
            out.append(raw_job(ident, strip_tags(title.group(1) if title else inner), link,
                               strip_tags(loc.group(1)) if loc else city_from_url,
                               epoch(strip_tags(date.group(1)) if date else "")))
        if not found or len(out) >= cap:
            break
        sleep(0.4)
    return out[:cap]


JSONLD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
JOB_LINK = r"/(job|jobs|lowongan|vacanc|career|careers|karir|karier|loker|posisi|position)s?/[^\"'#\s<>]+"


def jobpostings(page: str) -> list[dict]:
    """Semua objek schema.org JobPosting di halaman."""
    found = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            kind = node.get("@type")
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                found.append(node)
            for key in ("@graph", "itemListElement", "item", "mainEntity"):
                if key in node:
                    walk(node[key])
    for block in JSONLD.findall(page):
        try:
            walk(json.loads(html.unescape(block.strip()).replace("\n", " ")))
        except ValueError:
            continue
    return found


def from_jsonld(node: dict, link: str) -> dict:
    locs = node.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    parts = []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, str):
            parts.append(addr)
            continue
        country = addr.get("addressCountry")
        country = country.get("name") if isinstance(country, dict) else country
        parts.append(", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), country])))
    if not parts and node.get("jobLocationType") == "TELECOMMUTE":
        parts.append("Remote, Indonesia")
    pay = node.get("baseSalary") or {}
    value = pay.get("value") if isinstance(pay, dict) else {}
    value = value if isinstance(value, dict) else {"value": value}
    lo = hi = 0
    if isinstance(pay, dict) and str(pay.get("currency") or value.get("currency") or "IDR").upper() == "IDR" \
            and str(value.get("unitText") or "MONTH").upper() == "MONTH":
        try:
            lo = int(float(value.get("minValue") or value.get("value") or 0))
            hi = int(float(value.get("maxValue") or 0))
        except (TypeError, ValueError):
            lo = hi = 0
    edu = node.get("educationRequirements") or ""
    if isinstance(edu, dict):
        edu = edu.get("credentialCategory") or ""
    kind = node.get("employmentType") or ""
    kind = kind[0] if isinstance(kind, list) and kind else kind
    ident = node.get("identifier") or ""
    ident = ident.get("value") if isinstance(ident, dict) else ident
    return raw_job(ident or link, node.get("title"), node.get("url") or link, "; ".join(parts),
                   epoch(node.get("datePosted")), str(kind).replace("_", " ").title(),
                   node.get("occupationalCategory") or "", epoch(node.get("validThrough")), str(edu), lo, hi,
                   desc=html_to_text(node.get("description") or ""))


def job_links(page: str, base: str, pattern: str) -> list[str]:
    links, seen = [], set()
    if page.lstrip().startswith("<?xml") or "<urlset" in page[:500]:
        candidates = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", page)
    else:
        candidates = [urljoin(base, html.unescape(h)) for h in re.findall(r'href=["\']([^"\']+)["\']', page)]
    host = urlsplit(base).netloc.split(":")[0].removeprefix("www.")
    for url in candidates:
        url = url.split("#")[0]
        if url in seen or not re.search(pattern, url, re.I):
            continue
        if host not in urlsplit(url).netloc and not re.search(r"(workday|smartrecruiters|successfactors)", url):
            continue
        if url.rstrip("/") == base.rstrip("/"):
            continue
        seen.add(url)
        links.append(url)
    return links


def jsonld(company: dict, now=None, known: dict | None = None) -> list[dict]:
    """Daftar lowongan dari halaman daftar/sitemap, isi dari JobPosting di halaman detail.

    known: {tautan: lowongan_kemarin} supaya halaman detail yang sudah pernah dibaca tidak diambil ulang.
    """
    known = known or {}
    page, final = get_text(company["url"])
    nodes = jobpostings(page)
    out = [from_jsonld(n, final) for n in nodes]
    links = job_links(page, final, company.get("pola") or JOB_LINK)
    cap = cap_of(company)
    fresh = 0
    for link in links[:cap]:
        if link in known:
            out.append({**known[link], "_keep": True})
            continue
        if fresh >= int(company.get("detail") or DETAIL_CAP):
            continue
        fresh += 1
        try:
            detail, url = get_text(link)
        except Exception:  # noqa: BLE001
            continue
        found = jobpostings(detail)
        if found:
            out.extend(from_jsonld(n, url) for n in found[:1])
        elif company.get("tanpa_jsonld"):
            title = re.search(r"<h1[^>]*>(.*?)</h1>", detail, re.S) or re.search(r"<title>(.*?)</title>", detail, re.S)
            if title:
                out.append(raw_job(link, strip_tags(title.group(1)), link, company.get("kota", "")))
        sleep(0.3)
    seen, uniq = set(), []
    for j in out:
        if j["title"] and j["link"] not in seen:
            seen.add(j["link"])
            uniq.append(j)
    return uniq


GENERIC = re.compile(
    r"^(apply( now| here| di sini)?|lamar( sekarang)?|daftar( sekarang)?|ajukan( sekarang)?|kirim lamaran|"
    r"lihat( detail| lowongan| selengkapnya| posisi)?|detail( job| pekerjaan| lowongan| posisi)?( vacancy)?|"
    r"detil pekerjaan|selengkapnya|learn more|read more|more|view( job| details?)?|see (more|details?|vacancies)|"
    r"klik( di ?sini)?( untuk (melamar|mendaftar|daftar|apply))?|click here( to apply)?|info(rmasi)? lengkap|job details?|"
    r"details?|requirements?:?|kualifikasi:?|persyaratan:?|>+|»|→|\W*)$", re.I)
DEADLINE = re.compile(
    r"(lamar sebelum|batas(?: akhir)?(?: waktu)?(?: pendaftaran| lamaran| melamar)?|deadline|closing date|close date|"
    r"berakhir(?: pada)?|ditutup(?: pada)?|apply before|valid until|until|hingga|s\.?d\.?)\s*:?\s*"
    r"(\d{1,2}[ /.-][A-Za-z0-9]{2,9}[ /.,-]*\d{4}|[A-Za-z]{3,9}\.? \d{4},? \d{1,2}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4})", re.I)
ANCHOR = re.compile(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
SOCIAL = re.compile(r"(facebook|instagram|twitter|x\.com|linkedin|youtube|tiktok|wa\.me|whatsapp|mailto:|\.(jpe?g|png|webp|svg)(\?|$))", re.I)


def _title_near(block: str, row: str) -> str:
    """Judul kartu lowongan dari HTML di sekitar tautan: baris tabel, judul (h1-h6), atau elemen berkelas judul."""
    if row:
        for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I):
            text = strip_tags(cell)
            if 3 <= len(text) <= 150 and not GENERIC.match(text) and not re.fullmatch(r"[\d\s./-]+", text):
                return text
    heads = re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", block, re.S | re.I)
    for text in map(strip_tags, reversed(heads)):
        if 3 <= len(text) <= 150 and not GENERIC.match(text):
            return text
    for m in reversed(list(re.finditer(
            r'class=["\'][^"\']*(?:title|judul|position|posisi|job-?name|vacancy|lowongan)[^"\']*["\'][^>]*>(.*?)</',
            block, re.S | re.I))):
        text = strip_tags(m.group(1))
        if 3 <= len(text) <= 150 and not GENERIC.match(text):
            return text
    for text in map(strip_tags, reversed(re.findall(r"<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>", block, re.S | re.I))):
        if 3 <= len(text) <= 150 and not GENERIC.match(text):
            return text
    return ""


def cards(page: str, final: str, company: dict) -> list[dict]:
    """Kartu lowongan dari satu halaman daftar (tanpa membuka halaman detail).

    Lowongan tanpa judul yang jelas dikembalikan dengan judul kosong dan _detail=True.
    """
    pattern = company.get("pola") or JOB_LINK
    rx = re.compile(company["judul_regex"], re.I | re.S) if company.get("judul_regex") else None
    drop = re.compile(company["buang"], re.I) if company.get("buang") else None
    hits: list[tuple] = []
    texts: dict[str, list] = {}
    for m in ANCHOR.finditer(page):
        href = urljoin(final, html.unescape(m.group(1).strip())).split("#")[0]
        if not re.search(pattern, href, re.I) or SOCIAL.search(href) or href.rstrip("/") == final.rstrip("/"):
            continue
        if href not in texts:
            texts[href] = []
            hits.append((href, m.start(), m.end()))
        texts[href].append(strip_tags(m.group(2)))
    out = []
    for i, (href, start, end) in enumerate(hits):
        prev_end = hits[i - 1][2] if i else 0
        next_start = hits[i + 1][1] if i + 1 < len(hits) else len(page)
        block = page[max(prev_end, start - 3000):start]
        after = page[end:min(next_start, end + 700)]
        row = ""
        tr = block.lower().rfind("<tr")
        if tr != -1 and block.lower().rfind("</tr>") < tr:
            close = page.lower().find("</tr>", end)
            row = block[tr:] + page[start:close if close != -1 else end]
        context = strip_tags(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", block[-1500:] + " " + after, flags=re.S | re.I))
        anchor = max(texts[href], key=len)
        title, loc, date = "", "", ""
        if rx:
            m = rx.search(anchor) or rx.search(context)
            if m:
                found = m.groupdict()
                title, loc, date = found.get("title") or "", found.get("loc") or "", found.get("date") or ""
        if not title and 4 <= len(anchor) <= 150 and not GENERIC.match(anchor):
            title = anchor
        if not title:
            title = _title_near(block, row)
        if drop and (drop.search(title) or drop.search(context[-400:])):
            continue
        deadline = DEADLINE.search(context)
        ident = re.sub(r"[^A-Za-z0-9_-]+", "-", urlsplit(href).path.strip("/").split("/")[-1] or href)[-40:].strip("-")
        out.append({**raw_job(ident or hashlib.md5(href.encode()).hexdigest()[:12], title, href,
                              loc or company.get("kota") or (f"{title} {strip_tags(row)}" if row else
                                                             f"{title} {strip_tags(block[-1200:])} {strip_tags(after)}"),
                              epoch(date, fmt=company.get("format_tanggal", "")) if date else 0,
                              expires=epoch(deadline.group(2)) if deadline else 0),
                    "_detail": not title})
    return out


def html_list(company: dict, now=None, known: dict | None = None) -> list[dict]:
    """Halaman daftar lowongan biasa. Judul yang tak terbaca di daftar diambil dari halaman detailnya."""
    known = known or {}
    now = now or datetime.now(WIB)
    page, final = get_text(company["url"])
    found = cards(page, final, company)
    out, fresh = [], 0
    max_age = int(company.get("maks_hari") or 0)
    for job in found[:cap_of(company)]:
        if job.pop("_detail"):
            old = known.get(job["link"])
            if old:
                job["title"] = old["title"]
            elif fresh < int(company.get("detail") or DETAIL_CAP):
                fresh += 1
                try:
                    detail, url = get_text(job["link"])
                    nodes = jobpostings(detail)
                    if nodes:
                        job = {**from_jsonld(nodes[0], url), "id": job["id"], "link": job["link"]}
                    else:
                        og = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']{120,})',
                                       detail, re.I)
                        job["desc"] = html_to_text(og.group(1)) if og else ""
                        m = (re.search(r"<h1[^>]*>(.*?)</h1>", detail, re.S | re.I)
                             or re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', detail, re.I)
                             or re.search(r"<title[^>]*>(.*?)</title>", detail, re.S | re.I))
                        job["title"] = strip_tags(m.group(1)).split(" | ")[0] if m else ""
                        job["loc"] = company.get("kota") or f"{job['title']} {strip_tags(detail)[:3000]}"
                    sleep(0.3)
                except Exception:  # noqa: BLE001
                    continue
        if not job["title"]:
            continue
        if job["expires"] and job["expires"] < now.timestamp():
            continue
        if max_age and job["posted"] and job["posted"] < now.timestamp() - max_age * 86400:
            continue
        out.append(job)
    return out


ADAPTERS = {
    "workday": workday, "smartrecruiters": smartrecruiters, "workable": workable,
    "successfactors": successfactors, "oracle": oracle, "radancy": radancy, "jsonld": jsonld, "html": html_list,
}
WITH_KNOWN = {"jsonld", "html", "successfactors"}


def _cut(page: str, start: str, ends: tuple[str, ...], size: int = 60000) -> str:
    """Potongan HTML dari penanda awal sampai penanda akhir pertama (untuk isi deskripsi di halaman detail)."""
    m = re.search(start, page, re.I)
    if not m:
        return ""
    begin = page.find(">", m.end())  # mulai sesudah tag pembukanya
    chunk = page[begin + 1:begin + 1 + size]
    cut = min((i for i in (chunk.find(e) for e in ends) if i > 0), default=len(chunk))
    tag = chunk.rfind("<", 0, cut)  # mundur ke awal tag yang memuat penanda akhir
    return chunk[:tag if tag > 0 else cut]


SEC_START = re.compile(
    r"^(tentang (pekerjaan|posisi|peran|lowongan)|deskripsi( pekerjaan| posisi| lowongan| tugas)?|job descriptions?|"
    r"job summary|about (the|this) (role|job|position)|the role|tanggung jawab|responsibilit(y|ies)|key responsibilities|"
    r"ringkasan (pekerjaan|posisi)|uraian (tugas|pekerjaan)|kualifikasi|persyaratan|syarat|requirements?|qualifications?)\s*:?$",
    re.I)
SEC_STOP = re.compile(
    r"^(karir lainnya|karier lainnya|lowongan lainnya|lowongan (terkait|serupa)|posisi lainnya|other (jobs|vacancies|openings|"
    r"opportunities)|similar jobs|related jobs|bagikan( lowongan)?|share( this job)?|cari karir|ikuti kami|follow us|"
    r"hubungi kami|contact us|copyright|\u00a9|lamar sekarang|apply now|daftar sekarang|kembali)\b", re.I)
LOC_LABEL = re.compile(r"^(lokasi penempatan|lokasi kerja|penempatan|work location|job location|placement)\s*:?\s*(.*)$", re.I)
PERIOD = re.compile(r"(\d{1,2} [A-Za-z]{3,9}\.? \d{4})\s*[-\u2013\u2014]\s*(\d{1,2} [A-Za-z]{3,9}\.? \d{4})")


def text_sections(page: str) -> tuple[str, dict]:
    """Deskripsi dari halaman lowongan tanpa format standar, berdasarkan judul bagiannya.

    Mulai dari judul seperti "Tentang Pekerjaan" / "Job Description" sampai bagian penutup seperti
    "Karir Lainnya" / "Bagikan". Juga membaca "Lokasi Penempatan" dan periode pendaftaran "1 Jan 2026 - 31 Des 2026".
    """
    body = re.sub(r"<head\b.*?</head>|<(nav|footer)\b[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    text = html_to_text(body, limit=400_000)
    lines = text.split("\n")
    extra: dict = {}
    for i, line in enumerate(lines):
        m = LOC_LABEL.match(line.strip())
        if m:
            value = m.group(2).strip() or next((x.strip() for x in lines[i + 1:i + 4] if x.strip()), "")
            if 2 < len(value) < 120:
                extra.setdefault("loc", value)
    period = PERIOD.search(text)
    if period:
        extra["expires"] = epoch(period.group(2))
    start = next((i for i, line in enumerate(lines) if SEC_START.match(line.strip("\u2022 ").strip())), None)
    if start is None:
        return "", extra
    first = lines[start].strip().lower()
    out: list[str] = []
    for line in lines[start:]:
        bare = line.strip("\u2022 ").strip()
        if out and (SEC_STOP.match(bare) or bare.lower() == first):
            break  # bagian penutup, atau isi yang sama terulang (tampilan HP dan desktop)
        out.append(line)
    desc = "\n".join(out).strip()
    if len(desc) > DESC_LIMIT:
        desc = desc[:DESC_LIMIT].rsplit("\n", 1)[0].rstrip() + "\n\u2026"
    return (desc if len(desc) > 60 else ""), extra


PDF_NOTE = ("Detail lowongan ini berupa dokumen PDF di situs resmi perusahaan. "
            "Buka lewat tombol lamar untuk membaca deskripsi dan syaratnya.")
PDF_BULLET = re.compile(r"^[▪●■‣⁃∙◦➢–*-]\s*(?=\S)")
PDF_PAGE = re.compile(r"^(page|halaman|hal\.?)\s*\d+\s*(from|of|dari|/)\s*\d+$|^\d+\s*/\s*\d+$", re.I)


def pdf_text(body: bytes) -> tuple[str, dict]:
    """Teks lowongan dari dokumen PDF. Butuh pustaka pypdf (dipasang di workflow); tanpa itu hasilnya kosong."""
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError:
        return "", {}
    try:
        reader = PdfReader(BytesIO(body))
        raw = "\n".join((page.extract_text() or "") for page in reader.pages[:8])
    except Exception:  # noqa: BLE001  PDF rusak atau terkunci
        return "", {}
    lines: list[str] = []
    for line in raw.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if PDF_PAGE.match(line):
            continue
        line = PDF_BULLET.sub("• ", line)
        prev = lines[-1] if lines else ""
        # Baris PDF terpotong sesuai lebar halaman: sambung kembali bila kalimatnya berlanjut.
        if line and prev and not re.search(r"[.:;!?]$", prev) and re.match(r"[a-z(,&]", line):
            lines[-1] = f"{prev} {line}"
        else:
            lines.append(line)
    extra: dict = {}
    for i, line in enumerate(lines):
        m = LOC_LABEL.match(line)
        if m:
            value = m.group(2).strip() or next((x for x in lines[i + 1:i + 3] if x), "")
            if 2 < len(value) < 120:
                extra["loc"] = value
                break
    text = _tidy_lines("\n".join(lines))
    return (text if len(text) > 60 else ""), extra


def describe(company: dict, r: dict) -> tuple[str, dict]:
    """Deskripsi lengkap satu lowongan dari sumbernya. Mengembalikan (teks, {'loc':.., 'type':..})."""
    kind = company["ats"].lower()
    link = r["link"]
    extra: dict = {}
    if kind == "workday":
        parts = urlsplit(link)
        tenant = parts.netloc.split(".")[0]
        info = (get_json(f"https://{parts.netloc}/wday/cxs/{tenant}{parts.path}") or {}).get("jobPostingInfo") or {}
        extra = {"loc": "; ".join(filter(None, [info.get("location"), *(info.get("additionalLocations") or [])])),
                 "type": info.get("timeType") or ""}
        return html_to_text(info.get("jobDescription")), extra
    if kind == "smartrecruiters":
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{company['slug']}/postings/{r['id']}")
        sections = ((data.get("jobAd") or {}).get("sections") or {})
        parts = []
        for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
            sec = sections.get(key) or {}
            if sec.get("text"):
                parts.append(f"<h3>{sec.get('title') or ''}</h3>{sec['text']}")
        return html_to_text("".join(parts)), extra
    _, _, ctype, body = request(link)
    if body[:5] == b"%PDF-" or "pdf" in (ctype or "").lower():
        text, extra = pdf_text(body)  # mis. Vale: setiap lowongan berupa dokumen PDF
        return (text or PDF_NOTE), extra
    page = _decode(body, ctype)
    nodes = jobpostings(page)
    if nodes and nodes[0].get("description"):
        return html_to_text(nodes[0]["description"]), extra
    text, extra = text_sections(page)
    if kind == "successfactors":
        where = re.search(r'itemprop=["\']addressLocality["\'][^>]*>(.*?)<', page, re.S) \
            or re.search(r'class=["\'][^"\']*jobGeoLocation[^"\']*["\'][^>]*>(.*?)<', page, re.S)
        if where:
            extra["loc"] = strip_tags(where.group(1))
        body = _cut(page, r'class=["\']jobdescription["\']|itemprop=["\']description["\']',
                    ('class="applylink', "class='applylink", 'id="similar', 'class="social', "<footer", "jobdescription-footer"))
        return html_to_text(body) or text, extra
    if kind == "radancy":
        body = _cut(page, r'class=["\'][^"\']*ats-description', ('class="job-apply', "<footer", 'class="job-description__footer'))
        return html_to_text(body) or text, extra
    if text:
        return text, extra
    og = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']{120,})', page, re.I)
    return (html_to_text(og.group(1)) if og else ""), extra


LOGO_MIN_PX = 64
LOGO_TRIES = 6             # kandidat gambar yang diunduh untuk dicek per halaman
# Bukan logo perusahaan: ikon media sosial/toko aplikasi, ikon mask Safari (satu warna), versi putih untuk latar gelap.
LOGO_SKIP = re.compile(
    r"facebook|instagram|twitter|tiktok|youtube|linkedin|whatsapp|telegram|google-?play|app-?store|play-?store|"
    r"safari-pinned|mask-icon|placeholder|loading|spinner|sprite|avatar|banner|hero|slider|"
    r"white|putih|negative|inverse|reverse|[-_]wht\b", re.I)
GENERIC_WORDS = {"pt", "tbk", "persero", "indonesia", "the", "and", "dan", "group", "grup", "internasional",
                 "international", "company", "corporation", "corp", "co", "of"}
WHITE = {"#fff", "#ffffff", "white", "#fefefe", "#fdfdfd", "#fcfcfc", "#fafafa", "rgb(255,255,255)", "#ffffffff"}


def brand_words(company: dict) -> set[str]:
    """Kata penanda merek: kata nama perusahaan, singkatannya (Bank Central Asia -> bca), kode, dan slug."""
    words = [w for w in re.findall(r"[a-z0-9]+", (company.get("nama") or "").lower()) if w not in GENERIC_WORDS]
    out = {w for w in words if len(w) >= 3}
    if len(words) >= 2:
        out.add("".join(w[0] for w in words[:4]))
        if words[0] == "bank" and len(words) >= 3:
            out.add("".join(w[0] for w in words[1:4]))
    for extra in (company.get("kode"), company.get("slug"), company.get("label")):
        if extra:
            out |= {w for w in re.findall(r"[a-z0-9]+", str(extra).lower()) if len(w) >= 3}
    return out - {"bank"}


def logo_pages(company: dict) -> list[str]:
    """Halaman yang dibuka untuk mencari logo: beranda, halaman lowongan di platformnya, lalu situs karier."""
    slug = company.get("slug")
    board = {
        "lever": f"https://jobs.lever.co/{slug}",
        "greenhouse": f"https://job-boards.greenhouse.io/{slug}",
        "workable": f"https://apply.workable.com/{slug}/",
        "smartrecruiters": f"https://careers.smartrecruiters.com/{slug}",
    }.get((company.get("ats") or "").lower()) if slug else None
    pages = [company.get("web"), board, company.get("url"), *(company.get("situs") or [])[:2]]
    seen: list[str] = []
    for url in pages:
        if url and url not in seen:
            seen.append(url)
    return seen


def find_logo(company: dict) -> str:
    """Logo resmi perusahaan yang benar-benar bisa ditampilkan.

    Kandidat diambil dari ikon situs (apple-touch-icon dan ikon besar), logo di JSON-LD, gambar ber-"logo" di
    halaman, dan og:image yang berupa logo. Setiap kandidat diunduh dulu: harus gambar sungguhan, tidak terlalu
    kecil, dan bukan logo putih (yang tak terlihat di kotak logo berlatar putih).
    """
    words = brand_words(company)
    tried: set[str] = set()
    if (company.get("ats") or "").lower() == "workable" and company.get("slug"):
        try:  # API akun Workable memuat logo yang diunggah perusahaan
            data = get_json(f"https://apply.workable.com/api/v1/accounts/{company['slug']}")
            url = (data or {}).get("logo") if isinstance(data, dict) else ""
            if url and usable_logo(url):
                return url
        except Exception:  # noqa: BLE001
            pass
    for page_url in logo_pages(company):
        try:
            page, final = _logo_page(page_url)
        except Exception:  # noqa: BLE001
            continue
        checked = 0
        for score, url in logo_candidates(page, final, words):
            if score < LOGO_MIN_PX or url in tried:
                continue
            if checked >= LOGO_TRIES:
                break
            tried.add(url)
            checked += 1
            if usable_logo(url):
                return url
    return ""


def _logo_page(url: str) -> tuple[str, str]:
    _, final, ctype, body = request(url, tries=1, timeout=15)
    return _decode(body, ctype), final


def logo_candidates(page: str, final: str, words: set[str] | None = None) -> list[tuple[int, str]]:
    """Kandidat logo di satu halaman, terurut dari yang paling meyakinkan. Skor kira-kira setara ukuran piksel."""
    words = words or set()
    found: dict[str, int] = {}

    def add(score: int, url: str, hint: str = "") -> None:
        url = urljoin(final, html.unescape(url.strip()).replace("\\/", "/"))
        if not url.startswith("http") or LOGO_SKIP.search(url.split("?")[0]) or LOGO_SKIP.search(hint):
            return
        name = (url.split("?")[0].rsplit("/", 1)[-1] + " " + hint).lower()
        if any(w in name for w in words):
            score += 30  # nama merek di nama berkas atau teks alt: hampir pasti logo perusahaan ini
        found[url] = max(found.get(url, 0), score)

    for tag in re.findall(r"<link\b[^>]*>", page, re.I):
        rel = re.search(r'rel=["\']([^"\']+)', tag, re.I)
        href = re.search(r'href=["\']([^"\']+)', tag, re.I)
        if not rel or not href or "icon" not in rel.group(1).lower() or "mask" in rel.group(1).lower():
            continue
        kind = rel.group(1).lower()
        size = re.search(r'sizes=["\'](\d+)x\d+', tag, re.I)
        score = int(size.group(1)) if size else (180 if "apple" in kind else 0)
        if href.group(1).lower().split("?")[0].endswith(".svg"):
            score = max(score, 256)
        if "apple" in kind:
            score += 40
        add(score, href.group(1))
    for block in JSONLD.findall(page):
        m = re.search(r'"logo"\s*:\s*(?:\{[^}]*?"url"\s*:\s*)?"([^"]+)"', block)
        if m:
            add(150, m.group(1))
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        if re.search(r'(property|name)=["\'](og:image|twitter:image)["\']', tag, re.I):
            content = re.search(r'content=["\']([^"\']+)', tag, re.I)
            if content and "logo" in content.group(1).lower():
                add(120, content.group(1))
    order = 0
    for tag in re.findall(r"<img\b[^>]*>", page, re.I):
        src = re.search(r'\b(?:data-)?src=["\']([^"\'\s]+)["\']', tag, re.I)
        if not src or src.group(1).startswith("data:"):
            continue
        attrs = " ".join(re.findall(r'\b(?:class|id|alt|title)=["\']([^"\']*)["\']', tag, re.I))
        path = src.group(1).split("?")[0].lower()
        if "logo" not in attrs.lower() and "logo" not in path and "brand" not in attrs.lower():
            continue
        if not re.search(r"\.(svg|png|webp|jpe?g|gif)$", path) and "rmkcdn" not in path and "/documents/" not in path:
            continue
        add(100 - min(order, 10) * 2, src.group(1), attrs)
        order += 1
    return sorted(((s, u) for u, s in found.items()), key=lambda x: -x[0])


def image_size(body: bytes) -> tuple[int, int] | None:
    """(lebar, tinggi) gambar PNG/GIF/JPEG/WebP/ICO dari isinya, tanpa pustaka tambahan."""
    if body[:8] == b"\x89PNG\r\n\x1a\n" and len(body) >= 24:
        return int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return int.from_bytes(body[6:8], "little"), int.from_bytes(body[8:10], "little")
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        chunk = body[12:16]
        if chunk == b"VP8X":
            return int.from_bytes(body[24:27], "little") + 1, int.from_bytes(body[27:30], "little") + 1
        if chunk == b"VP8L":
            bits = int.from_bytes(body[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 ":
            return int.from_bytes(body[26:28], "little") & 0x3FFF, int.from_bytes(body[28:30], "little") & 0x3FFF
    if body[:4] == b"\x00\x00\x01\x00":
        count = int.from_bytes(body[4:6], "little")
        sizes = [(body[6 + i * 16] or 256, body[7 + i * 16] or 256) for i in range(min(count, 32)) if 8 + i * 16 <= len(body)]
        return max(sizes, default=(0, 0))
    if body[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(body):
            if body[i] != 0xFF:
                i += 1
                continue
            marker = body[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(body[i + 7:i + 9], "big"), int.from_bytes(body[i + 5:i + 7], "big")
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + int.from_bytes(body[i + 2:i + 4], "big")
    return None


def svg_is_white(svg: str) -> bool:
    """Benar bila semua warna yang dipakai SVG putih: logo untuk latar gelap, tidak terlihat di kotak putih."""
    colors = re.findall(r'(?:fill|stroke|stop-color|color)\s*[:=]\s*["\']?\s*(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}|[a-zA-Z]+)',
                        svg)
    seen = {re.sub(r"\s+", "", c.lower()) for c in colors} - {"none", "transparent", "currentcolor", "inherit", "url"}
    seen = {re.sub(r"^rgba\((\d+,\d+,\d+),[\d.]+\)$", r"rgb(\1)", c) for c in seen}
    return bool(seen) and seen <= WHITE


def usable_logo(url: str) -> bool:
    """Logo bisa dipakai: berkas gambar sungguhan, cukup besar, dan bukan logo putih."""
    try:
        status, _, ctype, body = request(url, headers={"Accept": "image/avif,image/webp,image/svg+xml,image/*,*/*;q=0.8"},
                                         tries=1, timeout=15)
    except Exception:  # noqa: BLE001
        return False
    if status >= 400 or len(body) < 100:
        return False
    head = body[:600].lstrip().lower()
    if b"<svg" in head or b"<?xml" in head[:10] or "svg" in (ctype or "").lower():
        svg = body.decode("utf-8", errors="replace")
        return "<svg" in svg.lower() and not svg_is_white(svg)
    if head.startswith((b"<!doctype", b"<html")) or "html" in (ctype or "").lower():
        return False
    size = image_size(body)
    if size is None:
        return (ctype or "").lower().startswith("image/")  # format lain (mis. AVIF): percayakan pada jenis berkasnya
    return max(size) >= LOGO_MIN_PX


def source_key(company: dict) -> str:
    """Kunci sumber yang stabil: dipakai di id lowongan dan penanda 'via'."""
    return company.get("slug") or (company.get("kode") or "").lower() or re.sub(r"[^a-z0-9]+", "-", company["nama"].lower()).strip("-")


def fetch_company(company: dict, refs: dict, known: dict | None = None, now: datetime | None = None,
                  described: set | None = None):
    """Lowongan berlokasi di Indonesia dari satu perusahaan. Mengembalikan (lowongan, jumlah_mentah).

    known: {tautan: lowongan_kemarin}. described: id lowongan yang deskripsinya sudah tersimpan, jadi tidak
    diambil ulang. Deskripsi baru ditaruh di kunci "desc" setiap lowongan.
    """
    kind = company["ats"].lower()
    adapter = ADAPTERS[kind]
    known = known or {}
    described = described if described is not None else set()
    raw = adapter(company, now, known) if kind in WITH_KNOWN else adapter(company, now)
    key = source_key(company)
    name = clean(company.get("nama"))
    jobs, pairs = [], []
    for r in raw:
        if r.get("_keep"):
            job = {k: v for k, v in r.items() if k != "_keep"}
            jobs.append(job)
            continue
        where = place(r["loc"], refs, strict=bool(company.get("global")))
        if where is None or not r["title"] or not r["id"]:
            continue
        old = known.get(r["link"]) or {}
        if where == ("", "") and (old.get("city") or old.get("province")):
            where = (old.get("city", ""), old.get("province", ""))  # lokasi dari halaman detail kemarin
        ident = re.sub(r"[^A-Za-z0-9_-]+", "", r["id"])[-40:] or hashlib.md5(r["link"].encode()).hexdigest()[:12]
        jobs.append({
            "id": f"{kind[:2]}-{key}-{ident}",
            "title": r["title"],
            "company": name,
            "logo": clean(company.get("logo") or ""),
            "city": where[0],
            "province": where[1],
            "platform": f"Karier {clean(company.get('label') or name)}",
            "function": r["function"],
            "industry": clean(company.get("industri") or ""),
            "type": norm_type(r["type"]) or old.get("type", ""),
            "edu": "",
            "smin": r["smin"],
            "smax": r["smax"],
            # Tanpa tanggal tayang: pakai tanggal pertama kali terlihat supaya tidak tampak "baru" setiap hari.
            "posted": r["posted"] or (known.get(r["link"]) or {}).get("posted") or int((now or datetime.now(WIB)).timestamp()),
            "expires": r["expires"],
            "via": f"{kind}:{key}",
            "link": r["link"],
        })
        pairs.append((jobs[-1], r))
    # Deskripsi lengkap: sebagian platform sudah mengirimnya di daftar, sisanya dari halaman/API detail.
    started, fetched = time.monotonic(), 0
    for job, r in pairs:
        if r.get("desc"):
            job["desc"] = r["desc"]
            continue
        if job["id"] in described or fetched >= DESC_CAP or time.monotonic() - started > DESC_BUDGET_SEC:
            continue
        fetched += 1
        try:
            text, extra = describe(company, r)
        except Exception:  # noqa: BLE001
            continue
        job["desc"] = text  # teks kosong pun dicatat supaya halaman tanpa deskripsi tidak dibuka ulang setiap hari
        if extra.get("loc") and not (job["city"] or job["province"]):
            better = place(extra["loc"], refs)
            if better:
                job["city"], job["province"] = better
        if extra.get("type") and not job["type"]:
            job["type"] = norm_type(extra["type"])
        if extra.get("expires") and not job["expires"]:
            job["expires"] = extra["expires"]
        sleep(0.2)
    now_ts = (now or datetime.now(WIB)).timestamp()
    jobs = [j for j in jobs if not j["expires"] or j["expires"] >= now_ts]
    return jobs, len(raw)


# ---------------------------------------------------------------- mode cek

MARKERS = [
    ("workday", r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?[A-Za-z0-9_-]+)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/(?:api/v\d/widget/accounts/)?([a-z0-9-]+)"),
    ("lever", r"jobs\.lever\.co/([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:boards|job-boards)(?:-api)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)"),
    ("oracle", r"(https?://[a-z0-9-]+\.fa\.[a-z0-9.-]+\.oraclecloud\.com/hcmUI/CandidateExperience/[a-z]{2}/sites/[A-Za-z0-9_]+)"),
    ("successfactors", r"((?:career|performancemanager|hcm)\d*\.(?:sap)?successfactors\.(?:com|eu)[^\"'\s<>]*|rmkcdn\.successfactors\.com|jobs2web)"),
    ("radancy", r"(tbcdn\.talentbrew\.com|radancy)"),
    ("taleo", r"([a-z0-9-]+\.taleo\.net)"),
    ("icims", r"([a-z0-9-]+\.icims\.com)"),
    ("kalibrr", r"kalibrr\.(?:com|id)/(?:[a-z]{2}-[A-Z]{2}/)?c/([a-z0-9-]+)"),
    ("jobstreet", r"(jobstreet\.co(?:m|\.id)[^\"'\s<>]*)"),
    ("glints", r"(glints\.com[^\"'\s<>]*)"),
    ("linkedin", r"(linkedin\.com/(?:company|jobs)[^\"'\s<>]*)"),
    ("recruitee", r"([a-z0-9-]+)\.recruitee\.com"),
    ("teamtailor", r"([a-z0-9-]+)\.teamtailor\.com"),
    ("bamboohr", r"([a-z0-9-]+)\.bamboohr\.com"),
    ("zohorecruit", r"([a-z0-9-]+\.zohorecruit\.[a-z.]+)"),
    ("dealls", r"(dealls\.com[^\"'\s<>]*)"),
    ("phenom", r"(phenompeople|cdn\.phenom)"),
    ("google-form", r"(docs\.google\.com/forms[^\"'\s<>]*|forms\.gle/[A-Za-z0-9]+)"),
    ("talentics", r"jobs\.talentics\.id/([a-z0-9-]+)"),
    ("darwinbox", r"([a-z0-9-]+\.darwinbox\.(?:com|in)/ms/candidate[^\"'\s<>]*)"),
    ("jobseeker", r"([a-z0-9-]+\.jobseeker\.software)"),
    ("sf-rmk", r"(/go/[A-Za-z0-9%,&._-]+/\d+/|/job/[^\"'\s<>]+/\d{6,}/)"),
    ("jsonld", r'"@type"\s*:\s*"JobPosting"'),
]
JOBWORD = re.compile(r"karir|karier|career|job|lowongan|vacanc|recruit|rekrut|apply|lamar|loker|posisi|opening", re.I)


def inspect_page(page: str, final: str) -> dict:
    found: dict[str, list] = {}
    for name, pat in MARKERS:
        hits = []
        for m in re.finditer(pat, page, re.I):
            val = m.group(1) if m.groups() else m.group(0)
            if val not in hits:
                hits.append(val)
            if len(hits) >= 5:
                break
        if hits:
            found[name] = hits
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    anchors = []
    for href, text in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, re.S | re.I):
        text = strip_tags(text)[:80]
        if JOBWORD.search(href) or JOBWORD.search(text):
            url = urljoin(final, html.unescape(href))
            if not any(url == a[1] for a in anchors):
                anchors.append([text, url])
        if len(anchors) >= 40:
            break
    scripts = [urljoin(final, s) for s in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', page, re.I)][:25]
    apis = []
    for u in re.findall(r"https?://[^\"'\s<>\\)]+", page):
        if re.search(r"api|recruit|career|karir|job|vacanc|lowongan|graphql", u, re.I) and u not in apis:
            apis.append(u[:200])
        if len(apis) >= 30:
            break
    rel = sorted(set(re.findall(r"[\"'](/(?:api|v\d|graphql)[^\"'\s<>]{0,120})[\"']", page)))[:30]
    return {
        "title": strip_tags(title.group(1))[:150] if title else "",
        "platform": found,
        "tautan": anchors,
        "skrip": scripts,
        "api": apis,
        "api_relatif": rel,
        "iframe": re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', page, re.I)[:5],
        "jobposting": len(jobpostings(page)),
        "teks": strip_tags(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I))[:600],
        "ukuran": len(page),
        "cuplikan": _snippets(page, final),
    }


def _snippets(page: str, final: str) -> list[str]:
    """Potongan HTML mentah di sekitar dua tautan lowongan pertama, untuk merancang pembaca halaman ini."""
    out = []
    for m in ANCHOR.finditer(page):
        href = urljoin(final, html.unescape(m.group(1)))
        if re.search(JOB_LINK, href, re.I) and not SOCIAL.search(href) and href.rstrip("/") != final.rstrip("/"):
            out.append(re.sub(r"\s+", " ", page[max(0, m.start() - 900):m.end() + 300]))
            if len(out) >= 2:
                break
    return out


PROBE_WORD = re.compile(r"vacanc|lowongan|loker|/jobs?\b|job-?list|joblist|career|karir|position|posisi|opening|requisition", re.I)
PROBE_SKIP = re.compile(r"\.(js|css|png|jpe?g|svg|gif|webp|ico|woff2?|pdf)(\?|$)|auth|login|register|token|recaptcha|google|facebook|"
                        r"instagram|linkedin|twitter|x\.com|youtube|play\.google|apple\.com|wa\.me|mailto", re.I)


def bundle_context(scripts: list[str], limit: int = 14) -> list[str]:
    """Potongan kode di sekitar alamat API lowongan dalam berkas JavaScript, untuk melihat parameter yang dipakai."""
    out: list[str] = []
    picks = [s for s in scripts if re.search(r"(main|app|index|bundle|chunk|_next/static|runtime)", s, re.I)
             and not re.search(r"(jquery|bootstrap|gtag|analytics|recaptcha|cloudflare|polyfill)", s, re.I)][:5]
    for src in picks:
        try:
            code, _ = get_text(src)
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r"[\"'`]([^\"'`\s]{3,160})[\"'`]", code):
            val = m.group(1)
            if not PROBE_WORD.search(val) or PROBE_SKIP.search(val) or not re.search(r"/|api|get|list|search", val, re.I):
                continue
            snippet = re.sub(r"\s+", " ", code[max(0, m.start() - 170):m.end() + 170])
            if not any(val in o for o in out):
                out.append(snippet)
            if len(out) >= limit:
                return out
    return out


def probe_apis(entry: dict, deadline: float) -> list[dict]:
    """Coba alamat API lowongan yang ditemukan di halaman/berkas JavaScript, catat jawabannya (untuk merancang adapter)."""
    found = list(entry.get("api_skrip") or []) + list(entry.get("api") or []) + list(entry.get("api_relatif") or [])
    final = entry.get("akhir") or entry.get("url") or ""
    parts = urlsplit(final)
    origin = f"{parts.scheme}://{parts.netloc}"
    bases = [u for u in found if u.startswith("http") and re.search(r"/api/?$|/api/v\d+/?$|service\.|api\.|webapi/?$", u, re.I)][:3]
    cands: list[str] = []
    for u in found:
        if not PROBE_WORD.search(u) or PROBE_SKIP.search(u) or ":" in u.split("//")[-1].split("/", 1)[-1]:
            continue
        if u.startswith("http"):
            cands.append(u)
        else:
            path = u if u.startswith("/") else "/" + u
            cands += [b.rstrip("/") + path for b in bases] + [origin + path]
    out: list[dict] = []
    for url in dict.fromkeys(cands):
        if len(out) >= 14 or time.monotonic() > deadline:
            break
        row: dict = {"url": url[:220]}
        for method in ("GET", "POST"):
            try:
                status, _, ctype, body = request(url, data=b"{}" if method == "POST" else None, tries=1, timeout=10,
                                                 headers={"Accept": "application/json, text/plain, */*",
                                                          **({"Content-Type": "application/json"} if method == "POST" else {})})
                row.update({"cara": method, "status": status, "jenis": (ctype or "")[:40], "ukuran": len(body),
                            "awal": re.sub(r"\s+", " ", _decode(body, ctype))[:320]})
                break
            except HTTPError as err:
                row.update({"cara": method, "status": err.code})
                if err.code != 405:
                    break
            except Exception as err:  # noqa: BLE001
                row.update({"cara": method, "status": 0, "galat": str(err)[:120]})
                break
        out.append(row)
    return out


def _bundle_apis(scripts: list[str]) -> list[str]:
    """Untuk situs aplikasi (SPA): cari alamat API dan jalur lowongan di berkas JavaScript utamanya."""
    hits: list[str] = []
    picks = [s for s in scripts if re.search(r"(main|app|index|bundle|chunk|_next/static|runtime|vendor)", s, re.I)
             and not re.search(r"(jquery|bootstrap|gtag|analytics|recaptcha|cloudflare|polyfill)", s, re.I)][:5]
    pattern = re.compile(r"[\"'`](https?://[^\"'`\s]{6,160}|/?[A-Za-z0-9_-]+(?:/[A-Za-z0-9_{}$.:-]+){1,6}/?(?:\?[^\"'`\s]{0,80})?)[\"'`]")
    keyword = re.compile(r"api|career|karir|karier|job|vacan|lowongan|recruit|rekrut|posisi|position|opening|loker", re.I)
    for src in picks:
        try:
            code, _ = get_text(src)
        except Exception:  # noqa: BLE001
            continue
        for m in pattern.findall(code):
            if keyword.search(m) and not re.search(r"\.(png|jpe?g|svg|css|woff2?|gif|webp|ico)$", m, re.I) and m not in hits:
                hits.append(m[:200])
            if len(hits) >= 100:
                return hits
    return hits


def guesses(found: dict) -> list[dict]:
    """Konfigurasi adapter yang bisa langsung dicoba dari platform yang terdeteksi."""
    out = []
    for url in found.get("workday", [])[:2]:
        out.append({"ats": "workday", "url": "https://" + url.split("://")[-1]})
    for slug in found.get("smartrecruiters", [])[:2]:
        if slug.lower() not in ("company", "search", "jobs"):
            out.append({"ats": "smartrecruiters", "slug": slug})
    for slug in found.get("workable", [])[:2]:
        if slug not in ("api", "j"):
            out.append({"ats": "workable", "slug": slug})
    for url in found.get("oracle", [])[:1]:
        out.append({"ats": "oracle", "url": url})
    for kind in ("greenhouse", "lever", "ashby"):
        for slug in found.get(kind, [])[:1]:
            out.append({"ats": kind, "slug": slug})
    return out


def try_config(company: dict, cfg: dict, refs: dict) -> dict:
    test = {**company, **cfg, "maks": 40, "detail": 5}
    started = time.monotonic()
    try:
        if test["ats"] in ADAPTERS:
            jobs, raw = fetch_company(test, refs)
        else:
            import update  # Greenhouse/Lever/Ashby ada di update.py
            jobs, raw = update.fetch_board({**test, "slug": test.get("slug", "")}, refs.get("provinces") or {})
        return {**cfg, "ok": True, "mentah": raw, "indonesia": len(jobs), "detik": round(time.monotonic() - started, 1),
                "contoh": [[j["title"], j["city"] or j["province"], j["link"]] for j in jobs[:6]]}
    except Exception as err:  # noqa: BLE001
        return {**cfg, "ok": False, "galat": str(err)[:300], "detik": round(time.monotonic() - started, 1)}


def _sitemap(origin: str) -> dict:
    """Sitemap situs karier: jumlah alamat dan contoh alamat lowongan (untuk adapter jsonld)."""
    out: dict = {}
    try:
        robots, _ = get_text(origin + "/robots.txt")
        maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
    except Exception:  # noqa: BLE001
        maps = []
    maps = maps or [origin + "/sitemap.xml"]
    out["peta"] = maps[:5]
    for url in maps[:2]:
        try:
            text, _ = get_text(url)
        except Exception as err:  # noqa: BLE001
            out.setdefault("galat", []).append(f"{url}: {str(err)[:120]}")
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
        jobs = [u for u in locs if re.search(JOB_LINK, u, re.I)]
        out.setdefault("isi", []).append({"url": url, "alamat": len(locs), "lowongan": len(jobs),
                                          "contoh": (jobs or locs)[:10]})
    return out


CHECK_BUDGET_SEC = 200   # per perusahaan, supaya cek semua perusahaan selesai jauh di bawah 30 menit


def check_company(company: dict, refs: dict) -> dict:
    result: dict = {"kode": company.get("kode", ""), "nama": company["nama"], "grup": company.get("grup", ""),
                    "induk": company.get("induk", ""), "situs": [], "uji": []}
    detected: dict[str, list] = {}
    deadline = time.monotonic() + CHECK_BUDGET_SEC
    late = lambda: time.monotonic() > deadline  # noqa: E731

    def visit(url: str) -> dict:
        entry: dict = {"url": url}
        if late():
            entry.update({"status": 0, "galat": "dilewati: batas waktu cek perusahaan ini"})
            result["situs"].append(entry)
            return entry
        try:
            status, final, ctype, body = request(url, tries=1, timeout=15)
            page = _decode(body, ctype)
            entry.update({"status": status, "akhir": final, **inspect_page(page, final)})
            if entry["ukuran"] < 25_000 and entry["skrip"]:
                entry["api_skrip"] = _bundle_apis(entry["skrip"])
                # Situs aplikasi (isi dimuat JavaScript): catat potongan kode dan coba alamat API lowongannya.
                entry["kode_api"] = bundle_context(entry["skrip"])
                entry["coba_api"] = probe_apis(entry, deadline)
            found = cards(page, final, {"pola": company.get("pola") or JOB_LINK})
            entry["kartu"] = {"jumlah": len(found), "tanpa_judul": sum(1 for j in found if j["_detail"]),
                              "contoh": [[j["title"], j["loc"][:80], j["link"]] for j in found[:8]]}
            for k, v in entry["platform"].items():
                detected.setdefault(k, [])
                detected[k] += [x for x in v if x not in detected[k]]
        except HTTPError as err:
            entry.update({"status": err.code, "galat": str(err)[:200]})
        except Exception as err:  # noqa: BLE001
            entry.update({"status": 0, "galat": str(err)[:200]})
        result["situs"].append(entry)
        return entry

    for url in (company.get("situs") or [])[:5]:
        visit(url)
    if not any(e.get("status") == 200 for e in result["situs"]) and company.get("web"):
        for path in ("/karir", "/careers", "/career", "/id/karir", "/en/careers"):
            if visit(company["web"].rstrip("/") + path).get("status") == 200:
                break
    # Ikuti tautan "Lowongan / Vacancies / Lihat lowongan" satu tingkat lebih dalam.
    seen = {e["url"] for e in result["situs"]} | {e.get("akhir") for e in result["situs"]}
    follow = []
    for entry in [e for e in result["situs"] if e.get("status") == 200]:
        for text, href in entry.get("tautan", []):
            if href in seen or SOCIAL.search(href) or re.search(r"\.pdf($|\?)|login|register|masuk|daftar|signin|sign-in", href, re.I):
                continue
            if re.search(r"lowongan|vacanc|/jobs?\b|/jobs?/?$|career-opportunit|current_vacancies|job-?list|viewalljobs|"
                         r"recruitment\.|rekrutmen\.|careers?\.|karir\.|/go/|type_vacancy", href, re.I) \
                    or re.search(r"lowongan|vacanc|see (all )?(jobs|vacancies)|lihat (semua )?lowongan|cari karir|job opportunit",
                                 text, re.I):
                seen.add(href)
                follow.append(href)
    follow.sort(key=lambda u: 0 if re.search(r"lowongan|vacanc|job", u, re.I) else 1)
    for url in follow[:4]:
        visit(url)
    ok = next((e for e in result["situs"] if e.get("status") == 200), None)
    if ok and not late():
        parts = urlsplit(ok["akhir"])
        result["sitemap"] = _sitemap(f"{parts.scheme}://{parts.netloc}")
    if company.get("ats"):
        cfg = {k: company[k] for k in ("ats", "slug", "url", "cari", "lokasi", "pola") if company.get(k)}
        result["uji"].append({**try_config(company, cfg, refs), "sumber": "perusahaan.json"})
    extra = []
    for entry in [e for e in result["situs"] if e.get("status") == 200]:
        parts = urlsplit(entry["akhir"])
        if "successfactors" in entry.get("platform", {}) and "sf-rmk" in entry.get("platform", {}):
            extra.append({"ats": "successfactors", "url": f"{parts.scheme}://{parts.netloc}", "lokasi": ""})
        if entry.get("kartu", {}).get("jumlah", 0) >= 2:
            extra.append({"ats": "html", "url": entry["akhir"]})
    for slug in detected.get("talentics", [])[:2]:
        extra.append({"ats": "html", "url": f"https://jobs.talentics.id/{slug}", "pola": rf"jobs\.talentics\.id/{slug}/[a-z0-9-]+"})
    tried_html = 0
    for cfg in (company.get("coba") or []) + guesses(detected) + extra:
        if cfg.get("ats") == "html":
            tried_html += 1
            if tried_html > 3:
                continue
        if any(u.get("ats") == cfg.get("ats") and u.get("slug") == cfg.get("slug") and u.get("url") == cfg.get("url")
               for u in result["uji"]):
            continue
        if late():
            result["uji"].append({**cfg, "ok": False, "galat": "dilewati: batas waktu cek perusahaan ini"})
            continue
        result["uji"].append(try_config(company, cfg, refs))
    result["terdeteksi"] = detected
    return result


def check_all(companies: list[dict], refs: dict, workers: int = 16) -> list[dict]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(check_company, c, refs) for c in companies]
        results = []
        for c, fut in zip(companies, futures):
            try:
                results.append(fut.result(timeout=240))
            except Exception as err:  # noqa: BLE001
                results.append({"kode": c.get("kode", ""), "nama": c["nama"], "galat": str(err)[:300]})
            log(f"cek {c['nama']}: selesai")
    return results
