import test from 'node:test';
import assert from 'node:assert/strict';
import {
  decode, filterJobs, sortJobs, countBy, median, salaryBy, salaryText, juta, ribu, ago, dateText, timeText,
  slug, karirhubUrl, initials, htmlToText, filtersFromQuery, filtersToQuery, activeCount, summarize, cityLabel, tidy, typeLabel, findMajor, majorFilter, MAJORS,
  EMPTY_FILTERS, detailShard, yearsFrom, buildJobSuggestions, buildMajorSuggestions, matchSuggestions, splitMatch, prettyTitle, suggestKey, CATEGORY_BY_KEY, placeLabel
} from './logic.js';

const NOW = 1791943200; // 14 Okt 2026 06.00 WIB

const DATA = {
  v: 1,
  updated: '2026-10-14T06:00:00+07:00',
  sources: [{ name: 'Karirhub Kemnaker', ok: true, count: 4 }],
  logoBase: 'https://kemnaker-assets.oss-accelerate.aliyuncs.com/',
  fields: ['id', 'title', 'company', 'city', 'province', 'platform', 'function', 'industry', 'type', 'edu', 'smin', 'smax', 'posted', 'expires', 'first', 'via'],
  lists: {
    company: ['PT Sinar Jaya', 'Xendit', 'CV Maju Café'],
    logo: ['joss/a.png', '', ''],
    city: ['Kota Bandung', 'Jakarta', 'Kab. Badung'],
    province: ['Jawa Barat', 'DKI Jakarta', 'Bali'],
    platform: ['Glints', 'Karier Xendit', 'JobStreet'],
    function: ['Gudang', 'Teknologi Informasi', 'Juru Masak'],
    industry: ['Logistik', 'Teknologi Finansial', 'Restoran'],
    type: ['Full time', 'Magang', ''],
    edu: ['SMA atau Sederajat', 'Sarjana', ''],
    via: ['karirhub', 'greenhouse:xendit']
  },
  jobs: [
    ['a1', 'Staf Gudang', 0, 0, 0, 0, 0, 0, 0, 0, 4500000, 6000000, NOW - 3600, NOW + 86400 * 30, 20261014, 0],
    ['a2', 'IT GRC Analyst', 1, 1, 1, 1, 1, 1, 0, 2, 0, 0, NOW - 86400 * 3, 0, 20261014, 1],
    ['a3', 'Sous Chef', 2, 2, 2, 2, 2, 2, 1, 1, 9000000, 0, NOW - 86400 * 10, NOW + 86400 * 2, 20261014, 0],
    ['a4', 'Admin Gudang', 0, 0, 0, 2, 0, 0, 0, 1, 0, 3500000, NOW - 7200, NOW + 86400 * 5, 20261014, 0]
  ]
};

const { jobs } = decode(DATA);
const F = (o) => ({ ...EMPTY_FILTERS, types: [], ...o });
const ids = (list) => list.map((j) => j.id);

test('decode memetakan indeks ke nilai', () => {
  const j = jobs[0];
  assert.equal(j.company, 'PT Sinar Jaya');
  assert.equal(j.logo, 'joss/a.png');
  assert.equal(j.province, 'Jawa Barat');
  assert.equal(j.fn, 'Gudang');
  assert.equal(j.eduLevel, 30);
  assert.equal(j.pay, 5250000);
  assert.equal(jobs[1].eduLevel, -1);
  assert.equal(jobs[2].company, 'CV Maju Café');
  assert.deepEqual(decode(null).jobs, []);
  assert.deepEqual(decode({ v: 99 }).jobs, []);
});

test('pencarian kata kunci tanpa peduli huruf & aksen', () => {
  assert.deepEqual(ids(filterJobs(jobs, F({ q: 'gudang' }), NOW)), ['a1', 'a4']);
  assert.deepEqual(ids(filterJobs(jobs, F({ q: 'cafe' }), NOW)), ['a3']);
  assert.deepEqual(ids(filterJobs(jobs, F({ q: 'admin  bandung' }), NOW)), ['a4']);
  assert.deepEqual(ids(filterJobs(jobs, F({ q: 'glints' }), NOW)), ['a1']);
});

