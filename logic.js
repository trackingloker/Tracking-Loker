// Tracking Loker: fungsi murni (tanpa DOM) untuk membaca data, menyaring, dan meringkas lowongan.
// Diuji di logic.test.mjs.

export const KARIRHUB_WEB = 'https://karirhub.kemnaker.go.id';
export const KARIRHUB_DETAIL_API = 'https://api.kemnaker.go.id/karirhub/vacancy/v2/published-industrial-vacancies/';

const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const HARI = 86400;

// Jenjang dari API Karirhub (/v1/educations). SMA dan SMK setara.
export const EDU_LEVEL = {
  'Tidak Tamat SD/Tidak Sekolah': 0,
  'SD atau Sederajat': 10,
  'SMP atau Sederajat': 20,
  'SMA atau Sederajat': 30,
  'SMK': 30,
  'Diploma': 40,
  'Profesi': 50,
  'Sarjana': 50,
  'Magister': 60,
  'Doktoral': 80
};

export const EDU_SHORT = {
  'Tidak Tamat SD/Tidak Sekolah': 'Tanpa ijazah',
  'SD atau Sederajat': 'SD',
  'SMP atau Sederajat': 'SMP',
  'SMA atau Sederajat': 'SMA',
  'SMK': 'SMK',
  'Diploma': 'Diploma',
  'Profesi': 'Profesi',
  'Sarjana': 'S1',
  'Magister': 'S2',
  'Doktoral': 'S3'
};

export const EDU_CHOICES = [
  { key: '', label: 'Semua', level: Infinity },
  { key: 'smp', label: 'SD/SMP', level: 20 },
  { key: 'sma', label: 'SMA/SMK', level: 30 },
  { key: 'd3', label: 'Diploma', level: 40 },
  { key: 's1', label: 'S1', level: 50 },
  { key: 's2', label: 'S2/S3', level: 80 }
];

export const GAJI_CHOICES = [
  { key: '', label: 'Semua', min: 0 },
  { key: 'ada', label: 'Dicantumkan', min: 1 },
  { key: '3', label: '≥ 3 jt', min: 3e6 },
  { key: '5', label: '≥ 5 jt', min: 5e6 },
  { key: '8', label: '≥ 8 jt', min: 8e6 },
  { key: '12', label: '≥ 12 jt', min: 12e6 }
];

export const WAKTU_CHOICES = [
  { key: '', label: 'Kapan saja', days: 0 },
  { key: '1', label: '24 jam', days: 1 },
  { key: '3', label: '3 hari', days: 3 },
  { key: '7', label: '7 hari', days: 7 },
  { key: '30', label: '30 hari', days: 30 }
];

export const SORTS = [
  { key: '', label: 'Terbaru' },
  { key: 'gaji', label: 'Gaji tertinggi' },
  { key: 'tutup', label: 'Segera ditutup' },
  { key: 'az', label: 'Perusahaan A–Z' }
];

export const DIRECT = '@perusahaan';

export const EMPTY_FILTERS = Object.freeze({
  q: '', jur: '', prov: '', city: '', fn: '', types: [], edu: '', gaji: '', waktu: '', src: '', sort: ''
});

