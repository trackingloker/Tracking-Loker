"""Uji penarik data dengan respons API tiruan (bentuk sama dengan API Karirhub & Greenhouse)."""

import json
import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import update

PROV_BALI = "c63a30a8-db19-48a3-8782-0680555ae95b"
PROV_JKT = "224c2de4-72b5-4e58-9f20-5f869d68ddab"
CITY_BADUNG = "7ab09331-cc51-4c17-8519-58927f821ffb"
CITY_JAKSEL = "11111111-0000-0000-0000-000000000001"
EDU_SMA = "8520de4a-e87e-4b18-a12a-aa6fb19c9a09"
NOW = datetime(2026, 10, 14, 6, 0, tzinfo=update.WIB)


def vacancy(i, **kw):
    row = {
        "id": f"01a1-{i:04d}",
        "title": f"  Staf   Gudang {i} ",
        "company_name": "PT Contoh Jaya",
        "company_logo_uri": update.LOGO_BASE + f"joss/company/logo-{i}.png",
        "city_name": None,
        "locations": [f"city:{CITY_BADUNG}"],
        "created_at": "2026-10-13 16:21:09",
        "published_at": 1791883269,
        "expires_at": 1797094800,
        "job_type_name": "Full time",
        "job_function_name": "Gudang",
        "industry_name": "Logistik",
        "education_id": EDU_SMA,
        "show_salary": True,
        "min_salary_amount": 4500000,
        "max_salary_amount": 6000000,
        "min_salary_currency": "IDR",
        "platform_name": "Glints",
        "platform_link": f"https://glints.com/id/opportunities/jobs/staf-{i}?utm_campaign=kemnaker&utm_medium=api&ref=x",
    }
    row.update(kw)
    return row