test('filter provinsi, kota, bidang, sumber, tipe', () => {
  assert.deepEqual(ids(filterJobs(jobs, F({ prov: 'Jawa Barat' }), NOW)), ['a1', 'a4']);
  assert.deepEqual(ids(filterJobs(jobs, F({ prov: 'Jawa Barat', city: 'Kota Bandung' }), NOW)), ['a1', 'a4']);
  assert.deepEqual(ids(filterJobs(jobs, F({ fn: 'Juru Masak' }), NOW)), ['a3']);
  assert.deepEqual(ids(filterJobs(jobs, F({ src: 'JobStreet' }), NOW)), ['a3', 'a4']);
  assert.deepEqual(ids(filterJobs(jobs, F({ src: '@perusahaan' }), NOW)), ['a2']);
  assert.deepEqual(ids(filterJobs(jobs, F({ types: ['Magang'] }), NOW)), ['a3']);
  assert.deepEqual(ids(filterJobs(jobs, F({ types: ['Magang', 'Full time'] }), NOW)), ['a1', 'a2', 'a3', 'a4']);
});

test('pendidikan saya: tampilkan yang syaratnya sama atau lebih rendah (+ tanpa syarat)', () => {
  assert.deepEqual(ids(filterJobs(jobs, F({ edu: 'sma' }), NOW)), ['a1', 'a2']);
  assert.deepEqual(ids(filterJobs(jobs, F({ edu: 's1' }), NOW)), ['a1', 'a2', 'a3', 'a4']);
});

test('gaji dan waktu posting', () => {
  assert.deepEqual(ids(filterJobs(jobs, F({ gaji: 'ada' }), NOW)), ['a1', 'a3', 'a4']);
  assert.deepEqual(ids(filterJobs(jobs, F({ gaji: '5' }), NOW)), ['a1', 'a3']);
  assert.deepEqual(ids(filterJobs(jobs, F({ gaji: '8' }), NOW)), ['a3']);
  assert.deepEqual(ids(filterJobs(jobs, F({ waktu: '1' }), NOW)), ['a1', 'a4']);
  assert.deepEqual(ids(filterJobs(jobs, F({ waktu: '7' }), NOW)), ['a1', 'a2', 'a4']);
});

test('faset: hitungan provinsi mengabaikan filter provinsi sendiri', () => {
  const f = F({ prov: 'Bali', gaji: 'ada' });
  assert.deepEqual(ids(filterJobs(jobs, f, NOW)), ['a3']);
  assert.deepEqual(countBy(filterJobs(jobs, f, NOW, 'prov'), 'province'), [['Jawa Barat', 2], ['Bali', 1]]);
});

test('urutan', () => {
  assert.deepEqual(ids(sortJobs(jobs, '')), ['a1', 'a4', 'a2', 'a3']);
  assert.deepEqual(ids(sortJobs(jobs, 'gaji')), ['a3', 'a1', 'a4', 'a2']);
  assert.deepEqual(ids(sortJobs(jobs, 'tutup')), ['a3', 'a4', 'a1', 'a2']);
  assert.deepEqual(ids(sortJobs(jobs, 'az')), ['a3', 'a1', 'a4', 'a2']);
});

test('median dan gaji per bidang', () => {
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 0, 2, 3]), 2.5);
  assert.equal(median([]), 0);
  assert.deepEqual(salaryBy(jobs, 'fn', 1), [
    { name: 'Juru Masak', median: 9000000, n: 1 },
    { name: 'Gudang', median: 4375000, n: 2 }
  ]);
  assert.deepEqual(salaryBy(jobs, 'fn', 2), [{ name: 'Gudang', median: 4375000, n: 2 }]);
});