// ---------- Jurusan ----------
// Karirhub tidak mencantumkan jurusan secara rapi, jadi jurusan dicocokkan lewat bidang pekerjaan (fns)
// dan kata kunci di judul lowongan (kw). aka = nama lain yang mungkin diketik pengguna (termasuk jurusan SMK).
export const MAJORS = [
  { label: 'Akuntansi', aka: ['akuntansi', 'accounting', 'akuntan', 'perpajakan', 'pajak', 'akl', 'akuntansi keuangan lembaga', 'komputerisasi akuntansi'],
    fns: ['Akuntansi & Keuangan', 'Akuntan Perpajakan', 'Audit Intern / Pengawasan', 'Keuangan, Analis', 'Penggajian dan Fasilitas'],
    kw: ['akuntan', 'accounting', 'accountant', 'finance', 'keuangan', 'pajak', 'tax', 'audit', 'auditor', 'kasir', 'cashier', 'payroll', 'bookkeeping', 'treasury'] },
  { label: 'Manajemen', aka: ['manajemen', 'management', 'administrasi bisnis', 'bisnis', 'manajemen bisnis', 'business'],
    fns: ['Manajemen Operasional', 'Management Trainee', 'Penjualan dan Pengembangan Bisnis', 'Manajemen Merk / Produk', 'Manajemen Proyek', 'Pengembangan Produk', 'Procurement', 'Pembelian / Purchasing'],
    kw: ['management trainee', 'manager', 'manajer', 'business development', 'operasional', 'operations', 'purchasing', 'procurement', 'project officer'] },
  { label: 'Ekonomi & Perbankan', aka: ['ekonomi', 'perbankan', 'ekonomi pembangunan', 'keuangan dan perbankan', 'banking', 'ekonomi syariah', 'perbankan syariah'],
    fns: ['Operasi Perbankan', 'Kredit / Pinjaman', 'Keuangan, Analis', 'Investasi dan Keuangan', 'Ahli Ekonomi', 'Sekuritas, Trader', 'Kolektor'],
    kw: ['bank', 'banking', 'teller', 'kredit', 'credit', 'financial', 'collection', 'collector', 'relationship officer', 'funding'] },
  { label: 'Teknik Informatika', aka: ['teknik informatika', 'informatika', 'ilmu komputer', 'sistem informasi', 'it', 'ti', 'teknologi informasi', 'rpl', 'rekayasa perangkat lunak', 'tkj', 'teknik komputer jaringan', 'teknik komputer', 'computer science'],
    fns: ['IT', 'TI, Network Engineer', 'Teknik, Perangkat Lunak', 'TI, Administrator', 'TI, Systems Analyst', 'TI, Web Developer', 'TI, Programmer', 'Pemrosesan Data', 'Teknik, Jaringan', 'Teknik, Perangkat Keras'],
    kw: ['developer', 'programmer', 'software', 'it support', 'it staff', 'data analyst', 'data scientist', 'data engineer', 'network', 'web', 'frontend', 'front end', 'backend', 'back end', 'fullstack', 'full stack', 'devops', 'sysadmin', 'qa engineer', 'tester', 'helpdesk', 'it'] },
  { label: 'Desain Komunikasi Visual', aka: ['dkv', 'desain komunikasi visual', 'desain grafis', 'desain', 'design', 'multimedia', 'animasi', 'desain produk', 'seni rupa'],
    fns: ['Design', 'Desainer Grafis Komputer', 'Juru Gambar', 'Fotografer'],
    kw: ['desain', 'design', 'designer', 'desainer', 'graphic', 'grafis', 'ui', 'ux', 'ilustrator', 'illustrator', 'video editor', 'videografer', 'videographer', 'fotografer', 'photographer', 'animator', 'motion', 'content creator', 'multimedia'] },
  { label: 'Ilmu Komunikasi', aka: ['ilmu komunikasi', 'komunikasi', 'jurnalistik', 'hubungan masyarakat', 'humas', 'public relations', 'penyiaran', 'broadcasting'],
    fns: ['Marketing dan Relasi Publik', 'Hubungan Masyarakat', 'Komunikasi', 'Penulis / Media & Jurnalisme / Percetakan dan Penerbitan', 'Editor', 'Reporter', 'Penyiar, TV / Radio', 'Pemasaran Internet'],
    kw: ['public relation', 'humas', 'content', 'copywriter', 'social media', 'jurnalis', 'journalist', 'reporter', 'editor', 'media', 'host', 'presenter', 'announcer', 'komunikasi', 'communication'] },
  { label: 'Pemasaran', aka: ['pemasaran', 'marketing', 'bisnis daring dan pemasaran', 'bdp', 'digital marketing', 'manajemen pemasaran'],
    fns: ['Penjualan dan Pemasaran', 'Pemasaran (Non-Teknis)', 'Pemasaran (Teknis)', 'Pemasaran Internet', 'Telemarketing', 'Merchandiser', 'Penjualan (Non-Teknis)', 'Penjualan (Teknis)'],
    kw: ['marketing', 'pemasaran', 'sales', 'digital marketing', 'brand', 'telemarketing', 'merchandiser', 'promotor', 'spg', 'spb'] },
  { label: 'Teknik Mesin', aka: ['teknik mesin', 'mesin', 'mechanical', 'teknik pemesinan', 'tp', 'teknik pengelasan', 'mekatronika'],
    fns: ['Teknik, Mesin', 'Maintenance', 'Manufaktur dan Produksi', 'Operator'],
    kw: ['mesin', 'mechanical', 'mekanik', 'mechanic', 'maintenance', 'teknisi mesin', 'welder', 'welding', 'las', 'cnc', 'machinist', 'operator produksi', 'mekatronika'] },
  { label: 'Teknik Otomotif', aka: ['otomotif', 'teknik otomotif', 'tkr', 'teknik kendaraan ringan', 'tsm', 'teknik sepeda motor', 'tbsm'],
    fns: [],
    kw: ['mekanik', 'mechanic', 'otomotif', 'automotive', 'bengkel', 'service advisor', 'alat berat', 'heavy equipment', 'body repair', 'spooring'] },
  { label: 'Teknik Elektro', aka: ['teknik elektro', 'elektro', 'electrical', 'elektronika', 'teknik listrik', 'titl', 'teknik instalasi tenaga listrik', 'telekomunikasi'],
    fns: ['Teknik, Elektro', 'Teknik, Telekomunikasi'],
    kw: ['elektro', 'electrical', 'listrik', 'electrician', 'elektronika', 'teknisi elektronik', 'instrument', 'instrumentasi', 'telekomunikasi', 'fiber optic', 'teknisi listrik'] },
  { label: 'Teknik Sipil & Arsitektur', aka: ['teknik sipil', 'sipil', 'civil', 'arsitektur', 'arsitek', 'desain interior', 'interior', 'dpib', 'bangunan', 'konstruksi'],
    fns: ['Teknik, Sipil', 'Arsitek', 'Juru Gambar', 'Manajemen Proyek'],
    kw: ['sipil', 'civil', 'drafter', 'drafting', 'arsitek', 'architect', 'surveyor', 'konstruksi', 'construction', 'site engineer', 'quantity surveyor', 'estimator', 'interior', 'pelaksana'] },
  { label: 'Teknik Industri', aka: ['teknik industri', 'industri', 'industrial engineering', 'manajemen industri'],
    fns: ['Penelitian dan Manajemen Kualitas', 'Quality Control (QC)', 'Manajemen Mutu (ISO)', 'Manajemen Pabrik'],
    kw: ['ppic', 'qc', 'qa', 'quality', 'supervisor produksi', 'production', 'supply chain', 'teknik industri', 'industrial engineer', 'planner', 'inventory control'] },
  { label: 'Kimia', aka: ['kimia', 'teknik kimia', 'kimia analis', 'analis kimia', 'chemistry', 'chemical'],
    fns: ['Teknik, Kimia', 'Laboratorium', 'Quality Control (QC)'],
    kw: ['kimia', 'chemical', 'chemist', 'laboratorium', 'laboratory', 'lab', 'analis lab'] },
  { label: 'Pertambangan & Geologi', aka: ['pertambangan', 'tambang', 'teknik pertambangan', 'geologi', 'teknik geologi', 'perminyakan', 'teknik perminyakan', 'migas', 'mining'],
    fns: ['Teknik, Perminyakan', 'Ahli Geologi'],
    kw: ['tambang', 'mining', 'mine', 'geologi', 'geolog', 'geologist', 'migas', 'oil', 'gas', 'hse', 'k3', 'safety', 'smelter', 'nikel', 'batubara', 'coal'] },
  { label: 'Logistik & Transportasi', aka: ['logistik', 'logistic', 'manajemen logistik', 'transportasi', 'teknik logistik', 'supply chain', 'manajemen transportasi'],
    fns: ['Logistik', 'Operasi Gudang', 'Transportasi', 'Supir', 'Administrasi Export'],
    kw: ['logistik', 'logistic', 'gudang', 'warehouse', 'ekspedisi', 'kurir', 'courier', 'driver', 'supir', 'sopir', 'shipping', 'export', 'import', 'inventory', 'delivery'] },
  { label: 'Psikologi & SDM', aka: ['psikologi', 'sdm', 'manajemen sdm', 'manajemen sumber daya manusia', 'hr', 'hrd', 'human resource'],
    fns: ['SDM', 'Penggajian dan Fasilitas'],
    kw: ['hr', 'hrd', 'human resource', 'recruiter', 'recruitment', 'rekrutmen', 'talent', 'people', 'psikolog', 'psychologist', 'personalia', 'training'] },
  { label: 'Hukum', aka: ['hukum', 'ilmu hukum', 'law', 'syariah', 'hukum bisnis'],
    fns: ['Legal, Konsultasi & Advisori'],
    kw: ['legal', 'hukum', 'lawyer', 'advokat', 'paralegal', 'notaris', 'compliance', 'kepatuhan'] },
  { label: 'Pendidikan', aka: ['pendidikan', 'keguruan', 'fkip', 'pgsd', 'paud', 'pgpaud', 'tarbiyah', 'pendidikan guru', 'bimbingan konseling'],
    fns: ['Edukasi', 'Guru / Tutor', 'Pelatih, Pendidik', 'Kepala Sekolah', 'Pelatih Olahraga', 'Perpustakaan dan Kurator'],
    kw: ['guru', 'teacher', 'tutor', 'pengajar', 'mengajar', 'dosen', 'lecturer', 'instruktur', 'instructor', 'trainer', 'edukator', 'educator', 'pendidik', 'paud', 'tk'] },
  { label: 'Bahasa & Sastra', aka: ['bahasa', 'sastra', 'sastra inggris', 'bahasa inggris', 'pendidikan bahasa inggris', 'sastra jepang', 'bahasa jepang', 'sastra mandarin', 'bahasa mandarin', 'sastra korea', 'english'],
    fns: ['Penerjemah'],
    kw: ['english', 'inggris', 'mandarin', 'chinese', 'japanese', 'jepang', 'korean', 'korea', 'translator', 'penerjemah', 'interpreter', 'bahasa', 'copywriter'] },
  { label: 'Keperawatan & Kebidanan', aka: ['keperawatan', 'perawat', 'ners', 'kebidanan', 'bidan', 'nursing'],
    fns: ['Perawat', 'Bidan', 'Asisten Teknis Kesehatan'],
    kw: ['perawat', 'nurse', 'ners', 'bidan', 'midwife', 'klinik', 'clinic', 'caregiver', 'medis'] },
  { label: 'Farmasi', aka: ['farmasi', 'apoteker', 'pharmacy', 'tenaga teknis kefarmasian', 'ttk', 'farmasi klinis'],
    fns: ['Apoteker / Farmasi'],
    kw: ['apoteker', 'farmasi', 'pharmacist', 'pharmacy', 'kefarmasian', 'ttk', 'apotek'] },
  { label: 'Kedokteran', aka: ['kedokteran', 'dokter', 'kedokteran gigi', 'dokter gigi', 'kedokteran hewan', 'dokter hewan', 'medical'],
    fns: ['Dokter Gigi', 'Dokter Umum', 'Dokter Spesialis', 'Dokter Hewan'],
    kw: ['dokter', 'doctor', 'dentist', 'drg', 'dokter hewan', 'veterinarian'] },
  { label: 'Kesehatan Masyarakat & Gizi', aka: ['kesehatan masyarakat', 'kesmas', 'gizi', 'ilmu gizi', 'analis kesehatan', 'teknologi laboratorium medis', 'radiologi', 'fisioterapi', 'k3', 'keselamatan kerja'],
    fns: ['Laboratorium', 'Asisten Teknis Kesehatan', 'Teknik, Keselamatan'],
    kw: ['gizi', 'nutrisi', 'nutritionist', 'ahli gizi', 'radiografer', 'radiographer', 'fisioterapis', 'physiotherapist', 'analis kesehatan', 'laboratorium', 'hse', 'k3', 'safety'] },
  { label: 'Perhotelan & Pariwisata', aka: ['perhotelan', 'hotel', 'pariwisata', 'hospitality', 'usaha perjalanan wisata', 'upw', 'tourism'],
    fns: ['Operasi Hotel', 'Tour & Travel', 'Operasi Restoran', 'Resepsionis'],
    kw: ['hotel', 'front office', 'front desk', 'housekeeping', 'receptionist', 'resepsionis', 'tour', 'travel', 'guest', 'concierge', 'bellboy', 'waiter', 'waitress', 'server', 'villa', 'resort', 'spa'] },
  { label: 'Tata Boga & Kuliner', aka: ['tata boga', 'boga', 'kuliner', 'culinary', 'perhotelan kuliner', 'pastry', 'seni kuliner', 'kulinari'],
    fns: ['Juru Masak', 'Makanan dan Minuman', 'Operasi Restoran'],
    kw: ['cook', 'chef', 'koki', 'kitchen', 'dapur', 'pastry', 'baker', 'bakery', 'barista', 'bartender', 'juru masak', 'commis', 'cook helper', 'butcher'] },
  { label: 'Pertanian & Peternakan', aka: ['pertanian', 'agribisnis', 'agroteknologi', 'agronomi', 'peternakan', 'perikanan', 'kehutanan', 'teknologi pangan', 'agriculture'],
    fns: ['Teknik, Pertanian', 'Peternakan', 'Dokter Hewan'],
    kw: ['pertanian', 'agronomi', 'agronomist', 'agri', 'perkebunan', 'kebun', 'plantation', 'peternakan', 'farm', 'perikanan', 'kehutanan', 'sawit', 'pangan', 'food technologist'] },
  { label: 'Administrasi Perkantoran', aka: ['administrasi perkantoran', 'administrasi', 'otkp', 'mplb', 'manajemen perkantoran', 'sekretaris', 'kesekretariatan', 'administrasi niaga', 'administrasi publik'],
    fns: ['Administrasi & Customer Relationship', 'Sekretaris', 'Bagian Umum', 'Resepsionis', 'Layanan Pelanggan'],
    kw: ['admin', 'administrasi', 'administration', 'sekretaris', 'secretary', 'resepsionis', 'receptionist', 'data entry', 'office', 'customer service', 'staff umum', 'general affair'] },
  { label: 'Tata Busana & Fashion', aka: ['tata busana', 'busana', 'fashion', 'desain mode', 'tekstil'],
    fns: ['Pembuat Pola', 'Model Fashion'],
    kw: ['fashion', 'busana', 'jahit', 'penjahit', 'tailor', 'garment', 'pola', 'pattern', 'tekstil', 'textile'] },
  { label: 'Pelayaran', aka: ['pelayaran', 'nautika', 'teknika', 'kepelautan', 'perkapalan', 'teknik perkapalan'],
    fns: ['Awak Kapal Laut'],
    kw: ['kapal', 'nautika', 'pelaut', 'seaman', 'deck', 'abk', 'vessel', 'marine', 'port captain', 'port engineer'] }
];

