"""Tracking Loker: lowongan dari Disnakerja (www.disnakerja.com), situs info lowongan berbasis WordPress.

Setiap artikel Disnakerja berisi satu perusahaan dengan satu atau beberapa posisi (judul H3). Yang diambil hanya
data ringkas per posisi: nama posisi, perusahaan, lokasi, pendidikan, tipe kerja, tanggal, dan tautan ke artikelnya.
Isi artikel tidak disalin; pelamar membaca kualifikasi dan cara melamar langsung di Disnakerja.

Urutan cara membaca daftar artikel: API WordPress (wp-json), lalu halaman daftar biasa (/page/2/ dst.).
robots.txt situsnya dihormati. Hanya pustaka standar Python.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import karier

BASE = "https://www.disnakerja.com"
VIA = "disnakerja"
PLATFORM = "Disnakerja"
WINDOW_DAYS = 30          # artikel lebih lama dari ini tidak diambil; lowongan tanpa batas lamaran tayang 30 hari
POST_CAP = 300            # artikel baru yang dibuka per penarikan (sisanya di penarikan berikutnya)
LIST_PAGES = 40           # halaman daftar maksimal bila API WordPress tidak tersedia
BUDGET_SEC = 6 * 60
WORKERS = 4
# Bagian situs yang bukan artikel lowongan.
RESERVED = {"page", "category", "tag", "blog", "author", "wp-content", "wp-json", "wp-admin", "wp-includes", "feed", "search",
            "about", "tentang", "kontak", "contact", "privacy-policy", "kebijakan-privasi", "disclaimer", "sitemap", "pasang-iklan",
            "terms", "syarat-dan-ketentuan", "comments", "amp", "lowongan", "loker"}
# Judul H3 di artikel yang bukan nama posisi.
NOT_POSITION = re.compile(
    r"^(cara (melamar|mendaftar|daftar|apply)|persyaratan( umum)?|kualifikasi umum|syarat umum|dokumen|berkas|informasi|info |catatan|"
    r"tentang|profil|benefit|fasilitas|keuntungan|tahapan|jadwal|lowongan (kerja )?lainnya|lowongan terkait|bagikan|share|"
    r"lokasi|penempatan|deskripsi perusahaan|perhatian|disclaimer|kesimpulan|penutup|faq|apa itu|link pendaftaran)", re.I)
EDU_LEVELS = [  # dari yang terendah: "Minimal SMA/SMK" berarti terbuka untuk lulusan SMA
    ("SMP atau Sederajat", r"\bsmp\b|\bsltp\b"),
    ("SMA atau Sederajat", r"\bsma\b|\bsmk\b|\bslta\b|\bma\b(?= ?/)|sma/k|sederajat"),
    ("Diploma", r"\bd-?[134]\b|\bdiploma\b|\bstrata 1/diploma\b"),
    ("Sarjana", r"\bs-?1\b|\bsarjana\b|\bstrata[- ]?1\b|\bbachelor"),
    ("Magister", r"\bs-?2\b|\bmagister\b|\bmaster\b|\bstrata[- ]?2\b"),
]
EDU_LINE = re.compile(r"pendidikan|lulusan|minimal|education|degree|ijazah|jenjang", re.I)
LOC_LINE = re.compile(r"^(lokasi( kerja| penempatan)?|penempatan|domisili|work location|location|kota)\b\s*:?\s*(.*)$", re.I)
TYPE_WORDS = [("Magang", r"\bmagang\b|\bintern(ship)?\b|\bpkl\b"), ("Kontrak", r"\bkontrak\b|\bcontract\b|\bpkwt\b"),
              ("Part time", r"\bpart[- ]?time\b|paruh waktu"), ("Full time", r"\bfull[- ]?time\b|\bpermanen\b|\bpermanent\b|\bpkwtt\b")]
DEADLINE = re.compile(r"(batas|deadline|ditutup|paling lambat|closing date|berakhir|sampai dengan|s\.?d\.?)\D{0,40}?"
                      r"(\d{1,2} [A-Za-z]{3,9}\.? \d{4})", re.I)


def log(msg: str) -> None:
    karier.log(msg)


# ---------------------------------------------------------------- robots.txt

def load_robots() -> RobotFileParser | None:
    """robots.txt Disnakerja. None bila tidak ada (artinya semua boleh dibaca)."""
    rp = RobotFileParser()
    try:
        text, _ = karier.get_text(f"{BASE}/robots.txt")
    except HTTPError as err:
        if err.code in (404, 410):
            return None
        raise
    rp.parse(text.splitlines())
    return rp


def allowed(rp: RobotFileParser | None, url: str) -> bool:
    """Boleh dibaca menurut robots.txt (aturan khusus untuk bot ini, atau aturan umum "*")."""
    return rp is None or rp.can_fetch("TrackingLoker", url)  # nama bot di User-Agent kita


# ---------------------------------------------------------------- daftar artikel

def is_post(url: str) -> bool:
    parts = urlsplit(url)
    if parts.netloc.replace("www.", "") != "disnakerja.com" or parts.query:
        return False
    segs = [s for s in parts.path.split("/") if s]
    return len(segs) == 1 and segs[0] not in RESERVED and not segs[0].isdigit() and "." not in segs[0]


def list_rest(since: datetime) -> list[dict]:
    """Artikel sejak tanggal tertentu lewat API WordPress: [{link, posted, modified}], terbaru dulu."""
    out: list[dict] = []
    after = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # 50 per halaman: bila server mengabaikan _fields, isi artikel ikut terkirim dan jawabannya jadi besar.
    for page in range(1, 41):
        try:
            rows = karier.get_json(f"{BASE}/wp-json/wp/v2/posts", {
                "per_page": 50, "page": page, "after": after, "orderby": "date", "order": "desc",
                "_fields": "link,date_gmt,modified_gmt"})
        except HTTPError as err:
            if err.code == 400 and page > 1:  # halaman melewati batas: semua sudah terbaca
                break
            raise
        if not isinstance(rows, list):
            raise ValueError("bukan daftar artikel WordPress")
        for r in rows:
            link = r.get("link") or ""
            if is_post(link):
                out.append({"link": link, "posted": _utc(r.get("date_gmt")), "modified": _utc(r.get("modified_gmt"))})
        if len(rows) < 50:
            break
    return out


def _utc(value) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "")).replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return 0


def post_links(page: str) -> list[str]:
    """Tautan artikel lowongan di satu halaman daftar, sesuai urutan tampil."""
    seen: list[str] = []
    for href in re.findall(r'<a\b[^>]*href=["\'](https?://(?:www\.)?disnakerja\.com/[^"\'#?]+)["\']', page, re.I):
        url = href if href.endswith("/") else href + "/"
        url = url.replace("://disnakerja.com", "://www.disnakerja.com")
        if is_post(url) and url not in seen:
            seen.append(url)
    return seen


# ---------------------------------------------------------------- isi artikel

END_MARK = re.compile(
    r'<footer\b|id=["\']comments|class=["\'][^"\']*\b(related-posts|sharedaddy|post-tags|jp-relatedposts)\b|'
    r'>\s*(?:<(?:strong|b)>\s*)?(Info Lowongan Lainnya|Lowongan Lainnya|Lowongan Terkait|Artikel Terbaru|Lowongan Berdasarkan)'
    r'\s*(?:</(?:strong|b)>)?\s*[:,]?\s*(?:<|dapat)', re.I)


def _region(page: str) -> str:
    """Bagian artikel: dari judul H1 sampai "Info Lowongan Lainnya", daftar artikel terkait, komentar, atau footer.

    Penanda akhir harus berdiri sendiri sebagai isi elemen, supaya tautan "Lowongan Terbaru" di menu atau
    "Baca Juga" di tengah artikel tidak memotong daftar posisi.
    """
    start = re.search(r"<h1\b", page, re.I)
    body = page[start.start():] if start else page
    end = END_MARK.search(body)
    return body[:end.start()] if end else body


def _text(markup: str) -> str:
    # Sel tabel dan daftar definisi (label metadata) dipisah per baris.
    return karier.html_to_text(re.sub(r"</(td|th|dt|dd)>", "\n", markup, flags=re.I), limit=200_000)


META_LABELS = r"lokasi( kerja| penempatan)?|penempatan|pendidikan( terakhir| minimal)?|jenjang pendidikan|tipe pekerjaan|" \
    r"jenis pekerjaan|pengalaman( kerja)?|kategori|last update|terakhir diperbarui|gaji|deadline|batas lamaran"


def label_value(lines: list[str], names: str) -> str:
    """Nilai di samping atau di bawah label: "Lokasi: Jawa Barat", "Lokasi" lalu "Jawa Barat", atau satu baris berisi
    beberapa label sekaligus ("Lokasi Jawa Barat Pendidikan S1") yang dipotong di label berikutnya."""
    pat = re.compile(rf"^(?:{names})\b\s*:?\s*(?P<v>.*)$", re.I)
    nxt = re.compile(rf"\s(?:{META_LABELS})\b\s*:?", re.I)
    for i, line in enumerate(lines):
        m = pat.match(line.strip("\u2022 ").strip())
        if not m:
            continue
        value = m.group("v").strip(" :")
        if not value:
            value = next((x.strip() for x in lines[i + 1:i + 3] if x.strip()), "")
            if re.match(rf"^({META_LABELS})\b", value, re.I):
                continue
        cut = nxt.search(" " + value)
        if cut:
            value = (" " + value)[:cut.start()].strip()
        if 1 < len(value) < 120:
            return value
    return ""


def edu_level(text: str) -> str:
    """Jenjang pendidikan terendah yang disebut, dengan nama yang sama seperti data Karirhub."""
    low = text.lower()
    lines = [x for x in low.split("\n") if EDU_LINE.search(x)] or [low]
    joined = "\n".join(lines)
    for name, pat in EDU_LEVELS:
        if re.search(pat, joined):
            return name
    return ""


def work_type(text: str) -> str:
    for name, pat in TYPE_WORDS:
        if re.search(pat, text, re.I):
            return name
    return ""


def _clean_title(text: str) -> str:
    title = karier.clean(re.sub(r"<[^>]+>", " ", text))
    title = re.sub(r"^(\d+[.)]|[-•*])\s*", "", title)
    title = re.sub(r"^(lowongan( kerja)?|posisi|position)\s*:?\s+", "", title, flags=re.I)
    return title.strip(" :-")


def company_name(page: str) -> str:
    m = re.search(r"<h1\b[^>]*>(.*?)</h1>", page, re.S | re.I)
    name = karier.clean(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""
    name = re.sub(r"^(info )?(lowongan( kerja)?|loker|rekrutmen|recruitment)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+[-|–]\s+disnakerja.*$", "", name, flags=re.I)
    return name.strip()


def published(page: str) -> int:
    for pat in (r'"datePublished"\s*:\s*"([^"]+)"', r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*property=["\']article:published_time'):
        m = re.search(pat, page)
        if m:
            try:
                return int(datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp())
            except ValueError:
                continue
    return 0


def logo_of(page: str) -> str:
    """Gambar unggulan artikel (biasanya logo perusahaan)."""
    m = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)', page) \
        or re.search(r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image', page)
    url = html.unescape(m.group(1)) if m else ""
    return url if "/wp-content/uploads/" in url and not re.search(r"default|placeholder|banner|cover", url, re.I) else ""


# Baris tebal yang berupa label, bukan nama posisi ("Kualifikasi", "Persyaratan Berkas", "INFO").
LABEL_WORDS = re.compile(
    r"^(kualifikasi|persyaratan|syarat|tanggung ?jawab|deskripsi|job ?desc|uraian|requirement|responsib|qualification|benefit|"
    r"fasilitas|cara|pendaftaran|catatan|note|info|penempatan|lokasi|dokumen|berkas|tahapan|jadwal|gaji|keterangan|"
    r"perhatian|ketentuan|kriteria|lowongan|tentang|profil|batas|periode|kirim|lamar|apply|email|link|website|alamat|"
    r"tunjangan|keuntungan|penting|disclaimer|update|kontak|hubungi|penutup|kesimpulan|ayo|yuk|segera)\b", re.I)
# Paragraf atau subjudul. Penutup </p> boleh tidak ada (HTML yang dirampingkan): paragraf berakhir di blok berikutnya.
PARA = re.compile(r"<(p|h[2-5])\b[^>]*>(.*?)(?=</\1>|<p\b|<h[1-6]\b|<ul\b|<ol\b|<div\b|<hr\b|<table\b|</div>)", re.S | re.I)
LEAD_BOLD = re.compile(r"^(?:\s|&nbsp;|&#160;|<br\s*/?>|<span\b[^>]*>)*<(strong|b)\b[^>]*>(.*?)</\1>", re.S | re.I)


def bold_lines(region: str) -> list[tuple[int, int, str]]:
    """Baris yang diawali teks tebal dan tebalnya berdiri sendiri: "<p><strong>1. Team Leader</strong></p>", juga bila
    disusul <br> dan rinciannya di paragraf yang sama. Tebal di tengah kalimat tidak dihitung."""
    out = []
    for m in PARA.finditer(region):
        inner = m.group(2)
        lead = LEAD_BOLD.match(inner)
        if not lead:
            continue
        rest = inner[lead.end():]
        rest_text = karier.clean(re.sub(r"<[^>]+>", " ", rest)).strip(" :\u00a0")
        if rest_text and not re.match(r"^(?:\s|&nbsp;|</span>|:)*<br\b", rest, re.I):
            continue
        raw = karier.clean(re.sub(r"<[^>]+>", " ", lead.group(2)))
        if raw:
            out.append((m.start(), m.start(2) + lead.end(), raw))
    return out


HEADING = re.compile(r"<(h[2-5])\b[^>]*>(.*?)</\1>", re.S | re.I)
NUMBERED = re.compile(r"^\d{1,2}\s*[.)]\s*\S")


def find_positions(region: str, company: str) -> list[tuple[int, int, str]]:
    """Nama posisi di artikel Disnakerja: baris tebal sendiri (biasanya bernomor, "1. Team Leader") atau subjudul.

    Label seperti "Kualifikasi:", judul "Lowongan Kerja PT X", dan nama perusahaan dilewati. Bila ada yang bernomor,
    hanya yang bernomor yang dipakai.
    """
    found = bold_lines(region)
    for m in HEADING.finditer(region):
        found.append((m.start(), m.end(), karier.clean(re.sub(r"<[^>]+>", " ", m.group(2)))))
    found.sort()
    company_key = re.sub(r"[^a-z0-9]+", " ", company.lower()).strip()
    out, seen = [], set()
    for start, end, raw in found:
        title = _clean_title(raw)
        key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        if (not title or len(title) < 3 or len(title) > 90 or len(title.split()) > 12 or ":" in raw.rstrip(" :")
                or raw.rstrip().endswith(":") or LABEL_WORDS.match(title) or NOT_POSITION.match(title)
                or key in (company_key, re.sub(r"^(pt|cv) ", "", company_key)) or company_key and company_key in key
                or "disnakerja" in key or re.search(r"https?://|@", title) or key in seen):
            continue
        if any(s < start < e for s, e, _ in out):
            continue  # baris tebal di dalam subjudul yang sudah diambil
        seen.add(key)
        out.append((start, end, raw))
    if any(NUMBERED.match(raw) for _, _, raw in out):
        out = [x for x in out if NUMBERED.match(x[2])]
    return [(s, e, _clean_title(raw)) for s, e, raw in out]


def _bold_raw(region: str, pos: tuple[int, int, str]) -> str:
    """Teks asli (dengan nomornya) dari baris tebal di posisi tertentu."""
    return karier.clean(re.sub(r"<[^>]+>", " ", region[pos[0]:pos[1]]))


def _date_text(text: str, now: datetime) -> int:
    """Tanggal dari teks seperti "October 22, 2026" atau "22 Oktober 2026"."""
    m = re.search(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", text or "")
    if m:
        try:
            return int(datetime.strptime(" ".join(m.groups()), "%B %d %Y").replace(tzinfo=karier.WIB).timestamp())
        except ValueError:
            pass
    return karier.epoch(text, now) if text else 0


def edu_for(section: str, title: str, others: list[str]) -> str:
    """Jenjang pendidikan untuk satu posisi. Baris "Pendidikan minimal D3/S1 untuk Quality Assurance" dipakai untuk
    posisi yang disebut namanya; baris untuk posisi lain dilewati."""
    lines = [x for x in section.lower().split("\n") if EDU_LINE.search(x)]
    me = title.lower()
    own = [x for x in lines if me in x]
    if own:
        lines = own
    else:
        lines = [x for x in lines if not any(o.lower() in x for o in others if o.lower() != me)]
    return edu_level("\n".join(lines)) if lines else ""


def parse_post(page: str, link: str, refs: dict, now: datetime, posted_hint: int = 0) -> tuple[list[dict], dict]:
    """Lowongan per posisi dari satu artikel. Mengembalikan (lowongan, info) untuk laporan cek."""
    company = company_name(page)
    region = _region(page)
    lines = [x for x in _text(region).split("\n")]
    meta = {
        "lokasi": label_value(lines, r"lokasi( kerja| penempatan)?|penempatan"),
        "pendidikan": label_value(lines, r"pendidikan( terakhir| minimal)?|jenjang pendidikan|education"),
        "tipe": label_value(lines, r"tipe pekerjaan|jenis pekerjaan|tipe|status( kerja| pekerjaan)?|job type"),
        "update": label_value(lines, r"last update|terakhir diperbarui|diperbarui|update"),
    }
    # Tanggal terbit dari API WordPress paling tepat; "Last Update" di halaman hanya cadangan.
    posted = posted_hint or published(page) or _date_text(meta["update"], now) or int(now.timestamp())
    positions = find_positions(region, company)
    if not positions:
        # Cadangan: seluruh halaman dari H1 sampai footer, hanya baris tebal bernomor ("1. Team Leader").
        start = re.search(r"<h1\b", page, re.I)
        whole = page[start.start() if start else 0:]
        foot = re.search(r"<footer\b", whole, re.I)
        region = whole[:foot.start()] if foot else whole
        positions = [x for x in find_positions(region, company) if x[2] and NUMBERED.match(_bold_raw(region, x))]
    bold = [raw for _, _, raw in bold_lines(region)]
    info = {"perusahaan": company, "posisi": [t for _, _, t in positions],
            "baris_tebal_lain": [b for b in bold if _clean_title(b) not in {t for _, _, t in positions}][:10],
            "meta": meta, "tanggal": posted,
            # Untuk menelusuri bila posisi tidak terbaca: ukuran bagian artikel dan jumlah teks tebal.
            "panjang_artikel": len(region), "tebal_di_halaman": len(re.findall(r"<(strong|b)\b", page, re.I)),
            "tebal_di_artikel": len(re.findall(r"<(strong|b)\b", region, re.I)),
            "contoh_tebal_halaman": [m.group(0) for m in re.finditer(r"<(?:p|h\d|li|div)\b[^>]*>\s*<(?:strong|b)\b[\s\S]{0,160}",
                                                                      page, re.I)][:4]}
    if not company or not positions:
        return [], info
    full_text = "\n".join(lines)
    deadline = DEADLINE.search(full_text)
    expires = karier.epoch(deadline.group(2), now) if deadline else 0
    if not expires or expires < posted:
        expires = posted + WINDOW_DAYS * 86400
    meta_place = karier.place(meta["lokasi"], refs) if meta["lokasi"] else None
    logo = logo_of(page)
    slug = urlsplit(link).path.strip("/").split("/")[-1][-60:]
    jobs = []
    titles = [t for _, _, t in positions]
    sections = [_text(region[end:(positions[i + 1][0] if i + 1 < len(positions) else len(region))])
                for i, (_, end, _) in enumerate(positions)]
    for i, (start, end, title) in enumerate(positions):
        # Posisi berurutan tanpa isi ("1. Supervisor Sewing", "2. Quality Assurance", lalu satu daftar kualifikasi):
        # pakai kualifikasi bersama di bawahnya.
        section = next((x for x in sections[i:] if x.strip()), "")
        sec_lines = section.split("\n")
        where = None
        for line in sec_lines:
            m = LOC_LINE.match(line.strip("• ").strip())
            if m and m.group(3):
                where = karier.place(m.group(3), refs)
                if where and where != ("", ""):
                    break
        for guess in (where, karier.place(title, refs), meta_place):
            if guess and guess != ("", ""):
                where = guess
                break
        else:
            where = ("", "")
        ident = hashlib.md5(title.lower().encode()).hexdigest()[:8]
        jobs.append({
            "id": f"dk-{slug}-{ident}",
            "title": title,
            "company": company,
            "logo": logo,
            "city": where[0],
            "province": where[1],
            "platform": PLATFORM,
            "function": "",
            "industry": "",
            "type": work_type(title + "\n" + section) or karier.norm_type(meta["tipe"]) or work_type(meta["tipe"]),
            "edu": edu_for(section, title, titles) or edu_level(meta["pendidikan"]),
            "smin": 0,
            "smax": 0,
            "posted": posted,
            "expires": expires,
            "via": VIA,
            "link": link,
        })
    return jobs, info


def dedupe(jobs: list[dict]) -> list[dict]:
    """Disnakerja kadang menerbitkan ulang lowongan yang sama di artikel baru: simpan yang terbaru saja."""
    best: dict[tuple, dict] = {}
    for j in sorted(jobs, key=lambda x: -x["posted"]):
        key = (re.sub(r"[^a-z0-9]+", " ", j["company"].lower()).strip(), re.sub(r"[^a-z0-9]+", " ", j["title"].lower()).strip())
        best.setdefault(key, j)
    return list(best.values())


# ---------------------------------------------------------------- penarikan

def fetch(refs: dict, prev: dict, now: datetime | None = None, state: dict | None = None, cap: int = POST_CAP):
    """Lowongan Disnakerja 30 hari terakhir. Mengembalikan (lowongan, utuh, ringkasan, catatan_baru).

    prev: lowongan kemarin {id: lowongan}. state: catatan artikel yang sudah dibaca {tautan: {"m": diubah, "p": terbit}},
    supaya artikel yang tidak berubah tidak dibuka lagi. utuh: semua artikel dalam jendela 30 hari terbaca, jadi
    lowongan yang artikelnya hilang boleh dianggap ditutup.
    """
    from concurrent.futures import ThreadPoolExecutor

    now = now or datetime.now(karier.WIB)
    since = now - timedelta(days=WINDOW_DAYS)
    cutoff = since.timestamp()
    started = time.monotonic()
    state = dict(state or {})
    rp = load_robots()
    if not allowed(rp, f"{BASE}/"):
        raise RuntimeError("robots.txt Disnakerja tidak mengizinkan halaman lowongannya dibaca")
    known: dict[str, list[dict]] = {}
    for job in prev.values():
        if job.get("via") == VIA and job.get("link"):
            known.setdefault(job["link"], []).append(job)

    complete = True
    method = "api"
    try:
        posts = list_rest(since)
    except Exception as err:  # noqa: BLE001  API ditutup: baca halaman daftar biasa
        log(f"Disnakerja: API WordPress tidak bisa dipakai ({str(err)[:80]}), membaca halaman daftar")
        method = "halaman"
        posts, seen = [], set()
        for n in range(1, LIST_PAGES + 2):
            if n > LIST_PAGES:
                complete = False  # masih ada halaman yang belum terbaca
                break
            url = BASE + ("/" if n == 1 else f"/page/{n}/")
            if not allowed(rp, url):
                break
            try:
                page, _ = karier.get_text(url)
            except HTTPError as e:
                if e.code == 404:
                    break
                raise
            links = [u for u in post_links(page) if u not in seen]
            if not links:
                break
            seen.update(links)
            posts += [{"link": u, "posted": (state.get(u) or {}).get("p", 0), "modified": 0} for u in links]
            # Semua artikel di halaman ini sudah tercatat lebih tua dari jendela 30 hari: halaman berikutnya lebih tua lagi.
            dates = [(state.get(u) or {}).get("p", 0) for u in links]
            if all(dates) and max(dates) < cutoff:
                break
            karier.sleep(0.5)

    jobs: list[dict] = []
    todo = []
    for p in posts:
        note = state.get(p["link"]) or {}
        if p["posted"] and p["posted"] < cutoff:
            continue
        unchanged = note and (not p["modified"] or p["modified"] <= note.get("m", 0))
        if unchanged:
            if note.get("p", 0) >= cutoff:
                jobs += [dict(j) for j in known.get(p["link"], [])]
            continue
        if allowed(rp, p["link"]):
            todo.append(p)
    if len(todo) > cap:
        complete = False
        todo = todo[:cap]

    def one(p):
        if time.monotonic() - started > BUDGET_SEC:
            return p, None
        try:
            page, _ = karier.get_text(p["link"])
        except Exception:  # noqa: BLE001
            return p, None
        karier.sleep(0.3)
        return p, parse_post(page, p["link"], refs, now, p["posted"])

    opened = parsed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for p, result in pool.map(one, todo):
            if result is None:
                complete = False
                continue
            opened += 1
            found, info = result
            parsed += bool(found)
            state[p["link"]] = {"m": p["modified"] or int(now.timestamp()), "p": info["tanggal"]}
            jobs += found
    jobs = [j for j in jobs if j["posted"] >= cutoff and (not j["expires"] or j["expires"] >= now.timestamp())]
    jobs = dedupe(jobs)
    # Catatan artikel yang sudah jauh di luar jendela dibuang supaya berkasnya tidak terus membesar.
    state = {k: v for k, v in state.items() if v.get("p", 0) >= cutoff - 14 * 86400}
    summary = {"cara": method, "artikel": len(posts), "dibuka": opened, "berisi_lowongan": parsed, "utuh": complete}
    log(f"Disnakerja: {len(jobs)} lowongan dari {len(posts)} artikel ({method}; {opened} artikel dibuka, "
        f"{parsed} berisi lowongan{'' if complete else '; sebagian, dilanjutkan penarikan berikutnya'})")
    return jobs, complete, summary, state


def check(refs: dict, now: datetime | None = None, sample: int = 8) -> dict:
    """Laporan untuk mode cek: cara membaca daftar artikel, dan hasil membaca beberapa artikel terbaru."""
    now = now or datetime.now(karier.WIB)
    report: dict = {"nama": "Disnakerja", "situs": BASE}
    try:
        rp = load_robots()
        report["robots"] = "tidak ada" if rp is None else ("boleh" if allowed(rp, f"{BASE}/") else "dilarang")
    except Exception as err:  # noqa: BLE001
        report["robots"] = f"gagal: {str(err)[:160]}"
        rp = None
    links: list[str] = []
    try:
        posts = list_rest(now - timedelta(days=3))
        report["api"] = f"ok, {len(posts)} artikel 3 hari terakhir"
        links = [p["link"] for p in posts]
    except Exception as err:  # noqa: BLE001
        report["api"] = f"gagal: {str(err)[:160]}"
    try:
        page, final = karier.get_text(BASE + "/")
        found = post_links(page)
        report["halaman_daftar"] = {"status": "ok", "url": final, "artikel": len(found), "contoh": found[:5]}
        links = links or found
    except Exception as err:  # noqa: BLE001
        report["halaman_daftar"] = {"status": f"gagal: {str(err)[:160]}"}
    samples = []
    for link in links[:sample]:
        try:
            page, _ = karier.get_text(link)
            jobs, info = parse_post(page, link, refs, now)
            info["lowongan"] = [{k: j[k] for k in ("title", "city", "province", "edu", "type")} for j in jobs]
            info["logo"] = logo_of(page)
            samples.append({"url": link, **info})
        except Exception as err:  # noqa: BLE001
            samples.append({"url": link, "gagal": str(err)[:160]})
        karier.sleep(0.5)
    report["contoh_artikel"] = samples
    report["berhasil"] = sum(1 for s in samples if s.get("lowongan"))
    return report