test('format angka & gaji', () => {
  assert.equal(ribu(19568), '19.568');
  assert.equal(ribu(0), '0');
  assert.equal(juta(4500000), '4,5 jt');
  assert.equal(juta(750000), '750 rb');
  assert.equal(salaryText(4500000, 6000000), 'Rp4,5–6 jt');
  assert.equal(salaryText(5000000, 5000000), 'Rp5 jt');
  assert.equal(salaryText(9000000, 0), 'Mulai Rp9 jt');
  assert.equal(salaryText(0, 3500000), 'Hingga Rp3,5 jt');
  assert.equal(salaryText(800000, 1500000), 'Rp800 rb–1,5 jt');
  assert.equal(salaryText(0, 0), '');
});

test('waktu relatif & tanggal WIB', () => {
  assert.equal(ago(NOW - 60, NOW), 'baru saja');
  assert.equal(ago(NOW - 1800, NOW), '30 menit lalu');
  assert.equal(ago(NOW - 3 * 3600, NOW), '3 jam lalu');
  assert.equal(ago(NOW - 30 * 3600, NOW), 'kemarin');
  assert.equal(ago(NOW - 4 * 86400, NOW), '4 hari lalu');
  assert.equal(ago(NOW - 15 * 86400, NOW), '2 minggu lalu');
  assert.equal(ago(1791883269, 1791883269 + 40 * 86400), '13 Okt 2026');
  assert.equal(dateText(1791883269), '13 Okt');
  assert.equal(timeText(1791883269), '16.21');
});

test('tautan Karirhub & slug', () => {
  assert.equal(slug('F&B Supervisor – Pererenan'), 'f-b-supervisor-pererenan');
  assert.equal(karirhubUrl({ via: 'karirhub', title: 'Head Butcher', id: '01a1' }),
    'https://karirhub.kemnaker.go.id/lowongan-dalam-negeri/lowongan/head-butcher-01a1');
  assert.equal(karirhubUrl({ via: 'greenhouse:xendit', title: 'X', id: 'gr-1' }), '');
});

test('inisial, label kota, html ke teks', () => {
  assert.equal(initials('PT Sinar Jaya Abadi'), 'SJ');
  assert.equal(initials('Xendit'), 'X');
  assert.equal(initials(''), '?');
  assert.equal(cityLabel('Kota Jakarta Selatan'), 'Jakarta Selatan');
  assert.equal(cityLabel('Kab. Badung'), 'Kab. Badung');
  assert.equal(htmlToText('<p>&bull; Ramah<br />&bull; Jujur &amp; teliti</p><ul><li>SIM C</li></ul><script>x</script>'),
    '• Ramah\n• Jujur & teliti\n• SIM C\nx');
});

test('label kota, tipe kerja, dan judul huruf besar dirapikan', () => {
  assert.equal(cityLabel('Kota Adm. Jakarta Selatan'), 'Jakarta Selatan');
  assert.equal(cityLabel('Kab. Adm. Kepulauan Seribu'), 'Kab. Kepulauan Seribu');
  assert.equal(cityLabel('Kebayoran Baru'), 'Kebayoran Baru');
  assert.equal(typeLabel('Contract'), 'Kontrak');
  assert.equal(typeLabel('Internship'), 'Magang');
  assert.equal(typeLabel('Full time'), 'Full time');
  assert.equal(tidy('ADMIN MARKETING'), 'Admin Marketing');
  assert.equal(tidy('PT PARAGON TECHNOLOGY AND INNOVATION'), 'PT Paragon Technology and Innovation');
  assert.equal(tidy('LOGISTIK DC and E-COMMERCE BALI'), 'Logistik DC and E-Commerce Bali');
  assert.equal(tidy('DW STEWARD'), 'DW Steward');
  assert.equal(tidy('PT CHAMP RESTO INDONESIA TBK'), 'PT Champ Resto Indonesia Tbk');
  assert.equal(tidy('STAFF ADMIN (SMA/SMK)'), 'Staff Admin (SMA/SMK)');
  assert.equal(tidy('DI JUAL CEPAT'), 'Di Jual Cepat');
  assert.equal(tidy('Sales Executive'), 'Sales Executive');
  assert.equal(tidy('IT Support'), 'IT Support');
  assert.equal(tidy('HRD'), 'HRD');
  assert.equal(tidy('System Analyst REGULATORY REPORTING'), 'System Analyst Regulatory Reporting');
  assert.equal(tidy('Staff HRD & GA (Bekasi)'), 'Staff HRD & GA (Bekasi)');
});