/** Cari jurusan dari teks ketikan pengguna (nama, singkatan, atau sebagian nama). */
export function findMajor(text) {
  const t = fold(text);
  if (!t) return null;
  const exact = MAJORS.find((m) => fold(m.label) === t || m.aka.includes(t));
  if (exact) return exact;
  if (t.length < 3) return null;
  return MAJORS.find((m) => fold(m.label).startsWith(t) || m.aka.some((a) => a.startsWith(t))) || null;
}

const majorCache = new Map();
/** Fungsi penyaring untuk satu jurusan. Teks yang bukan jurusan dikenal dicocokkan ke judul + bidang. */
export function majorFilter(text) {
  const t = fold(text);
  if (!t) return null;
  if (majorCache.has(t)) return majorCache.get(t);
  const m = findMajor(t);
  let fn;
  if (m) {
    const fns = new Set(m.fns);
    const esc = (k) => fold(k).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`(^|[^a-z0-9])(${m.kw.map(esc).join('|')})(?![a-z0-9])`);
    fn = (j) => fns.has(j.fn) || re.test(j.titleFold);
  } else {
    const tokens = t.split(' ').filter(Boolean);
    fn = (j) => tokens.every((tok) => j.titleFold.includes(tok) || fold(j.fn).includes(tok));
  }
  majorCache.set(t, fn);
  return fn;
}