class FakeApi:
    """Meniru endpoint Laravel berhalaman: data + meta.last_page + meta.total."""

    def __init__(self, vacancies, max_limit=100, fail=None, boards=None, details=None):
        self.details = details or {}
        self.vacancies = vacancies
        self.max_limit = max_limit
        self.fail = fail or set()
        self.boards = boards or {}
        self.calls = []

    def page(self, rows, params):
        limit = int(params.get("limit", 18))
        if limit > self.max_limit:
            raise HTTPError("u", 422, "limit terlalu besar", {}, BytesIO())
        page = int(params.get("page", 1))
        chunk = rows[(page - 1) * limit: page * limit]
        last = max(1, -(-len(rows) // limit))
        return {"data": chunk, "meta": {"current_page": page, "last_page": last, "per_page": limit, "total": len(rows)}}

    def __call__(self, url, params=None, **_):
        params = params or {}
        self.calls.append((url, dict(params)))
        for key in self.fail:
            if key in url:
                raise RuntimeError(f"jaringan putus: {key}")
        if url == update.PROVINCES:
            return self.page([{"id": PROV_BALI, "name": "Bali"}, {"id": PROV_JKT, "name": "DKI Jakarta"}], params)
        if url == update.CITIES:
            return self.page([
                {"id": CITY_BADUNG, "province_id": PROV_BALI, "name": "Kab. Badung"},
                {"id": CITY_JAKSEL, "province_id": PROV_JKT, "name": "Kota Jakarta Selatan"},
            ], params)
        if url == update.EDUCATIONS:
            return {"data": [{"id": EDU_SMA, "name": "SMA atau Sederajat", "level": 30}]}
        if url == update.LISTING:
            return self.page(self.vacancies, params)
        if url.startswith(update.LISTING + "/"):
            return {"data": self.details.get(url.rsplit("/", 1)[1], {})}
        for slug, jobs in self.boards.items():
            if url.endswith(f"/boards/{slug}/jobs"):
                return {"jobs": jobs, "meta": {"total": len(jobs)}}
        raise AssertionError(f"URL tak terduga {url}")


class Base(unittest.TestCase):
    def setUp(self):
        self._fetch, self._sleep, self._portals = update.fetch, update.sleep, update.PORTALS
        update.PORTALS = []  # situs info lowongan diuji terpisah dengan respons tiruan (test_karier.TestDisnakerja)
        update.sleep = lambda s: None
        update.log = lambda msg: None
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        update.fetch, update.sleep, update.PORTALS = self._fetch, self._sleep, self._portals

    def use(self, api):
        update.fetch = api
        return api

    def read(self, name):
        return json.loads((self.dir / name).read_text("utf-8"))


class TestPaging(Base):
    def test_semua_halaman_terbaca(self):
        api = self.use(FakeApi([vacancy(i) for i in range(250)]))
        rows, total = update.paged(update.LISTING)
        self.assertEqual(len(rows), 250)
        self.assertEqual(total, 250)
        self.assertEqual(len([c for c in api.calls if c[0] == update.LISTING]), 3)

    def test_ukuran_halaman_turun_bila_ditolak(self):
        self.use(FakeApi([vacancy(i) for i in range(40)], max_limit=18))
        rows, total = update.paged(update.LISTING)
        self.assertEqual((len(rows), total), (40, 40))

    def test_batas_halaman(self):
        self.use(FakeApi([vacancy(i) for i in range(500)]))
        rows, _ = update.paged(update.LISTING, max_pages=2)
        self.assertEqual(len(rows), 200)


class TestNormalisasi(Base):
    refs = {
        "provinces": {PROV_BALI: "Bali", PROV_JKT: "DKI Jakarta"},
        "cities": {CITY_BADUNG: ("Kab. Badung", PROV_BALI)},
        "educations": {EDU_SMA: "SMA atau Sederajat"},
    }

    def test_bidang_utama(self):
        job = update.from_karirhub(vacancy(7), self.refs)
        self.assertEqual(job["title"], "Staf Gudang 7")
        self.assertEqual((job["city"], job["province"]), ("Kab. Badung", "Bali"))
        self.assertEqual(job["edu"], "SMA atau Sederajat")
        self.assertEqual((job["smin"], job["smax"]), (4500000, 6000000))
        self.assertEqual(job["logo"], "joss/company/logo-7.png")
        self.assertEqual(job["link"], "https://glints.com/id/opportunities/jobs/staf-7?ref=x")
        self.assertEqual(job["posted"], 1791883269)

    def test_waktu_wib_bila_tanpa_epoch(self):
        job = update.from_karirhub(vacancy(1, published_at=None), self.refs)
        self.assertEqual(job["posted"], 1791883269)

    def test_gaji_disembunyikan_atau_aneh(self):
        self.assertEqual(update.salary({"show_salary": False, "min_salary_amount": 5e6}), (0, 0))
        self.assertEqual(update.salary({"min_salary_amount": 0, "max_salary_amount": 0}), (0, 0))
        self.assertEqual(update.salary({"min_salary_amount": 5, "max_salary_amount": 7}), (0, 0))
        # Upah harian/per paket (Rp100 rb, Rp132 rb) bukan gaji bulanan.
        self.assertEqual(update.salary({"min_salary_amount": 104000, "max_salary_amount": 300000}), (0, 0))
        self.assertEqual(update.salary({"min_salary_amount": 300000, "max_salary_amount": 4500000}), (0, 4500000))
        self.assertEqual(update.salary({"min_salary": {"amount": 8e6}, "max_salary": {"amount": 5e6}}), (5000000, 8000000))
        self.assertEqual(update.salary({"min_salary_amount": 1000, "max_salary_amount": 2000, "min_salary_currency": "USD"}), (0, 0))

    def test_lokasi_provinsi_saja_dan_tanpa_lokasi(self):
        job = update.from_karirhub(vacancy(2, locations=[f"province:{PROV_JKT}"]), self.refs)
        self.assertEqual((job["city"], job["province"]), ("", "DKI Jakarta"))
        job = update.from_karirhub(vacancy(3, locations=[], city_name="Kota Medan"), self.refs)
        self.assertEqual((job["city"], job["province"]), ("Kota Medan", ""))

    def test_tipe_kerja_bahasa_indonesia(self):
        self.assertEqual(update.from_karirhub(vacancy(1, job_type_name="Contract"), self.refs)["type"], "Kontrak")
        self.assertEqual(update.from_karirhub(vacancy(1, job_type_name="Internship"), self.refs)["type"], "Magang")
        self.assertEqual(update.from_karirhub(vacancy(1, job_type_name="Part time"), self.refs)["type"], "Part time")
        self.assertEqual(update.job_type("Remote"), "Remote")

    def test_lokasi_dari_detail(self):
        refs = {
            "provinces": {PROV_BALI: "Bali", PROV_JKT: "DKI Jakarta"},
            "cities": {CITY_BADUNG: ("Kab. Badung", PROV_BALI), CITY_JAKSEL: ("Kota Adm. Jakarta Selatan", PROV_JKT)},
            "educations": {},
        }
        # Bentuk asli dari API (lowongan berlokasi kota).
        real = {"region": {"regionable_type": "city", "key": "kab-badung-bali", "name": "Kab. Badung, Bali",
                           "regionable": {"code": "5103", "name": "Kab. Badung", "province_id": PROV_BALI}},
                "employer": {"city_id": CITY_BADUNG, "province_id": PROV_BALI}}
        self.assertEqual(update.place_from_detail(real, refs), ("Kab. Badung", "Bali"))
        district = {"region": {"regionable_type": "district", "name": "Kebayoran Baru, Kota Adm. Jakarta Selatan, DKI Jakarta"}}
        self.assertEqual(update.place_from_detail(district, refs), ("Kota Adm. Jakarta Selatan", "DKI Jakarta"))
        by_id = {"region": {"regionable_type": "district", "name": "Kebayoran Baru", "regionable": {"city_id": CITY_JAKSEL}}}
        self.assertEqual(update.place_from_detail(by_id, refs), ("Kota Adm. Jakarta Selatan", "DKI Jakarta"))
        employer_only = {"region": None, "employer": {"province_id": PROV_BALI}}
        self.assertEqual(update.place_from_detail(employer_only, refs), ("", "Bali"))
        self.assertEqual(update.place_from_detail({}, refs), ("", ""))

    def test_baris_rusak_dilewati(self):
        self.assertIsNone(update.from_karirhub({"id": "", "title": "x"}, self.refs))
        self.assertIsNone(update.from_karirhub({"id": "a", "title": "  "}, self.refs))

    def test_adapter_lever_dan_ashby(self):
        prov = {"a": "DKI Jakarta", "b": "Jawa Barat"}
        co = {"nama": "Contoh", "slug": "contoh"}
        lever = {"id": "abc", "text": "Data Analyst", "hostedUrl": "https://jobs.lever.co/contoh/abc",
                 "createdAt": 1791883269000,
                 "categories": {"location": "Jakarta", "commitment": "Full-time", "team": "Data", "allLocations": ["Jakarta"]}}
        job = update.from_board("lever", co, lever, prov)
        self.assertEqual((job["id"], job["city"], job["province"]), ("le-contoh-abc", "Jakarta", "DKI Jakarta"))
        self.assertEqual((job["type"], job["function"], job["posted"]), ("Full time", "Data", 1791883269))
        ashby = {"id": "u1", "title": "Product Designer", "jobUrl": "https://jobs.ashbyhq.com/contoh/u1",
                 "publishedAt": "2026-10-10T03:00:00.000+00:00", "employmentType": "Intern", "department": "Desain",
                 "location": "Singapore", "secondaryLocations": [{"location": "Bandung, Indonesia"}]}
        job = update.from_board("ashby", co, ashby, prov)
        self.assertEqual((job["city"], job["province"], job["type"]), ("Bandung", "Jawa Barat", "Magang"))
        ashby["secondaryLocations"] = []
        self.assertIsNone(update.from_board("ashby", co, ashby, prov))

    def test_lokasi_perusahaan_indonesia(self):
        prov = {"a": "DKI Jakarta", "b": "Bali", "c": "Jawa Barat"}
        self.assertEqual(update.indonesia_place("Bangkok, Thailand; Jakarta, Indonesia", prov), ("Jakarta", "DKI Jakarta"))
        self.assertEqual(update.indonesia_place("Bali, Indonesia", prov), ("Bali", "Bali"))
        self.assertEqual(update.indonesia_place("Remote - Indonesia", prov), ("Remote - Indonesia", ""))
        self.assertEqual(update.indonesia_place("Indonesia", prov), ("", ""))
        self.assertIsNone(update.indonesia_place("Kuala Lumpur, Malaysia; Singapore", prov))
        self.assertIsNone(update.indonesia_place("Solothurn, Switzerland", prov))


class TestRun(Base):
    def board(self):
        return {"xendit": [
            {"id": 1, "title": "IT GRC Analyst", "location": {"name": "Jakarta, Indonesia"},
             "absolute_url": "https://job-boards.greenhouse.io/xendit/jobs/1", "first_published": "2026-10-01T10:00:00-04:00"},
            {"id": 2, "title": "Merchant Support", "location": {"name": "Bangkok, Thailand"},
             "absolute_url": "https://job-boards.greenhouse.io/xendit/jobs/2", "updated_at": "2026-10-03T23:26:29-04:00"},
        ]}

    def companies(self):
        (self.dir / "perusahaan.json").write_text(json.dumps([{"nama": "Xendit", "ats": "greenhouse", "slug": "xendit"}]))

    def test_dua_hari_berturut(self):
        self.companies()
        self.use(FakeApi([vacancy(i) for i in range(30)], boards=self.board()))
        self.assertEqual(update.run(self.dir, now=NOW), 0)

        data = self.read("jobs.json")
        self.assertEqual(len(data["jobs"]), 31)
        self.assertIn("Karier Xendit", data["lists"]["platform"])
        jobs = update.decode(data)
        x = jobs["gr-xendit-1"]
        self.assertEqual((x["city"], x["province"], x["company"]), ("Jakarta", "DKI Jakarta", "Xendit"))
        self.assertEqual(x["first"], 20261014)
        self.assertRegex(jobs["01a1-0003"]["logo"], r"^joss/company/logo-\d+\.png$")  # satu logo per perusahaan
        links = self.read("links.json")
        self.assertEqual(links["gr-xendit-1"], "https://job-boards.greenhouse.io/xendit/jobs/1")
        day1 = self.read("stats.json")["days"][-1]
        self.assertEqual((day1["active"], day1["new"], day1["closed"]), (31, None, None))

        # Hari kedua: lowongan 0-4 ditutup, 30-31 baru.
        self.use(FakeApi([vacancy(i) for i in range(5, 32)], boards=self.board()))
        update.run(self.dir, now=datetime(2026, 10, 15, 6, 0, tzinfo=update.WIB))
        jobs = update.decode(self.read("jobs.json"))
        self.assertEqual(len(jobs), 28)
        self.assertNotIn("01a1-0000", jobs)
        self.assertEqual(jobs["01a1-0010"]["first"], 20261014)
        self.assertEqual(jobs["01a1-0031"]["first"], 20261015)
        days = self.read("stats.json")["days"]
        self.assertEqual([d["d"] for d in days], ["2026-10-14", "2026-10-15"])
        self.assertEqual((days[-1]["new"], days[-1]["closed"]), (2, 5))
        self.assertIn("01a1-0010", self.read("links.json"))

    def test_dua_penarikan_sehari_menjumlahkan_baru_dan_ditutup(self):
        self.use(FakeApi([vacancy(i) for i in range(10)]))
        update.run(self.dir, now=NOW)
        day2 = datetime(2026, 10, 15, 5, 13, tzinfo=update.WIB)
        self.use(FakeApi([vacancy(i) for i in range(2, 12)]))      # pagi: 2 baru, 2 ditutup
        update.run(self.dir, now=day2)
        self.use(FakeApi([vacancy(i) for i in range(2, 13)]))      # cadangan: 1 baru lagi
        update.run(self.dir, now=day2.replace(hour=7, minute=37))
        days = self.read("stats.json")["days"]
        self.assertEqual([d["d"] for d in days], ["2026-10-14", "2026-10-15"])
        self.assertEqual((days[-1]["new"], days[-1]["closed"], days[-1]["active"]), (3, 2, 11))

    def test_sumber_gagal_tidak_menghapus_data_lama(self):
        self.use(FakeApi([vacancy(i) for i in range(10)]))
        update.run(self.dir, now=NOW)
        self.use(FakeApi([], fail={"published-industrial-vacancies"}))
        self.assertEqual(update.run(self.dir, now=NOW), 1)
        self.assertEqual(len(self.read("jobs.json")["jobs"]), 10)

    def test_karirhub_sebagian_tidak_menutup_lowongan(self):
        self.companies()
        self.use(FakeApi([vacancy(i) for i in range(300)], boards=self.board()))
        update.run(self.dir, now=NOW)
        # Hanya 1 halaman (100 dari 300) yang terbaca: lowongan lain tetap dianggap aktif.
        self.use(FakeApi([vacancy(i) for i in range(300)], boards=self.board()))
        update.run(self.dir, max_pages=1, now=NOW)
        self.assertEqual(len(self.read("jobs.json")["jobs"]), 301)

    def test_lowongan_kedaluwarsa_dibuang(self):
        self.use(FakeApi([vacancy(1), vacancy(2, expires_at=1700000000)]))
        update.run(self.dir, now=NOW)
        ids = [r[0] for r in self.read("jobs.json")["jobs"]]
        self.assertEqual(ids, ["01a1-0001"])

    def test_referensi_gagal_tetap_jalan(self):
        self.use(FakeApi([vacancy(1)], fail={"/cities", "/provinces", "/educations"}))
        self.assertEqual(update.run(self.dir, now=NOW), 0)
        job = update.decode(self.read("jobs.json"))["01a1-0001"]
        self.assertEqual((job["city"], job["edu"]), ("", ""))

    def test_lokasi_kecamatan_dilengkapi_sekali(self):
        rows = [vacancy(1, locations=["district:abc"], city_name="Kebayoran Baru", platform_name="Karirhub"),
                vacancy(2, locations=["district:def"], city_name="Antah Berantah", platform_name="Karirhub"),
                vacancy(3)]
        details = {"01a1-0001": {"region": {"name": "Kebayoran Baru, Kota Jakarta Selatan, DKI Jakarta"}},
                   "01a1-0002": {"region": {"name": "Antah Berantah"}}}
        api = self.use(FakeApi(rows, details=details))
        update.run(self.dir, now=NOW)
        jobs = update.decode(self.read("jobs.json"))
        self.assertEqual((jobs["01a1-0001"]["city"], jobs["01a1-0001"]["province"]), ("Kota Jakarta Selatan", "DKI Jakarta"))
        self.assertEqual((jobs["01a1-0002"]["city"], jobs["01a1-0002"]["province"]), ("Antah Berantah", ""))
        self.assertEqual(self.read("jobs.json")["checked"], ["01a1-0002"])
        self.assertEqual(len([c for c in api.calls if c[0].startswith(update.LISTING + "/")]), 2)
        # Hari berikutnya: tidak ada detail yang diminta ulang.
        api = self.use(FakeApi(rows, details=details))
        update.run(self.dir, now=NOW)
        self.assertEqual([c for c in api.calls if c[0].startswith(update.LISTING + "/")], [])
        self.assertEqual(update.decode(self.read("jobs.json"))["01a1-0001"]["province"], "DKI Jakarta")

    def test_urut_terbaru(self):
        self.use(FakeApi([vacancy(1, published_at=100), vacancy(2, published_at=300), vacancy(3, published_at=200)]))
        update.run(self.dir, now=datetime(1970, 1, 2, tzinfo=update.WIB))
        self.assertEqual([r[0] for r in self.read("jobs.json")["jobs"]], ["01a1-0002", "01a1-0003", "01a1-0001"])


if __name__ == "__main__":
    unittest.main()


# Uji situs karier perusahaan (karier.py) ikut berjalan lewat "python3 -m unittest test_update" di GitHub Actions.
from test_karier import (  # noqa: E402,F401
    TestApiPublik, TestCek, TestDeskripsi, TestDisnakerja, TestHalamanDaftar, TestHalamanHtml, TestLokasi, TestPenarikanHarian, TestWorkday,
)