test('upah harian tidak dihitung sebagai gaji bulanan', () => {
  const d = decode({ ...DATA, jobs: [['x', 'TENAGA BONGKAR MUAT', 0, 0, 0, 0, 0, 0, 0, 0, 100000, 132000, NOW, 0, 0, 0]] });
  assert.equal(d.jobs[0].pay, 0);
  assert.equal(d.jobs[0].title, 'Tenaga Bongkar Muat');
});

test('jurusan: cari dari nama, singkatan, dan sebagian nama', () => {
  assert.equal(findMajor('Akuntansi').label, 'Akuntansi');
  assert.equal(findMajor('AKL').label, 'Akuntansi');
  assert.equal(findMajor('tkj').label, 'Teknik Informatika');
  assert.equal(findMajor('IT').label, 'Teknik Informatika');
  assert.equal(findMajor('dkv').label, 'Desain Komunikasi Visual');
  assert.equal(findMajor('tata boga').label, 'Tata Boga & Kuliner');
  assert.equal(findMajor('perhot').label, 'Perhotelan & Pariwisata');
  assert.equal(findMajor('psikologi').label, 'Psikologi & SDM');
  assert.equal(findMajor('xyzzy'), null);
  assert.equal(findMajor('a'), null);
  for (const m of MAJORS) for (const a of m.aka) assert.equal(a, a.toLowerCase(), m.label);
});

test('jurusan: cocok lewat bidang atau kata di judul, bukan potongan kata', () => {
  const job = (title, fn = '') => ({ title, fn, titleFold: title.toLowerCase() });
  const ak = majorFilter('akuntansi');
  assert.ok(ak(job('Staff Accounting')));
  assert.ok(ak(job('Admin', 'Akuntansi & Keuangan')));
  assert.ok(ak(job('Kasir Toko')));
  assert.ok(!ak(job('Sales Executive', 'Penjualan')));
  const ti = majorFilter('TI');
  assert.ok(ti(job('IT Support')));
  assert.ok(ti(job('Backend Developer')));
  assert.ok(!ti(job('Waitress')), 'kata "it" di dalam kata lain tidak ikut');
  assert.ok(!ti(job('Admin Kitchen')));
  const boga = majorFilter('tata boga');
  assert.ok(boga(job('Cook Helper')));
  assert.ok(boga(job('Head Chef')));
  assert.ok(boga(job('Kitchen Staff')));
  assert.ok(!boga(job('Admin Gudang', 'Logistik')));
  // Teks bebas yang bukan jurusan: dicocokkan ke judul.
  const bebas = majorFilter('barista');
  assert.ok(bebas(job('Barista Kopi')));
  assert.ok(!bebas(job('Kasir')));
  assert.equal(majorFilter(''), null);
});

test('filter jurusan ikut di filterJobs dan URL', () => {
  assert.deepEqual(ids(filterJobs(jobs, F({ jur: 'Teknik Informatika' }), NOW)), ['a2']);
  assert.deepEqual(ids(filterJobs(jobs, F({ jur: 'tata boga' }), NOW)), ['a3']);
  assert.deepEqual(ids(filterJobs(jobs, F({ jur: 'gudang' }), NOW)), ['a1', 'a4']);
  const qs = filtersToQuery(F({ jur: 'Akuntansi', prov: 'Bali' }));
  assert.equal(qs, '?jur=Akuntansi&prov=Bali');
  assert.equal(filtersFromQuery(qs).jur, 'Akuntansi');
  assert.equal(activeCount(F({ jur: 'Akuntansi' })), 1);
});