export function fold(text) {
  return String(text || '')
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/\s+/g, ' ').trim();
}

/** "Kota Adm. Jakarta Selatan" -> "Jakarta Selatan", "Kab. Badung" tetap. */
export function cityLabel(city) {
  return String(city || '')
    .replace(/^Kota\s+(Adm\.?\s+|Administrasi\s+)?/i, '')
    .replace(/^Kab(upaten)?\.?\s+(Adm\.?\s+|Administrasi\s+)?/i, 'Kab. ')
    .trim();
}

// Tipe kerja dari sumber kadang berbahasa Inggris.
const TYPE_NAMES = {
  contract: 'Kontrak', internship: 'Magang', intern: 'Magang', daily: 'Harian',
  'full-time': 'Full time', 'part-time': 'Part time'
};
export function typeLabel(type) {
  const t = String(type || '').trim();
  return TYPE_NAMES[t.toLowerCase()] || t;
}

// Gaji di bawah ini hampir pasti upah harian/per paket, bukan gaji bulanan.
export const MIN_MONTHLY = 500000;

// Singkatan yang tetap huruf besar saat judul HURUF BESAR dirapikan.
const KEEP_UPPER = new Set(['PT', 'CV', 'UD', 'PD', 'IT', 'HR', 'HRD', 'GA', 'CS', 'SPG', 'SPB', 'SPV', 'QC', 'QA', 'DC',
  'B2B', 'B2C', 'F&B', 'BUMN', 'BUMD', 'SMA', 'SMK', 'SMP', 'SD', 'D3', 'S1', 'S2', 'KBA', 'UI', 'UX', 'CEO', 'CFO', 'COO',
  'CTO', 'PIC', 'SEO', 'CRM', 'ERP', 'SAP', 'K3', 'HSE', 'PPIC', 'TU', 'RS', 'RSU', 'TK', 'PAUD', 'MD', 'AR', 'AP', 'PR',
  'KOL', 'TV', 'ATM', 'DW', 'OB', 'IOS', 'AI', 'BPR', 'BPJS', 'NPWP', 'SIM', 'ID', 'JNE', 'JNT', 'MCU', 'OTR', 'HVAC']);
