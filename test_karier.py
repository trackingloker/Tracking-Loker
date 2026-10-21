"""Uji adapter situs karier (karier.py) dengan respons tiruan berbentuk sama seperti aslinya."""

import json
import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import karier
import update

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=karier.WIB)
REFS = {
    "provinces": {"p1": "Banten", "p2": "DKI Jakarta", "p3": "Jawa Barat", "p4": "Sulawesi Selatan"},
    "cities": {"c1": ("Kab. Tangerang", "p1"), "c2": ("Kota Tangerang", "p1"), "c3": ("Kota Adm. Jakarta Selatan", "p2"),
               "c4": ("Kab. Karawang", "p3"), "c5": ("Kab. Luwu Timur", "p4")},
    "educations": {},
}


class FakeHttp:
    """routes: {potongan_url: fungsi(url, data) -> (isi, content_type) atau objek JSON}"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, data=None, headers=None, timeout=25):
        self.calls.append((url, json.loads(data) if data else None))
        for key, fn in self.routes.items():
            if key in url:
                out = fn(url, json.loads(data) if data else None)
                if isinstance(out, Exception):
                    raise out
                if isinstance(out, tuple):
                    body, ctype = out
                else:
                    body, ctype = json.dumps(out), "application/json"
                return 200, url, ctype, body if isinstance(body, bytes) else body.encode()
        raise HTTPError(url, 404, "tidak ada", {}, BytesIO())


try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


def png(width: int, height: int) -> tuple[bytes, str]:
    """Berkas PNG tiruan: cukup tanda tangan dan header ukurannya."""
    head = b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")
    return head + b"\x08\x06\x00\x00\x00" + bytes(120), "image/png"


def svg(fill: str) -> tuple[str, str]:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40"><path fill="{fill}" d="M0 0h100v40H0z"/>'
            f'<path style="fill:{fill}" d="M10 10h20v20H10z"/></svg>'), "image/svg+xml"


def tiny_pdf(lines: list[str]) -> bytes:
    """PDF satu halaman berisi baris teks (Helvetica), dengan tabel xref yang benar."""
    text = "BT /F1 11 Tf 14 TL 50 780 Td " + " ".join(
        "(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self._http, self._sleep = karier.http, karier.sleep
        karier.sleep = lambda s: None
        karier.log = lambda m: None
        update.log = lambda m: None

    def tearDown(self):
        karier.http, karier.sleep = self._http, self._sleep

    def use(self, routes):
        karier.http = FakeHttp(routes)
        return karier.http


class TestLokasi(unittest.TestCase):
    def test_kota_dan_provinsi(self):
        self.assertEqual(karier.place("South Jakarta, Indonesia"), ("Kota Adm. Jakarta Selatan", "DKI Jakarta"))
        self.assertEqual(karier.place("BSD City, Tangerang"), ("Kota Tangerang Selatan", "Banten"))
        self.assertEqual(karier.place("Kabupaten Tangerang, Banten", REFS), ("Kab. Tangerang", "Banten"))
        self.assertEqual(karier.place("Sorowako, South Sulawesi"), ("Kab. Luwu Timur", "Sulawesi Selatan"))
        self.assertEqual(karier.place("Karawang", REFS), ("Kab. Karawang", "Jawa Barat"))
        self.assertEqual(karier.place("East Kalimantan, Indonesia"), ("", "Kalimantan Timur"))
        self.assertEqual(karier.place("Indonesia"), ("", ""))

    def test_luar_negeri_dan_mode_ketat(self):
        self.assertIsNone(karier.place("Singapore"))
        self.assertIsNone(karier.place("Bangkok, Thailand"))
        self.assertEqual(karier.place("Kuala Lumpur, Malaysia; Jakarta, Indonesia"), ("Jakarta", "DKI Jakarta"))
        self.assertIsNone(karier.place("Rotterdam", strict=True))
        self.assertEqual(karier.place("Kantor Pusat"), ("", ""))  # perusahaan lokal: tetap Indonesia

    def test_tanggal(self):
        self.assertEqual(karier.epoch("Posted Today", NOW), int(NOW.timestamp()))
        self.assertEqual(karier.epoch("Posted 30+ Days Ago", NOW), int(NOW.timestamp()) - 30 * 86400)
        self.assertEqual(karier.epoch("Oct 1, 2026"), int(datetime(2026, 10, 1, tzinfo=karier.WIB).timestamp()))
        self.assertGreater(karier.epoch("2026-10-01T08:00:00Z"), 0)
        self.assertEqual(karier.epoch(1791883269000), 1791883269)


class TestWorkday(Base):
    def test_filter_indonesia_dan_halaman(self):
        jobs = [{"title": f"Staff {i}", "externalPath": f"/job/Jakarta/Staff-{i}_R{i}", "locationsText": "Jakarta, Indonesia",
                 "postedOn": "Posted 2 Days Ago", "bulletFields": [f"R{i}"]} for i in range(45)]
        facets = [{"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locationCountry", "descriptor": "Country", "values": [
                {"descriptor": "Singapore", "id": "sg1", "count": 9}, {"descriptor": "Indonesia", "id": "id1", "count": 45}]}]}]

        def api(url, body):
            applied = body["appliedFacets"]
            rows = jobs if applied == {"locationCountry": ["id1"]} else jobs[:3] + [{"title": "SG", "externalPath": "/job/SG_1",
                                                                                        "locationsText": "Singapore"}]
            return {"total": len(rows), "facets": facets, "jobPostings": rows[body["offset"]: body["offset"] + body["limit"]]}

        http = self.use({"/wday/cxs/acme/External/jobs": api})
        out = karier.workday({"url": "https://acme.wd3.myworkdayjobs.com/en-US/External", "maks": 40}, NOW)
        self.assertEqual(len(out), 40)
        self.assertEqual(out[0]["link"], "https://acme.wd3.myworkdayjobs.com/External/job/Jakarta/Staff-0_R0")
        self.assertEqual(out[0]["id"], "R0")
        self.assertEqual(out[0]["posted"], int(NOW.timestamp()) - 2 * 86400)
        self.assertEqual(http.calls[1][1]["appliedFacets"], {"locationCountry": ["id1"]})


class TestApiPublik(Base):
    def test_smartrecruiters(self):
        self.use({"api.smartrecruiters.com/v1/companies/Acme/postings": lambda u, b: {"totalFound": 2, "content": [
            {"id": "744", "name": "Data Analyst", "releasedDate": "2026-10-10T03:00:00.000Z",
             "location": {"city": "Jakarta", "country": "id"}, "typeOfEmployment": {"label": "Full-time"},
             "function": {"label": "Information Technology"}},
            {"id": "745", "name": "Barista", "location": {"city": "Singapore", "country": "sg"}}]}})
        out = karier.fetch_company({"nama": "Acme", "ats": "smartrecruiters", "slug": "Acme", "global": True}, REFS, now=NOW)[0]
        self.assertEqual([j["title"] for j in out], ["Data Analyst"])
        self.assertEqual(out[0]["link"], "https://jobs.smartrecruiters.com/Acme/744")
        self.assertEqual(out[0]["via"], "smartrecruiters:Acme")

    def test_workable(self):
        self.use({"apply.workable.com/api/v1/widget/accounts/indico": lambda u, b: {"name": "INDICO", "jobs": [
            {"title": "Backend Engineer", "shortcode": "AB12CD", "url": "https://apply.workable.com/j/AB12CD",
             "published_on": "2026-10-12", "employment_type": "Full-time", "department": "Engineering",
             "locations": [{"city": "Jakarta", "region": "Jakarta", "country": "Indonesia"}]}]}})
        jobs, raw = karier.fetch_company({"nama": "INDICO", "ats": "workable", "slug": "indico", "kode": ""}, REFS, now=NOW)
        self.assertEqual((len(jobs), raw), (1, 1))
        self.assertEqual(jobs[0]["id"], "wo-indico-AB12CD")
        self.assertEqual((jobs[0]["city"], jobs[0]["province"]), ("Jakarta", "DKI Jakarta"))
        self.assertEqual(jobs[0]["platform"], "Karier INDICO")

    def test_oracle(self):
        self.use({"recruitingCEJobRequisitions": lambda u, b: {"items": [{"TotalJobsCount": 1, "requisitionList": [
            {"Id": "300", "Title": "Plant Engineer", "PostedDate": "2026-10-09", "PrimaryLocation": "Cilegon",
             "PrimaryLocationCountry": "ID"}]}]}})
        out = karier.oracle({"url": "https://abcd.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2"})
        self.assertEqual(out[0]["link"], "https://abcd.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2/job/300")
        self.assertIn("Indonesia", out[0]["loc"])


class TestHalamanHtml(Base):
    def test_successfactors(self):
        row = ('<tr class="data-row"><td><a class="jobTitle-link" href="/job/Jakarta-Analyst/{id}/">Analyst {id}</a>'
               '<a class="jobTitle-link" href="/job/Jakarta-Analyst/{id}/">Analyst {id}</a></td>'
               '<td><span class="jobLocation">Jakarta, ID</span></td><td><span class="jobDate">Oct 1, 2026</span></td></tr>')

        def page(url, body):
            start = int(parse_qs(urlsplit(url).query)["startrow"][0])
            ids = range(start, min(start + 25, 30))
            return "<table>" + "".join(row.format(id=1000 + i) for i in ids) + "</table>", "text/html"

        self.use({"jobs.example.com/search/": page})
        out = karier.successfactors({"url": "https://jobs.example.com"})
        self.assertEqual(len(out), 30)
        self.assertEqual(out[0]["link"], "https://jobs.example.com/job/Jakarta-Analyst/1000/")
        self.assertEqual(out[0]["loc"], "Jakarta, ID")

    def test_successfactors_cadangan_sitemap(self):
        sitemap = ('<urlset><url><loc>https://career.petrosea.com/job/Murung-Raya-Maintenance-Dispatcher-DBK/59988244/</loc></url>'
                   '<url><loc>https://career.petrosea.com/go/View-All-Jobs/644644/</loc></url></urlset>')
        detail = ('<h1><span itemprop="title">Maintenance Dispatcher DBK</span></h1>'
                  '<span itemprop="jobLocation"><span itemprop="address"><span itemprop="addressLocality">Murung Raya</span></span></span>'
                  '<meta itemprop="datePosted" content="Tue Oct 06 00:00:00 UTC 2026">')
        self.use({
            "career.petrosea.com/search/": lambda u, b: ("<p>Tidak ada tabel</p>", "text/html"),
            "career.petrosea.com/sitemap.xml": lambda u, b: (sitemap, "application/xml"),
            "career.petrosea.com/job/": lambda u, b: (detail, "text/html"),
        })
        out = karier.successfactors({"url": "https://career.petrosea.com", "lokasi": ""})
        self.assertEqual([(j["id"], j["title"], j["loc"]) for j in out], [("59988244", "Maintenance Dispatcher DBK", "Murung Raya")])

    def test_radancy(self):
        html = ('<ul><li><a href="https://careers.unilever.com/en/job/medan/manufacturing-manager/34155/101655148176" data-job-id="1">'
                '<h2>Manufacturing Manager</h2><span class="job-location">Medan, North Sumatra</span></a></li></ul>')
        self.use({"careers.unilever.com": lambda u, b: (html if "p=" not in u else "<ul></ul>", "text/html")})
        jobs, _ = karier.fetch_company({"nama": "Unilever Indonesia", "ats": "radancy", "global": True, "kode": "UNVR",
                                        "url": "https://careers.unilever.com/en/location/indonesia-jobs/34155/1643084/2"}, REFS, now=NOW)
        self.assertEqual(jobs[0]["title"], "Manufacturing Manager")
        self.assertEqual((jobs[0]["city"], jobs[0]["province"]), ("Kota Medan", "Sumatera Utara"))
        self.assertEqual(jobs[0]["id"], "ra-unvr-101655148176")

    def test_jsonld_dan_cache(self):
        listing = ('<a href="/karir/lowongan/teller-1">Teller</a><a href="/karir/lowongan/cs-2">CS</a>'
                   '<a href="/tentang">Tentang</a><a href="https://facebook.com/karir/x">FB</a>')

        def detail(name, city):
            node = {"@context": "https://schema.org", "@type": "JobPosting", "title": name, "datePosted": "2026-10-11",
                    "validThrough": "2026-11-30", "employmentType": "FULL_TIME",
                    "jobLocation": {"@type": "Place", "address": {"addressLocality": city, "addressCountry": "ID"}},
                    "baseSalary": {"currency": "IDR", "value": {"minValue": 5000000, "maxValue": 7000000, "unitText": "MONTH"}}}
            return f'<script type="application/ld+json">{json.dumps({"@graph": [node]})}</script>', "text/html"

        http = self.use({
            "bank.co.id/karir/lowongan/teller-1": lambda u, b: detail("Teller", "Surabaya"),
            "bank.co.id/karir/lowongan/cs-2": lambda u, b: detail("Customer Service", "Bandung"),
            "bank.co.id/karir": lambda u, b: (listing, "text/html"),
        })
        company = {"nama": "Bank Contoh", "ats": "jsonld", "kode": "BCON", "url": "https://bank.co.id/karir", "pola": r"/karir/lowongan/"}
        jobs, raw = karier.fetch_company(company, REFS, now=NOW)
        self.assertEqual(sorted(j["title"] for j in jobs), ["Customer Service", "Teller"])
        teller = next(j for j in jobs if j["title"] == "Teller")
        self.assertEqual((teller["city"], teller["smin"], teller["smax"], teller["type"]), ("Kota Surabaya", 5000000, 7000000, "Full time"))
        self.assertGreater(teller["expires"], teller["posted"])
        # Hari berikutnya: detail yang sudah dikenal tidak diambil ulang.
        known = {j["link"]: j for j in jobs}
        http.calls.clear()
        again, _ = karier.fetch_company(company, REFS, known, now=NOW)
        self.assertEqual(len(again), 2)
        self.assertEqual([c[0] for c in http.calls], ["https://bank.co.id/karir"])


class TestDeskripsi(Base):
    def test_teks_rapi(self):
        html = ('<p><strong>Tanggung jawab:</strong></p><ul><li><p>Membuat laporan</p></li><li>Analisis data</li></ul>'
                '<p>Kualifikasi &amp; syarat</p>')
        self.assertEqual(karier.html_to_text(html), "Tanggung jawab:\n\n\u2022 Membuat laporan\n\u2022 Analisis data\n\nKualifikasi & syarat")
        self.assertEqual(karier.html_to_text("&lt;p&gt;Halo&lt;/p&gt;"), "Halo")
        long = karier.html_to_text("".join(f"<p>Baris ke-{i} tentang tugas dan tanggung jawab.</p>" for i in range(400)))
        self.assertLessEqual(len(long), karier.DESC_LIMIT + 2)
        self.assertTrue(long.endswith("\u2026"))

    def test_workday_deskripsi_lokasi_tipe(self):
        def listing(url, body):
            return {"total": 1, "facets": [], "jobPostings": [
                {"title": "Medical Representative", "externalPath": "/job/Makassar/Medical-Rep_R1", "locationsText": "2 Locations",
                 "postedOn": "Posted Today", "bulletFields": ["R1"]}]}
        self.use({
            "/wday/cxs/kalbe/External/jobs": listing,
            "/wday/cxs/kalbe/External/job/Makassar/Medical-Rep_R1": lambda u, b: {"jobPostingInfo": {
                "jobDescription": "<p>Kunjungi dokter.</p><ul><li>S1 Farmasi</li></ul>", "location": "Makassar",
                "timeType": "Full time"}},
        })
        jobs, _ = karier.fetch_company({"nama": "Kalbe", "ats": "workday", "kode": "KLBF",
                                        "url": "https://kalbe.wd102.myworkdayjobs.com/External"}, REFS, now=NOW)
        self.assertEqual(jobs[0]["desc"], "Kunjungi dokter.\n\n\u2022 S1 Farmasi")
        self.assertEqual((jobs[0]["city"], jobs[0]["type"]), ("Kota Makassar", "Full time"))

    def test_successfactors_lokasi_dari_detail_dan_tidak_diulang(self):
        rows = ('<tr class="data-row"><td><a class="jobTitle-link" href="/job/AVP-Finance/58995944/">AVP Finance</a></td>'
                '<td><span class="jobLocation"></span></td></tr>')
        detail = ('<span itemprop="addressLocality">Jakarta</span><span class="jobdescription"><p>Memimpin tim.</p>'
                  '<ul><li>Minimal 8 tahun</li></ul></span><a class="applylink" href="#">Apply</a>')
        http = self.use({
            "careers.ioh.co.id/search/": lambda u, b: ("<table>" + rows + "</table>", "text/html"),
            "careers.ioh.co.id/job/AVP-Finance/58995944/": lambda u, b: (detail, "text/html"),
        })
        company = {"nama": "PT Indosat Tbk", "ats": "successfactors", "kode": "ISAT", "url": "https://careers.ioh.co.id", "lokasi": ""}
        jobs, _ = karier.fetch_company(company, REFS, now=NOW)
        self.assertEqual(jobs[0]["desc"], "Memimpin tim.\n\n\u2022 Minimal 8 tahun")
        self.assertEqual((jobs[0]["city"], jobs[0]["province"]), ("Jakarta", "DKI Jakarta"))
        # Besok: deskripsi sudah tersimpan, lokasi diambil dari data kemarin, halaman detail tidak dibuka lagi.
        http.calls.clear()
        again, _ = karier.fetch_company(company, REFS, {j["link"]: j for j in jobs}, NOW, {j["id"] for j in jobs})
        self.assertEqual((again[0]["city"], "desc" in again[0]), ("Jakarta", False))
        self.assertEqual(len(http.calls), 1)

    def test_bagian_halaman_tanpa_format_standar(self):
        section = ('<h2>Tentang Pekerjaan</h2><p>Program pengembangan calon pemimpin BCA.</p>'
                   '<h2>Persyaratan</h2><ul><li>S1 semua jurusan</li><li>IPK minimal 3,00</li></ul>'
                   '<h2>Tahapan Seleksi</h2><p>Tes online, wawancara.</p>')
        page = ('<html><head><title>x</title></head><body><nav><a>Beranda</a><a>Lokasi</a></nav>'
                f'<div class="mobile">{section}</div><div class="desktop">{section}</div>'
                '<p>01 Januari 2025 - 31 Desember 2026</p><h3>Lokasi Tes</h3><p>Jakarta</p>'
                '<h3>Lokasi Penempatan</h3><p>Seluruh Indonesia</p><h2>Karir Lainnya</h2><p>Teller</p></body></html>')
        text, extra = karier.text_sections(page)
        self.assertTrue(text.startswith("Tentang Pekerjaan\n\nProgram pengembangan"))
        self.assertIn("\u2022 IPK minimal 3,00", text)
        self.assertEqual(text.count("Tentang Pekerjaan"), 1)  # bagian yang terulang tidak dobel
        self.assertNotIn("Teller", text)
        self.assertEqual(extra["loc"], "Seluruh Indonesia")
        self.assertEqual(extra["expires"], int(datetime(2026, 12, 31, tzinfo=karier.WIB).timestamp()))

    @unittest.skipUnless(HAS_PYPDF, "pypdf tidak terpasang")
    def test_lowongan_pdf_dibaca_isinya(self):
        pdf = tiny_pdf(["Page 1 from 3", "Position:", "Junior Mineral Resources Inventory Geologist",
                        "Work Location: Sorowako", "Purpose of the Role", "Mengelola data sumber daya mineral dan",
                        "inventaris cadangan nikel.", "- S1 Teknik Geologi", "- Pengalaman 0-2 tahun"])
        self.use({"valeindonesia.com/documents/": lambda u, b: (pdf, "application/pdf")})
        text, extra = karier.describe({"ats": "html"}, {"link": "https://www.valeindonesia.com/documents/d/guest/20261009_x", "id": "x"})
        self.assertNotIn("Page 1", text)
        self.assertIn("Mengelola data sumber daya mineral dan inventaris cadangan nikel.", text)  # baris PDF disambung
        self.assertIn("\u2022 S1 Teknik Geologi", text)
        self.assertEqual(extra["loc"], "Sorowako")
        self.assertEqual(karier.place(extra["loc"], REFS), ("Kab. Luwu Timur", "Sulawesi Selatan"))

    def test_pdf_tanpa_pypdf_diberi_catatan(self):
        self.use({"valeindonesia.com/documents/": lambda u, b: (tiny_pdf(["Isi"]), "application/pdf")})
        old, karier.pdf_text = karier.pdf_text, lambda body: ("", {})
        try:
            text, _ = karier.describe({"ats": "html"}, {"link": "https://www.valeindonesia.com/documents/d/guest/x", "id": "x"})
        finally:
            karier.pdf_text = old
        self.assertEqual(text, karier.PDF_NOTE)

    def test_deskripsi_dirapikan(self):
        # Workday Japfa mengirim baris baru sebagai "&amp;#xa;" sehingga dulu tampil "&#xa;" di layar.
        self.assertEqual(karier.html_to_text("<p>Create SO DO Billing &amp;#xa;&amp;#xa;</p><p>JAPFA adalah perusahaan.</p>"),
                         "Create SO DO Billing\n\nJAPFA adalah perusahaan.")
        self.assertEqual(karier.tidy_desc("Create SO DO Billing\n&#xa;&#xa;\n\nJAPFA adalah perusahaan."),
                         "Create SO DO Billing\n\nJAPFA adalah perusahaan.")
        # Hanya judul bagian tanpa isi (Petrosea): dianggap kosong.
        self.assertEqual(karier.tidy_desc("Job Summary\n\nJob Responsibilities\n\nEducation\n\nCertification"), "")
        # Deskripsi pendek tapi berisi tetap disimpan.
        self.assertEqual(karier.tidy_desc("Kualifikasi\n\u2022 S1 Akuntansi\n\u2022 Pengalaman 2 tahun"),
                         "Kualifikasi\n\u2022 S1 Akuntansi\n\u2022 Pengalaman 2 tahun")
        self.assertEqual(karier.tidy_desc("Create SO DO Billing"), "Create SO DO Billing")

    def test_logo_resmi(self):
        home = ('<head><link rel="icon" href="/favicon.ico"><link rel="apple-touch-icon" sizes="180x180" href="/apple-icon.png">'
                '</head><body><img class="site-logo" src="/img/logo-bca.svg"></body>')
        self.use({"www.bca.co.id/apple-icon.png": lambda u, b: png(180, 180),
                  "www.bca.co.id": lambda u, b: (home, "text/html")})
        self.assertEqual(karier.find_logo({"web": "https://www.bca.co.id"}), "https://www.bca.co.id/apple-icon.png")
        self.use({"kecil.co.id": lambda u, b: ('<link rel="icon" href="/favicon.ico">', "text/html")})
        self.assertEqual(karier.find_logo({"web": "https://kecil.co.id"}), "")  # favicon kecil: pakai inisial saja
        self.use({"svg.co.id/icon.svg": lambda u, b: svg("#0060AF"),
                  "svg.co.id": lambda u, b: ('<link rel="icon" type="image/svg+xml" href="/icon.svg">', "text/html")})
        self.assertEqual(karier.find_logo({"web": "https://svg.co.id"}), "https://svg.co.id/icon.svg")

    def test_logo_putih_sosmed_dan_rusak_dilewati(self):
        # Seperti karir.bca.co.id: logo header putih (untuk latar biru), logo berwarna di bagian bawah.
        page = ('<header><img alt="BCA logo" src="/candidate/_nuxt/bca-white.9YHRqfMr.svg"></header>'
                '<a href="https://tiktok.com/@bca"><img class="logo-sosmed" src="/img/tiktok-logo.webp"></a>'
                '<img class="logo" src="/img/logo-rusak.png">'
                '<footer><img alt="BCA logo" src="/candidate/_nuxt/bca-blue.CIusCzFC.svg"></footer>')
        http = self.use({
            "bca-blue": lambda u, b: svg("#0060AF"),
            "logo-rusak.png": lambda u, b: ("<!doctype html><title>404</title>" + " " * 200, "text/html"),
            "karir.bca.co.id": lambda u, b: (page, "text/html"),
        })
        company = {"nama": "PT Bank Central Asia Tbk", "kode": "BBCA", "situs": ["https://karir.bca.co.id/"]}
        self.assertEqual(karier.find_logo(company), "https://karir.bca.co.id/candidate/_nuxt/bca-blue.CIusCzFC.svg")
        self.assertFalse(any("white" in u or "tiktok" in u for u, _ in http.calls))
        self.assertTrue(karier.svg_is_white(svg("#FFFFFF")[0]))
        self.assertTrue(karier.svg_is_white('<svg><g style="fill: rgba(255, 255, 255, 0.9)"><path/></g></svg>'))
        self.assertFalse(karier.svg_is_white('<svg><path d="M0 0"/></svg>'))  # tanpa warna = hitam
        self.assertFalse(karier.svg_is_white('<svg><path fill="#fff"/><path fill="#E31E24"/></svg>'))

    def test_logo_dari_halaman_platform_lowongan(self):
        # Beranda tidak bisa dibuka: logo diambil dari halaman Lever/Greenhouse/SuccessFactors perusahaannya.
        lever = ('<div class="main-header-logo"><a href="https://jobs.lever.co/GoToGroup"><img alt="GoTo Group logo" '
                 'src="https://lever-client-logos.s3.us-west-2.amazonaws.com/ea3dc26a-1682066441676.png"></a></div>'
                 '<img src="https://jobs.lever.co/img/lever-logo-refresh.svg" alt="Lever logo">')
        self.use({
            "www.gotocompany.com": lambda u, b: TimeoutError("timed out"),
            "lever-client-logos": lambda u, b: png(400, 120),
            "jobs.lever.co/GoToGroup": lambda u, b: (lever, "text/html"),
        })
        goto = {"nama": "PT GoTo Gojek Tokopedia Tbk", "ats": "lever", "slug": "GoToGroup", "web": "https://www.gotocompany.com"}
        self.assertEqual(karier.logo_pages(goto), ["https://www.gotocompany.com", "https://jobs.lever.co/GoToGroup"])
        self.assertEqual(karier.find_logo(goto),
                         "https://lever-client-logos.s3.us-west-2.amazonaws.com/ea3dc26a-1682066441676.png")
        # Greenhouse tanpa beranda di perusahaan.json (Xendit).
        board = ('<meta property="og:image" content="https://s3-recruiting.cdn.greenhouse.io/external_greenhouse_job_boards/'
                 'logos/400/368/700/original/Xendit_LogoTextRHS_final.png?1594768204">')
        self.use({"s3-recruiting.cdn.greenhouse.io": lambda u, b: png(600, 200),
                  "job-boards.greenhouse.io/xendit": lambda u, b: (board, "text/html")})
        self.assertIn("Xendit_LogoTextRHS_final.png", karier.find_logo({"nama": "Xendit", "ats": "greenhouse", "slug": "xendit"}))
        # SuccessFactors (Chandra Asri): logo header berformat JPG di rmkcdn.
        rmk = '<a href="/"><img class="logo" src="//rmkcdn.successfactors.com/f48a2531/0516ba0f-a760-4ba3-b8d5-9.jpg" alt=""></a>'
        jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" \
              b"\xff\xc0\x00\x11\x08\x00\x50\x01\x2c\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01" + bytes(120)
        self.use({"www.chandra-asri.com": lambda u, b: TimeoutError("timed out"),
                  "rmkcdn.successfactors.com": lambda u, b: (jpg, "image/jpeg"),
                  "careers.chandra-asri.com": lambda u, b: (rmk, "text/html")})
        self.assertEqual(karier.image_size(jpg), (300, 80))
        self.assertEqual(karier.find_logo({"nama": "PT Chandra Asri Pacific Tbk", "ats": "successfactors", "web": "https://www.chandra-asri.com",
                                           "situs": ["https://careers.chandra-asri.com/"]}),
                         "https://rmkcdn.successfactors.com/f48a2531/0516ba0f-a760-4ba3-b8d5-9.jpg")

    def test_logo_workable_dari_api_akun(self):
        self.use({"api/v1/accounts/indico": lambda u, b: {"name": "INDICO", "logo": "https://workablehr.s3.amazonaws.com/uploads/account/logo/561932/logo"},
                  "workablehr.s3.amazonaws.com": lambda u, b: png(256, 256)})
        self.assertEqual(karier.find_logo({"nama": "INDICO", "ats": "workable", "slug": "indico", "web": "https://indico.id"}),
                         "https://workablehr.s3.amazonaws.com/uploads/account/logo/561932/logo")

    def test_ukuran_gambar(self):
        self.assertEqual(karier.image_size(png(192, 192)[0]), (192, 192))
        ico = b"\x00\x00\x01\x00\x02\x00" + bytes([16, 16]) + bytes(14) + bytes([0, 0]) + bytes(14)
        self.assertEqual(karier.image_size(ico), (256, 256))
        self.assertEqual(karier.brand_words({"nama": "PT Bank Central Asia Tbk", "kode": "BBCA"}) >= {"bca", "central", "asia", "bbca"}, True)

    def test_tipe_disamakan(self):
        self.assertEqual([karier.norm_type(t) for t in ["Permanent", "Direct Contract", "FULL_TIME", "Internship", "Harian"]],
                         ["Full time", "Kontrak", "Full time", "Magang", "Harian"])


class TestHalamanDaftar(Base):
    def test_judul_kartu_lokasi_dan_batas_lamaran(self):
        card = ('<div class="card"><span>Lowongan Kerja</span><h5>{t}</h5><p>Lamar Sebelum {d}.</p>'
                '<a class="btn" href="/jobs/view/{i}">Detil Pekerjaan</a></div>')
        page = "<main>" + card.format(t="BBAP Mantri Muda – BRI Region 10 Semarang", d="Dec 2026, 31", i="ZBPAQe6v") \
            + card.format(t="Relationship Manager Kota Medan", d="Jan 2026, 5", i="old1") + "</main>"
        self.use({"e-recruitment.bri.co.id/jobs": lambda u, b: (page, "text/html")})
        company = {"nama": "BRI", "ats": "html", "kode": "BBRI", "url": "https://e-recruitment.bri.co.id/jobs", "pola": r"/jobs/view/"}
        jobs, raw = karier.fetch_company(company, REFS, now=NOW)
        self.assertEqual(raw, 1)  # yang batas lamarannya sudah lewat dibuang
        self.assertEqual(jobs[0]["title"], "BBAP Mantri Muda – BRI Region 10 Semarang")
        self.assertEqual((jobs[0]["city"], jobs[0]["province"]), ("Kota Semarang", "Jawa Tengah"))
        self.assertEqual(jobs[0]["expires"], int(datetime(2026, 12, 31, tzinfo=karier.WIB).timestamp()))
        self.assertEqual(jobs[0]["id"], "ht-bbri-ZBPAQe6v")

    def test_baris_tabel_dan_tautan_luar(self):
        page = ('<table><tr><th>Posisi</th><th>Lokasi</th><th></th></tr>'
                '<tr><td>Staff Quality Control</td><td>Bogor</td><td><a href="https://id.jobstreet.com/job/89819391">Apply</a></td></tr>'
                '<tr><td>Sales Supervisor</td><td>Surabaya</td><td><a href="https://forms.gle/Tm8">Apply</a></td></tr></table>')
        self.use({"cimory.com/career": lambda u, b: (page, "text/html")})
        jobs, _ = karier.fetch_company({"nama": "Cimory", "ats": "html", "kode": "CMRY", "url": "https://www.cimory.com/career",
                                        "pola": r"jobstreet\.com/(id/)?job/\d+|forms\.gle/"}, REFS, now=NOW)
        self.assertEqual([(j["title"], j["city"]) for j in jobs], [("Staff Quality Control", "Kota Bogor"), ("Sales Supervisor", "Kota Surabaya")])

    def test_judul_dari_pola_teks_dan_umur(self):
        page = ''.join(f'<li><a href="/documents/d/guest/{d.replace("/", "")}_x{i}">&gt; {d} - Job vacancy for {loc} - {t}</a></li>'
                       for i, (d, loc, t) in enumerate([("10/09/2026", "National", "Snr. Geotech Engineer"),
                                                        ("10/06/2026", "East Luwu Regency", "Project Engineer"),
                                                        ("07/02/2026", "National", "Senior Coordinator Legal")]))
        self.use({"valeindonesia.com": lambda u, b: (page, "text/html")})
        company = {"nama": "Vale Indonesia", "ats": "html", "kode": "INCO", "url": "https://www.valeindonesia.com/indonesia/career.html",
                   "pola": r"/documents/d/guest/\d{8}", "format_tanggal": "%m/%d/%Y", "maks_hari": 60,
                   "judul_regex": r"(?P<date>\d{2}/\d{2}/\d{4})\s*-\s*Job vacanc\w* for (?P<loc>.+?)\s+-\s+(?P<title>.+)$"}
        jobs, _ = karier.fetch_company(company, REFS, now=NOW)
        self.assertEqual([j["title"] for j in jobs], ["Snr. Geotech Engineer", "Project Engineer"])
        self.assertEqual(jobs[1]["city"], "Kab. Luwu Timur")
        self.assertEqual(jobs[0]["posted"], int(datetime(2026, 10, 9, tzinfo=karier.WIB).timestamp()))

    def test_judul_dari_halaman_detail_sekali_saja(self):
        page = '<div><a href="/career/672354b8">Learn More</a></div><div><a href="/career/68b55e1b">Learn More</a></div>'
        http = self.use({
            "btpnsyariah.com/career/672354b8": lambda u, b: ("<h1>Community Officer</h1><p>Lokasi: Kupang</p>", "text/html"),
            "btpnsyariah.com/career/68b55e1b": lambda u, b: ("<title>Business Coach | BTPN Syariah</title>", "text/html"),
            "btpnsyariah.com/career": lambda u, b: (page, "text/html"),
        })
        company = {"nama": "BTPN Syariah", "ats": "html", "kode": "BTPS", "url": "https://www.btpnsyariah.com/career",
                   "pola": r"/career/[0-9a-f]{8}"}
        jobs, _ = karier.fetch_company(company, REFS, now=NOW)
        self.assertEqual(sorted(j["title"] for j in jobs), ["Business Coach", "Community Officer"])
        self.assertEqual(next(j for j in jobs if j["title"] == "Community Officer")["city"], "Kota Kupang")
        known = {j["link"]: j for j in jobs}
        http.calls.clear()
        again, _ = karier.fetch_company(company, REFS, known, now=NOW, described={j["id"] for j in jobs})
        self.assertEqual(len(again), 2)
        self.assertEqual(len(http.calls), 1)  # hanya halaman daftar
        self.assertEqual({j["posted"] for j in again}, {j["posted"] for j in jobs})  # tanggal tidak "baru" lagi

    def test_lowongan_tutup_dibuang(self):
        page = ('<div><h4>Banking Staff</h4><span>CLOSED</span><a href="https://jobs.talentics.id/mandiri/banking-staff">Ajukan</a></div>'
                '<div><h4>Officer Development Program</h4><a href="https://jobs.talentics.id/mandiri/odp">Ajukan</a></div>')
        self.use({"bankmandiri.co.id": lambda u, b: (page, "text/html")})
        jobs, _ = karier.fetch_company({"nama": "Mandiri", "ats": "html", "kode": "BMRI", "url": "https://www.bankmandiri.co.id/karir",
                                        "pola": r"jobs\.talentics\.id/mandiri/", "buang": r"\bCLOSED\b"}, REFS, now=NOW)
        self.assertEqual([j["title"] for j in jobs], ["Officer Development Program"])

    def test_tanggal_indonesia(self):
        self.assertEqual(karier.epoch("31 Desember 2026"), int(datetime(2026, 12, 31, tzinfo=karier.WIB).timestamp()))
        self.assertEqual(karier.epoch("5 Agu 2026"), int(datetime(2026, 8, 5, tzinfo=karier.WIB).timestamp()))
        self.assertEqual(karier.epoch("Dec 2026, 31"), int(datetime(2026, 12, 31, tzinfo=karier.WIB).timestamp()))


class TestCek(Base):
    def test_platform_terdeteksi_dan_dicoba(self):
        page = ('<html><head><title>Karir</title><script src="/static/app.js"></script></head>'
                '<body><a href="https://apply.workable.com/contoh/">Lihat lowongan</a></body></html>')
        self.use({
            "contoh.co.id/karir": lambda u, b: (page, "text/html"),
            "contoh.co.id/robots.txt": lambda u, b: ("Sitemap: https://contoh.co.id/sitemap.xml", "text/plain"),
            "contoh.co.id/sitemap.xml": lambda u, b: ("<urlset><url><loc>https://contoh.co.id/karir/lowongan/a</loc></url></urlset>",
                                                       "application/xml"),
            "contoh.co.id/static/app.js": lambda u, b: ('fetch("/api/v1/vacancies?page=1")', "text/javascript"),
            "apply.workable.com/api/v1/widget/accounts/contoh": lambda u, b: {"jobs": [
                {"title": "Admin", "shortcode": "X1", "locations": [{"city": "Jakarta", "country": "Indonesia"}]}]},
        })
        res = karier.check_company({"nama": "Contoh", "kode": "CTOH", "situs": ["https://contoh.co.id/karir"]}, REFS)
        site = res["situs"][0]
        self.assertEqual(site["platform"]["workable"], ["contoh"])
        self.assertIn("/api/v1/vacancies?page=1", site["api_skrip"])
        self.assertEqual(res["sitemap"]["isi"][0]["lowongan"], 1)
        self.assertTrue(res["uji"][0]["ok"])
        self.assertEqual(res["uji"][0]["indonesia"], 1)

    def test_ikuti_tautan_lowongan_dan_coba_kartu(self):
        home = '<a href="/karir/lowongan">Lihat lowongan</a><a href="https://instagram.com/x">IG</a>'
        listing = ''.join(f'<div><h3>{t}</h3><p>Jakarta</p><a href="/karir/lowongan/{i}">Detail</a></div>'
                          for i, t in enumerate(["Teller", "Analis Kredit", "Customer Service"]))
        self.use({
            "bank.co.id/karir/lowongan/": lambda u, b: ("<h1>x</h1>", "text/html"),
            "bank.co.id/karir/lowongan": lambda u, b: (listing, "text/html"),
            "bank.co.id/karir": lambda u, b: (home, "text/html"),
        })
        res = karier.check_company({"nama": "Bank", "kode": "BNK", "situs": ["https://bank.co.id/karir"]}, REFS)
        visited = [e["url"] for e in res["situs"]]
        self.assertIn("https://bank.co.id/karir/lowongan", visited)
        lst = next(e for e in res["situs"] if e["url"].endswith("/karir/lowongan"))
        self.assertEqual(lst["kartu"]["jumlah"], 3)
        self.assertEqual(lst["kartu"]["contoh"][0][0], "Teller")
        trial = next(u for u in res["uji"] if u["ats"] == "html")
        self.assertEqual((trial["ok"], trial["indonesia"]), (True, 3))
        self.assertTrue(lst["cuplikan"])

    def test_situs_gagal_tidak_menghentikan(self):
        self.use({"rusak.co.id": lambda u, b: HTTPError(u, 503, "down", {}, BytesIO())})
        res = karier.check_company({"nama": "Rusak", "situs": ["https://rusak.co.id/karir"]}, REFS)
        self.assertEqual(res["situs"][0]["status"], 503)


class TestPenarikanHarian(Base):
    def test_deskripsi_tersimpan_per_pecahan(self):
        import test_update
        tmp = Path(tempfile.mkdtemp())
        (tmp / "perusahaan.json").write_text(json.dumps([{"nama": "INDICO", "ats": "workable", "slug": "indico"}]))
        jobs_api = [{"title": "Data Engineer", "shortcode": "Z9", "description": "<p>Bangun pipeline data.</p>",
                     "locations": [{"city": "Bandung", "country": "Indonesia"}]}]
        self.use({"widget/accounts/indico": lambda u, b: {"jobs": jobs_api}})
        old_fetch, old_sleep = update.fetch, update.sleep
        update.fetch = test_update.FakeApi([test_update.vacancy(i) for i in range(3)])
        update.sleep = lambda s: None
        try:
            update.run(tmp, now=test_update.NOW)
            name = update.shard("wo-indico-Z9")
            self.assertEqual(json.loads((tmp / "detail" / f"{name}.json").read_text()), {"wo-indico-Z9": {"d": "Bangun pipeline data."}})
            self.assertEqual(json.loads((tmp / "detail" / "_info.json").read_text())["jobs"], 1)
            self.assertNotIn("01a1-0001", update.read_details(tmp))  # lowongan Karirhub tidak disimpan di sini
            jobs_api.clear()  # lowongan ditutup: deskripsinya ikut dibuang
            update.run(tmp, now=test_update.NOW)
            self.assertFalse((tmp / "detail" / f"{name}.json").exists())
            self.assertTrue((tmp / "detail" / "_info.json").exists())
        finally:
            update.fetch, update.sleep = old_fetch, old_sleep

    def test_jadwal_cadangan_hanya_bila_perlu(self):
        tmp = Path(tempfile.mkdtemp())
        at = lambda h, d=20: datetime(2026, 10, d, h, 30, tzinfo=karier.WIB)  # noqa: E731
        (tmp / "jobs.json").write_text(json.dumps({"updated": at(5).isoformat()}))
        self.assertFalse(update.needs_run(tmp, at(7), "schedule"))       # pagi sudah ada
        self.assertTrue(update.needs_run(tmp, at(18), "schedule"))       # malam belum
        self.assertTrue(update.needs_run(tmp, at(7), "workflow_dispatch"))  # manual selalu jalan
        (tmp / "jobs.json").write_text(json.dumps({"updated": at(19).isoformat()}))
        self.assertFalse(update.needs_run(tmp, at(20), "schedule"))
        self.assertFalse(update.needs_run(tmp, at(2, 21), "schedule"))   # lewat tengah malam masih sesi malam
        self.assertTrue(update.needs_run(tmp, at(5, 21), "schedule"))

    def test_deskripsi_kosong_dicoba_lagi_saat_versi_baru(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "detail").mkdir()
        stored = {"a": "", "b": "isi"}
        (tmp / "detail" / "_info.json").write_text(json.dumps({"versi": 1}))
        self.assertEqual(update.described_ids(tmp, stored), {"b"})
        (tmp / "detail" / "_info.json").write_text(json.dumps({"versi": update.DESC_VERSION}))
        self.assertEqual(update.described_ids(tmp, stored), {"a", "b"})

    def test_logo_dicek_ulang_sesuai_jadwal_dan_versi(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "detail").mkdir()
        now_ts = int(NOW.timestamp())
        day = 86400
        cache = {
            "BCA": {"url": "https://bca/logo-bca-white.svg", "t": now_ts - day},                         # aturan lama
            "Kalbe": {"url": "https://kalbe/logo.svg", "t": now_ts - 2 * day, "v": update.LOGO_VERSION},  # masih segar
            "GoTo": {"url": "", "t": now_ts - 2 * day, "v": update.LOGO_VERSION},                         # belum ketemu
            "Vale": {"url": "https://vale/fav.png", "t": now_ts - 9 * day, "v": update.LOGO_VERSION},     # sudah seminggu
        }
        (tmp / "detail" / "_logo.json").write_text(json.dumps(cache))
        found = {"BCA": "https://bca/bca-blue.svg", "GoTo": "https://lever/goto.png", "Vale": ""}
        asked = []
        old_find, old_ok = karier.find_logo, karier.usable_logo
        karier.find_logo = lambda c: asked.append(c["nama"]) or found.get(c["nama"], "")
        karier.usable_logo = lambda url: url == "https://vale/fav.png"  # situs Vale sedang tak bisa dibuka
        try:
            companies = [{"nama": n, "web": f"https://{n.lower()}.co.id"} for n in cache]
            logos = update.resolve_logos(tmp, companies, NOW, active={"GoTo"})
        finally:
            karier.find_logo, karier.usable_logo = old_find, old_ok
        self.assertEqual(sorted(asked), ["BCA", "GoTo", "Vale"])
        self.assertEqual(logos, {"BCA": "https://bca/bca-blue.svg", "Kalbe": "https://kalbe/logo.svg",
                                 "GoTo": "https://lever/goto.png", "Vale": "https://vale/fav.png"})
        saved = json.loads((tmp / "detail" / "_logo.json").read_text())
        self.assertTrue(all(e["v"] == update.LOGO_VERSION for e in saved.values()))

    def test_logo_untuk_nama_lain_di_karirhub(self):
        companies = [{"nama": "PT XLSMART Telecom Sejahtera Tbk", "alias": ["PT XL Axiata Tbk"]}, {"nama": "Tanpa Logo"}]
        names = update.logo_names(companies, {"PT XLSMART Telecom Sejahtera Tbk": "https://xl/logo.png"})
        self.assertEqual(names.get(update.name_key("PT Xl Axiata")), "https://xl/logo.png")
        self.assertEqual(names.get(update.name_key("PT. XLSMART Telecom Sejahtera")), "https://xl/logo.png")
        self.assertNotIn(update.name_key("Tanpa Logo"), names)
        by_name = {update.name_key(n): n for n in ["PT Astra Credit Companies", "PT Bank BTPN Syariah Tbk", "PT Bank Mandiri (Persero) Tbk",
                                                   "PT Bank Central Asia Tbk", "PT Indofood CBP Sukses Makmur Tbk", "PT Erajaya Swasembada Tbk"]}
        cases = {
            "Astra Credit Companies (ACC)": "PT Astra Credit Companies",
            "Astra Credit Companies WTC Mangga Dua": "PT Astra Credit Companies",
            "PT Bank Btpn Syariah, Tbk Kc Padang": "PT Bank BTPN Syariah Tbk",
            "PT. Indofood CBP Sukses Makmur, Tbk - Branch Semarang": "PT Indofood CBP Sukses Makmur Tbk",
            "PT Erajaya Swasembada Tbk (Bali)": "PT Erajaya Swasembada Tbk",
            "Erajaya Swasembada": "PT Erajaya Swasembada Tbk",
            "PT Bank Mandiri Taspen": "",            # anak usaha lain, logonya beda
            "PT Bank Central Asia Syariah": "",      # BCA Syariah bukan BCA
            "PT Mandiri Utama Finance": "",
        }
        self.assertEqual({k: update.logo_for(k, by_name) for k in cases}, cases)

    def test_deskripsi_tersimpan_dirapikan_dan_pdf_dibaca_ulang(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "detail").mkdir()
        (tmp / "detail" / "00.json").write_text(json.dumps({"a": {"d": karier.PDF_NOTE}, "b": {"d": "isi"}}))
        self.assertEqual(update.read_details(tmp), {"b": "isi"})

    def test_logo_perusahaan_juga_untuk_lowongan_karirhub(self):
        import test_update
        tmp = Path(tempfile.mkdtemp())
        (tmp / "perusahaan.json").write_text(json.dumps([
            {"nama": "PT Contoh Jaya Tbk", "web": "https://contoh.co.id", "ats": "workable", "slug": "contoh"}]))
        self.use({
            "contoh.co.id/apple.png": lambda u, b: png(180, 180),
            "contoh.co.id": lambda u, b: ('<link rel="apple-touch-icon" href="/apple.png">', "text/html"),
            "widget/accounts/contoh": lambda u, b: {"jobs": [{"title": "Analis", "shortcode": "A1",
                                                              "locations": [{"city": "Jakarta", "country": "Indonesia"}]}]},
        })
        old_fetch, old_sleep = update.fetch, update.sleep
        update.fetch = test_update.FakeApi([test_update.vacancy(1, company_logo_uri=None)])
        update.sleep = lambda s: None
        try:
            update.run(tmp, now=test_update.NOW)
        finally:
            update.fetch, update.sleep = old_fetch, old_sleep
        data = json.loads((tmp / "jobs.json").read_text())
        logos = dict(zip(data["lists"]["company"], data["lists"]["logo"]))
        self.assertEqual(logos["PT Contoh Jaya Tbk"], "https://contoh.co.id/apple.png")
        self.assertEqual(logos["PT Contoh Jaya"], "https://contoh.co.id/apple.png")  # lowongan Karirhub perusahaan yang sama
        self.assertTrue((tmp / "detail" / "_logo.json").exists())

    def test_perusahaan_ikut_tertarik_dan_gagal_terisolasi(self):
        import test_update
        tmp = Path(tempfile.mkdtemp())
        (tmp / "perusahaan.json").write_text(json.dumps([
            {"nama": "INDICO", "ats": "workable", "slug": "indico"},
            {"nama": "Rusak", "ats": "workable", "slug": "rusak"},
            {"nama": "Belum ada adapter", "kode": "XXXX", "situs": ["https://x.co.id/karir"]},
        ]))
        self.use({"widget/accounts/indico": lambda u, b: {"jobs": [
            {"title": "Data Engineer", "shortcode": "Z9", "locations": [{"city": "Bandung", "country": "Indonesia"}]}]}})
        old_fetch, old_sleep = update.fetch, update.sleep
        update.fetch = test_update.FakeApi([test_update.vacancy(i) for i in range(5)])
        update.sleep = lambda s: None
        try:
            self.assertEqual(update.run(tmp, now=test_update.NOW), 0)
        finally:
            update.fetch, update.sleep = old_fetch, old_sleep
        data = json.loads((tmp / "jobs.json").read_text())
        jobs = update.decode(data)
        self.assertIn("wo-indico-Z9", jobs)
        self.assertEqual(jobs["wo-indico-Z9"]["via"], "workable:indico")
        names = {s["name"]: s for s in data["sources"]}
        self.assertTrue(names["Karier INDICO"]["ok"])
        self.assertFalse(names["Karier Rusak"]["ok"])
        self.assertEqual(names["Karier INDICO"]["jenis"], "perusahaan")
        self.assertNotIn("Karier Belum ada adapter", names)


if __name__ == "__main__":
    unittest.main()