test('filter <-> URL', () => {
  const f = F({ q: 'admin', prov: 'Jawa Barat', types: ['Full time', 'Magang'], gaji: '5' });
  const qs = filtersToQuery(f);
  assert.equal(qs, '?q=admin&prov=Jawa+Barat&gaji=5&tipe=Full+time%2CMagang');
  assert.deepEqual(filtersFromQuery(qs), f);
  assert.equal(filtersToQuery(F({})), '');
  assert.equal(activeCount(f), 4);
});

test('ringkasan pasar', () => {
  const s = summarize(jobs, NOW);
  assert.deepEqual(s, { total: 4, companies: 3, fresh: 2, salariedPct: 75, medianPay: 5250000, provinces: 3 });
});

test('pecahan deskripsi sama dengan update.py', () => {
  // Nilai dari update.shard() di Python untuk id yang sama.
  assert.equal(detailShard('su-isat-58995944'), 'e5');
  assert.equal(detailShard('wo-indico-AB12CD'), 'bc');
  assert.equal(detailShard('le-GoToGroup-1e6eb820'), '67');
});

test('lama pengalaman dari teks lowongan', () => {
  assert.equal(yearsFrom('Minimal 3 tahun pengalaman di bidang keuangan'), 3);
  assert.equal(yearsFrom('At least 5+ years of experience in data'), 5);
  assert.equal(yearsFrom('2 years of relevant experience'), 2);
  assert.equal(yearsFrom('Fresh graduate are welcome'), 0);
  assert.equal(yearsFrom('Menguasai Excel'), null);
});

test('saran jurusan hanya yang melanjutkan ketikan', () => {
  const items = buildMajorSuggestions();
  const labels = (q) => matchSuggestions(items, q).map((i) => i.label);
  const ek = labels('ek');
  assert.equal(ek[0], 'Ekonomi & Perbankan');
  assert.ok(ek.includes('Ekonomi Pembangunan') && ek.includes('Ekonomi Syariah'));
  assert.ok(ek.every((l) => l.startsWith('Ekonomi')));  // "teknik" (ek di tengah kata) dan "Teknik Eksplorasi" tidak ikut
  assert.ok(labels('stat').includes('Statistika'));
  assert.ok(!labels('stat').includes('Statistics'));  // nama Inggris tidak ditawarkan
  assert.ok(labels('tata').includes('Tata Rias'));
  assert.deepEqual(labels('ekonomi pem'), ['Ekonomi Pembangunan']);
  assert.equal(labels('dkv')[0], 'DKV');
  assert.equal(matchSuggestions(items, 'dkv')[0].sub, 'Desain Komunikasi Visual');
  // Kata kedua yang diawali ketikan tetap boleh, tapi di belakang yang diawali ketikan.
  const kom = labels('kom');
  assert.equal(kom[0], 'Komunikasi');
  assert.ok(kom.indexOf('Ilmu Komunikasi') > kom.indexOf('Komputerisasi Akuntansi'));
  assert.deepEqual(labels('xyz'), []);
  assert.deepEqual(labels('  '), []);
});