const KEEP_LOWER = new Set(['dan', 'di', 'ke', 'dari', 'untuk', 'yang', 'atau', 'and', 'of', 'the', 'for', 'in', 'at', 'with', '&']);

/** "ADMIN MARKETING" -> "Admin Marketing", "PT INDOMOBIL PRIMA NIAGA" -> "PT Indomobil Prima Niaga". */
export function tidy(text) {
  const s = String(text || '').trim();
  const letters = s.replace(/[^A-Za-z]/g, '');
  if (letters.length < 4) return s;
  if ((s.match(/[A-Z]/g) || []).length < letters.length * 0.8) {
    // Judul campuran ("System Analyst REGULATORY REPORTING"): rapikan kata HURUF BESAR yang panjang saja.
    return s.replace(/\b[A-Z]{5,}\b/g, (w) => (KEEP_UPPER.has(w) ? w : w[0] + w.slice(1).toLowerCase()));
  }
  const fix = (part, isFirst) => {
    const bare = part.replace(/^[("'[]+|[)"'\],.:;!]+$/g, '');
    if (!bare) return part;
    const up = bare.toUpperCase();
    if (up === 'TBK') return part.replace(/TBK/i, 'Tbk');
    if (KEEP_UPPER.has(up) || /\d/.test(bare)) return part;
    if (!isFirst && KEEP_LOWER.has(bare.toLowerCase())) return part.toLowerCase();
    return part.toLowerCase().replace(/[a-zÀ-ɏ]/, (c) => c.toUpperCase());
  };
  let first = true;
  return s.split(/(\s+)/).map((word) => {
    if (/^\s+$/.test(word)) return word;
    const out = word.split(/([/-])/).map((seg, i) => (/^[/-]$/.test(seg) ? seg : fix(seg, first && i === 0))).join('');
    first = false;
    return out;
  }).join('');
}

/** Baca jobs.json (format ringkas dari update.py) menjadi daftar objek. */
export function decode(data) {
  const empty = { jobs: [], updated: null, sources: [], logoBase: '' };
  if (!data || data.v !== 1) return empty;
  const fields = data.fields || [];
  const lists = data.lists || {};
  const at = (name) => fields.indexOf(name);
  const pick = (row, name) => {
    const idx = row[at(name)];
    const list = lists[name] || [];
    return typeof idx === 'number' && idx < list.length ? list[idx] : '';
  };
  const jobs = (data.jobs || []).map((row) => {
    const companyIdx = row[at('company')];
    const job = {
      id: row[at('id')],
      title: tidy(row[at('title')]),
      company: tidy(pick(row, 'company')),
      logo: (lists.logo || [])[companyIdx] || '',
      city: pick(row, 'city'),
      province: pick(row, 'province'),
      platform: pick(row, 'platform'),
      fn: pick(row, 'function'),
      industry: pick(row, 'industry'),
      type: typeLabel(pick(row, 'type')),
      edu: pick(row, 'edu'),
      smin: monthly(row[at('smin')]),
      smax: monthly(row[at('smax')]),
      posted: row[at('posted')] || 0,
      expires: row[at('expires')] || 0,
      first: row[at('first')] || 0,
      via: pick(row, 'via')
    };
    job.eduLevel = job.edu in EDU_LEVEL ? EDU_LEVEL[job.edu] : -1;
    job.pay = salaryMid(job);
    job.titleFold = fold(job.title);
    job.hay = fold([job.title, job.company, cityLabel(job.city), job.province, job.fn, job.industry, job.platform].join(' '));
    return job;
  });
  return { jobs, updated: data.updated || null, sources: data.sources || [], logoBase: data.logoBase || '' };
}

function monthly(n) {
  return n >= MIN_MONTHLY ? n : 0;
}

export function salaryMid(job) {
  if (job.smin && job.smax) return (job.smin + job.smax) / 2;
  return job.smin || job.smax || 0;
}

/** Saring lowongan. `skip` dipakai untuk hitungan per pilihan (faset): abaikan satu filter. */
export function filterJobs(jobs, f, ref, skip = '') {
  const tokens = fold(f.q).split(' ').filter(Boolean);
  const edu = EDU_CHOICES.find((c) => c.key === f.edu);
  const gaji = GAJI_CHOICES.find((c) => c.key === f.gaji);
  const waktu = WAKTU_CHOICES.find((c) => c.key === f.waktu);
  const since = waktu && waktu.days ? ref - waktu.days * HARI : 0;
  const types = new Set(f.types || []);
  const jur = f.jur ? majorFilter(f.jur) : null;
  return jobs.filter((j) => {
    if (skip !== 'jur' && jur && !jur(j)) return false;
    if (skip !== 'prov' && f.prov && j.province !== f.prov) return false;
    if (skip !== 'city' && skip !== 'prov' && f.city && j.city !== f.city) return false;
    if (skip !== 'fn' && f.fn && j.fn !== f.fn) return false;
    if (skip !== 'src' && f.src) {
      // '@perusahaan' = semua lowongan yang ditarik langsung dari situs karier perusahaan.
      if (f.src === DIRECT ? j.via === 'karirhub' : j.platform !== f.src) return false;
    }
    if (skip !== 'types' && types.size && !types.has(j.type)) return false;
    if (skip !== 'edu' && edu && edu.key && j.eduLevel > edu.level) return false;
    if (skip !== 'gaji' && gaji && gaji.min) {
      if (gaji.min === 1 ? !j.pay : Math.max(j.smin, j.smax) < gaji.min) return false;
    }
    if (skip !== 'waktu' && since && j.posted < since) return false;
    for (const t of tokens) if (!j.hay.includes(t)) return false;
    return true;
  });
}

export function sortJobs(list, sort) {
  const out = list.slice();
  if (sort === 'gaji') out.sort((a, b) => Math.max(b.smin, b.smax) - Math.max(a.smin, a.smax) || b.posted - a.posted);
  else if (sort === 'tutup') out.sort((a, b) => (a.expires || Infinity) - (b.expires || Infinity) || b.posted - a.posted);
  else if (sort === 'az') out.sort((a, b) => a.company.localeCompare(b.company, 'id') || b.posted - a.posted);
  else out.sort((a, b) => b.posted - a.posted);
  return out;
}

/** [[nilai, jumlah], ...] urut terbanyak. Nilai kosong diabaikan. */
export function countBy(list, key, limit = 0) {
  const map = new Map();
  for (const j of list) {
    const v = typeof key === 'function' ? key(j) : j[key];
    if (!v) continue;
    map.set(v, (map.get(v) || 0) + 1);
  }
  const out = [...map].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), 'id'));
  return limit ? out.slice(0, limit) : out;
}

export function median(values) {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b);
  if (!v.length) return 0;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/** Median gaji per kelompok, hanya kelompok dengan minimal `minN` lowongan bergaji. */
export function salaryBy(list, key, minN = 5, limit = 10) {
  const groups = new Map();
  for (const j of list) {
    if (!j.pay || !j[key]) continue;
    if (!groups.has(j[key])) groups.set(j[key], []);
    groups.get(j[key]).push(j.pay);
  }
  return [...groups]
    .filter(([, v]) => v.length >= minN)
    .map(([name, v]) => ({ name, median: median(v), n: v.length }))
    .sort((a, b) => b.median - a.median)
    .slice(0, limit);
}

export function ribu(n) {
  return Math.round(n || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/** 4500000 -> "4,5 jt", 750000 -> "750 rb". */
export function juta(n) {
  if (n >= 1e9) return `${trim(n / 1e9)} M`;
  if (n >= 1e6) return `${trim(n / 1e6)} jt`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} rb`;
  return String(n);
}

function trim(x) {
  const r = Math.round(x * 10) / 10;
  return String(r).replace('.', ',');
}

export function salaryText(smin, smax) {
  if (smin && smax && smin !== smax) {
    if (smin >= 1e6 && smax >= 1e6 && smax < 1e9) return `Rp${trim(smin / 1e6)}–${trim(smax / 1e6)} jt`;
    return `Rp${juta(smin)}–${juta(smax)}`;
  }
  if (smin && smax) return `Rp${juta(smin)}`;
  if (smin) return `Mulai Rp${juta(smin)}`;
  if (smax) return `Hingga Rp${juta(smax)}`;
  return '';
}

export function dateText(epoch, withYear = false) {
  if (!epoch) return '';
  const d = new Date((epoch + 7 * 3600) * 1000); // tampilkan dalam WIB
  const base = `${d.getUTCDate()} ${BULAN[d.getUTCMonth()]}`;
  return withYear ? `${base} ${d.getUTCFullYear()}` : base;
}

export function timeText(epoch) {
  const d = new Date((epoch + 7 * 3600) * 1000);
  return `${String(d.getUTCHours()).padStart(2, '0')}.${String(d.getUTCMinutes()).padStart(2, '0')}`;
}

/** Waktu relatif berbahasa Indonesia. `now` dan `epoch` dalam detik. */
export function ago(epoch, now) {
  if (!epoch) return '';
  const s = Math.max(0, now - epoch);
  if (s < 60 * 5) return 'baru saja';
  if (s < 3600) return `${Math.floor(s / 60)} menit lalu`;
  if (s < HARI) return `${Math.floor(s / 3600)} jam lalu`;
  if (s < 2 * HARI) return 'kemarin';
  if (s < 7 * HARI) return `${Math.floor(s / HARI)} hari lalu`;
  if (s < 30 * HARI) return `${Math.floor(s / (7 * HARI))} minggu lalu`;
  return dateText(epoch, true);
}

export function slug(text) {
  return String(text || '').normalize('NFKD').replace(/[^\x00-\x7f]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

export function karirhubUrl(job) {
  if (job.via !== 'karirhub') return '';
  return `${KARIRHUB_WEB}/lowongan-dalam-negeri/lowongan/${slug(job.title)}-${job.id}`;
}

export function initials(name) {
  const words = String(name || '')
    .replace(/\b(PT|CV|Tbk|UD|PD|Persero|Yayasan)\b\.?/gi, '')
    .split(/[\s.,&()-]+/).filter(Boolean);
  if (!words.length) return '?';
  return (words[0][0] + (words[1] ? words[1][0] : '')).toUpperCase();
}

export function hue(text) {
  let h = 0;
  for (const ch of String(text || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h % 6;
}

/** Ubah HTML deskripsi menjadi teks bersih (baris per paragraf/poin). Tanpa DOM. */
/** Nama berkas pecahan deskripsi (00-ff) untuk satu lowongan: FNV-1a 32-bit, sama dengan update.py. */
export function detailShard(id) {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(String(id))) h = Math.imul(h ^ b, 0x01000193) >>> 0;
  return (h & 0xff).toString(16).padStart(2, '0');
}

/** Lama pengalaman minimal (tahun) yang disebut di teks lowongan, atau null. */
export function yearsFrom(text) {
  const t = String(text || '').toLowerCase();
  const m = t.match(/(?:minimal|minimum|min\.?|at least|sekurang-kurangnya|paling sedikit)\s*(\d{1,2})\s*\+?\s*(?:tahun|years?|yrs?)/)
    || t.match(/(\d{1,2})\s*\+?\s*(?:tahun|years?|yrs?)\s*(?:of\s+)?(?:pengalaman|experience|relevant experience|working experience)/);
  if (m) return +m[1];
  return /fresh ?graduate|lulusan baru|tanpa pengalaman|no experience required/.test(t) ? 0 : null;
}

export function htmlToText(html) {
  return String(html || '')
    .replace(/<\s*(br|\/p|\/li|\/div|\/h\d)\s*\/?>/gi, '\n')
    .replace(/<\s*li[^>]*>/gi, '• ')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ').replace(/&bull;/g, '•').replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&[a-z]+;/gi, ' ')
    .split('\n').map((l) => l.replace(/\s+/g, ' ').trim()).filter(Boolean)
    .join('\n');
}

// ---------- Filter <-> URL ----------

const KEYS = ['q', 'jur', 'prov', 'city', 'fn', 'edu', 'gaji', 'waktu', 'src', 'sort'];

export function filtersFromQuery(search) {
  const p = new URLSearchParams(search);
  const f = { ...EMPTY_FILTERS, types: [] };
  for (const k of KEYS) f[k] = p.get(k) || '';
  f.types = (p.get('tipe') || '').split(',').filter(Boolean);
  return f;
}

export function filtersToQuery(f) {
  const p = new URLSearchParams();
  for (const k of KEYS) if (f[k]) p.set(k, f[k]);
  if (f.types && f.types.length) p.set('tipe', f.types.join(','));
  const s = p.toString();
  return s ? `?${s}` : '';
}

export function activeCount(f) {
  let n = 0;
  for (const k of ['jur', 'prov', 'city', 'fn', 'edu', 'gaji', 'waktu', 'src']) if (f[k]) n += 1;
  return n + (f.types || []).length;
}

/** Ringkasan untuk kartu pasar. `ref` = waktu data diperbarui (detik). */
export function summarize(list, ref) {
  const salaried = list.filter((j) => j.pay);
  return {
    total: list.length,
    companies: new Set(list.map((j) => j.company)).size,
    fresh: list.filter((j) => j.posted >= ref - HARI).length,
    salariedPct: list.length ? Math.round((salaried.length / list.length) * 100) : 0,
    medianPay: median(salaried.map((j) => j.pay)),
    provinces: new Set(list.map((j) => j.province).filter(Boolean)).size
  };
}