test('saran posisi dan perusahaan dari lowongan aktif', () => {
  const jobs = [
    { title: 'SALES ADMINISTRATOR - CF LENGKONG', company: 'PT Japfa Comfeed Indonesia Tbk' },
    { title: 'Sales Administrator', company: 'PT Japfa Comfeed Indonesia Tbk' },
    { title: 'Admin Gudang (Urgent)', company: 'CV Maju Jaya' },
    { title: 'Staff Admin', company: 'PT Bank Central Asia Tbk' },
    { title: 'Teknisi AC', company: 'PT Bank Central Asia Tbk' }
  ];
  const items = buildJobSuggestions(jobs);
  const sales = matchSuggestions(items, 'sales');
  assert.equal(sales[0].label, 'Sales Administrator');  // tulisan huruf kecil dipilih, keterangan lokasi dibuang
  assert.equal(sales[0].count, 2);
  assert.deepEqual(matchSuggestions(items, 'admin').map((i) => i.label), ['Admin Gudang', 'Sales Administrator', 'Staff Admin']);
  assert.deepEqual(matchSuggestions(items, 'ad').map((i) => i.label), ['Admin Gudang']);  // 2 huruf: hanya dari awal nama
  // Bentuk badan usaha tidak menghalangi: "bank" dan "pt bank" sama-sama ketemu.
  assert.equal(matchSuggestions(items, 'bank')[0].label, 'PT Bank Central Asia Tbk');
  assert.equal(matchSuggestions(items, 'pt bank')[0].label, 'PT Bank Central Asia Tbk');
  assert.equal(matchSuggestions(items, 'bank')[0].count, 2);
  assert.ok(!matchSuggestions(items, 'ek').length);  // "teknisi" tidak diawali "ek"
  const junk = buildJobSuggestions([{ title: 'Kasir', company: 'Gedung Mal Ciputra Lt.P-1 Jl. Arteri S. Parman Rt. 011, Kota Adm. Jakarta Barat' }]);
  assert.deepEqual(matchSuggestions(junk, 'adm'), []);  // nama berisi alamat: tidak cocok di tengah
  const bri = buildJobSuggestions([{ title: 'Teller', company: 'PT Bank Rakyat Indonesia' }]);
  assert.equal(matchSuggestions(bri, 'rakyat')[0].label, 'PT Bank Rakyat Indonesia');
  assert.deepEqual(matchSuggestions(bri, 'ra'), []);  // terlalu pendek untuk cocok di tengah nama perusahaan
  const limited = matchSuggestions(items, 'admin', { total: 3, perKind: { posisi: 1, perusahaan: 1 } });
  assert.equal(limited.length, 3);  // jatah yang tidak terpakai diisi jenis lain
});

test('judul kapital dirapikan dan bagian cocok ditebalkan', () => {
  assert.equal(prettyTitle('STAFF IT & HRD'), 'Staff IT & HRD');
  assert.equal(prettyTitle('Admin Gudang'), 'Admin Gudang');
  assert.equal(suggestKey('Ekonomi & Perbankan'), 'ekonomi perbankan');
  assert.deepEqual(splitMatch('Ekonomi & Perbankan', 'ek'), ['', 'Ek', 'onomi & Perbankan']);
  assert.deepEqual(splitMatch('Ilmu Komunikasi', 'kom'), ['Ilmu ', 'Kom', 'unikasi']);
  assert.deepEqual(splitMatch('PT Bank Central Asia Tbk', 'bank cen'), ['PT ', 'Bank Cen', 'tral Asia Tbk']);
});

test('kategori fresh graduate dan MT memakai label hasil pemeriksaan deskripsi', () => {
  const fresh = CATEGORY_BY_KEY.get('fresh').test;
  const mt = CATEGORY_BY_KEY.get('mt').test;
  const job = (o) => ({ fn: '', titleFold: '', coFold: '', indFold: '', type: '', tags: 0, ...o });
  // Sudah diperiksa: label yang menentukan, bukan judul.
  assert.equal(fresh(job({ tags: 5, titleFold: 'staff admin' })), true);
  assert.equal(fresh(job({ tags: 4, titleFold: 'fresh graduate sales', fn: 'Fresh Graduate' })), false);
  assert.equal(mt(job({ tags: 6, titleFold: 'odp bank' })), true);
  assert.equal(mt(job({ tags: 4, titleFold: 'management trainee' })), false);
  // Belum diperiksa: bidang dari sumber atau judul.
  assert.equal(fresh(job({ fn: 'Fresh Graduate' })), true);
  assert.equal(mt(job({ titleFold: 'management trainee 2026' })), true);
  assert.equal(CATEGORY_BY_KEY.get('bumn').test(job({ coFold: 'pt bina karya (persero)' })), true);
});

test('lokasi nasional ditampilkan "Seluruh Indonesia"', () => {
  assert.equal(placeLabel({ city: '', province: '', tags: 12 }), 'Seluruh Indonesia');
  assert.equal(placeLabel({ city: '', province: '', tags: 4 }), 'Indonesia');
  assert.equal(placeLabel({ city: 'Kota Adm. Jakarta Selatan', province: 'DKI Jakarta', tags: 0 }, true), 'Jakarta Selatan, DKI Jakarta');
});
