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
// Sumber yang bukan situs karier perusahaan sendiri.
const PORTAL_VIAS = new Set(['karirhub', 'disnakerja']);
export const isCompanySite = (j) => !PORTAL_VIAS.has(j.via);

export const EMPTY_FILTERS = Object.freeze({
  q: '', jur: '', kat: '', prov: '', city: '', fn: '', types: [], edu: '', gaji: '', waktu: '', src: '', sort: ''
});

// ---------- Kategori ----------
// Sama dengan karier.TAG_* di penarik data.
export const TAG_FRESH = 1;
export const TAG_MT = 2;
export const TAG_CHECKED = 4;
export const TAG_NATIONAL = 8;

/** Lokasi untuk ditampilkan: kota, atau provinsi, atau "Seluruh Indonesia" bila penempatannya nasional. */
export function placeLabel(job, full = false) {
  const city = cityLabel(job.city);
  const text = full ? [city, job.province].filter(Boolean).join(', ') : city || job.province;
  return text || (job.tags & TAG_NATIONAL ? 'Seluruh Indonesia' : 'Indonesia');
}
// Seperti menu Disnakerja (MT/ODP, BUMN, Instansi, Palm Oil, Mining, Oil & Gas, Manufaktur, Fresh Graduate, Intern),
// tapi berlaku untuk lowongan dari semua sumber: dilihat dari bidang, industri, nama perusahaan, dan judul.
const BUMN_NAMES = /(^|[^a-z])(pertamina|pln|telkom indonesia|bank mandiri|bank rakyat indonesia|bank negara indonesia|bank tabungan negara|bank syariah indonesia|pos indonesia|kereta api indonesia|angkasa pura|pelindo|pelabuhan indonesia|garuda indonesia|wijaya karya|waskita karya|adhi karya|hutama karya|pupuk indonesia|pupuk kaltim|pupuk kujang|petrokimia gresik|semen indonesia|aneka tambang|bukit asam|krakatau steel|jasa marga|perusahaan gas negara|bio ?farma|kimia farma|indofarma|asabri|taspen|jamkrindo|askrindo|asuransi jasa indonesia|sucofindo|surveyor indonesia|pindad|pal indonesia|len industri|industri kereta api|dahana|brantas abipraya|nindya karya|danareksa|peruri|perhutani|perkebunan nusantara|ptpn|bulog|pegadaian|permodalan nasional madani|damri|pelni|asdp|airnav|sarinah|biro klasifikasi indonesia|bina karya)(?![a-z])/;
export const CATEGORIES = [
  // MT dan fresh graduate memakai label hasil pemeriksaan deskripsi/kualifikasi saat penarikan (TAG_*). Lowongan yang
  // belum diperiksa memakai bidang dari sumbernya atau judulnya.
  { key: 'mt', label: 'MT / ODP', test: (j) => (j.tags & TAG_CHECKED ? !!(j.tags & TAG_MT) : j.fn === 'Management Trainee'
    || /(^|[^a-z])(management trainee|odp|officer development|graduate (trainee|development) program)(?![a-z])/.test(j.titleFold)) },
  { key: 'bumn', label: 'BUMN', test: (j) => j.indFold === 'bumn' || /\(persero\)|(^|[^a-z])(persero|perum|perumda|bumn)(?![a-z])/.test(j.coFold)
    || BUMN_NAMES.test(j.coFold) },
  { key: 'instansi', label: 'Instansi', test: (j) => j.indFold === 'instansi pemerintah'
    || /^(dinas|kementerian|kementrian|badan|pemerintah|pemkab|pemkot|pemprov|sekretariat|kejaksaan|kepolisian|pengadilan|kantor wilayah|kanwil)(?![a-z])|(^|[^a-z])(rsud|puskesmas|universitas negeri|politeknik negeri)(?![a-z])/.test(j.coFold) },
  { key: 'sawit', label: 'Palm Oil', test: (j) => /sawit|palm|plantation/.test(`${j.indFold} ${j.coFold} ${j.titleFold}`) },
  { key: 'tambang', label: 'Mining', test: (j) => /tambang|mining/.test(j.indFold)
    || /(^|[^a-z])(tambang|pertambangan|mining|mine|nikel|nickel|batubara|coal|smelter)(?![a-z])/.test(`${j.coFold} ${j.titleFold}`) },
  { key: 'migas', label: 'Oil & Gas', test: (j) => /minyak|migas|oil|gas/.test(j.indFold)
    || /(^|[^a-z])(migas|oil (and|&) gas|petroleum|lng|offshore|drilling|pertamina|refinery)(?![a-z])/.test(`${j.coFold} ${j.titleFold}`) },
  { key: 'manufaktur', label: 'Manufaktur', test: (j) => /manufaktur|manufacturing/.test(j.indFold)
    || j.fn === 'Manufaktur dan Produksi' || j.fn === 'Manajemen Pabrik'
    || /(^|[^a-z])(operator produksi|pabrik|factory|manufacturing|manufaktur)(?![a-z])/.test(j.titleFold) },
  { key: 'fresh', label: 'Fresh Graduate', test: (j) => (j.tags & TAG_CHECKED ? !!(j.tags & TAG_FRESH) : j.fn === 'Fresh Graduate'
    || /(^|[^a-z])(fresh ?grad(uate)?s?|lulusan baru)(?![a-z])/.test(j.titleFold)) },
  { key: 'magang', label: 'Intern / Magang', test: (j) => j.type === 'Magang' }
];
export const CATEGORY_BY_KEY = new Map(CATEGORIES.map((c) => [c.key, c]));

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
    kw: ['kapal', 'nautika', 'pelaut', 'seaman', 'deck', 'abk', 'vessel', 'marine', 'port captain', 'port engineer'] },
  { label: 'Matematika & Statistika', aka: ['matematika', 'statistika', 'statistik', 'aktuaria', 'ilmu aktuaria', 'matematika terapan', 'mathematics', 'statistics'],
    fns: ['Pemrosesan Data'],
    kw: ['data analyst', 'analis data', 'data scientist', 'statistician', 'statistik', 'statistika', 'actuary', 'actuarial', 'aktuaris', 'aktuaria', 'risk analyst',
      'business intelligence', 'research analyst', 'quantitative', 'enumerator', 'guru matematika', 'tutor matematika', 'pengajar matematika'] },
  { label: 'Fisika', aka: ['fisika', 'teknik fisika', 'fisika terapan', 'fisika medis', 'physics'],
    fns: ['Laboratorium'],
    kw: ['fisika', 'physics', 'instrumentasi', 'kalibrasi', 'calibration', 'radiasi', 'proteksi radiasi', 'fisikawan medis', 'metrologi', 'guru fisika'] },
  { label: 'Biologi & Bioteknologi', aka: ['biologi', 'bioteknologi', 'mikrobiologi', 'biokimia', 'biologi terapan', 'biology', 'biotechnology'],
    fns: ['Laboratorium'],
    kw: ['biologi', 'biology', 'mikrobiologi', 'microbiology', 'bioteknologi', 'biotechnology', 'kultur jaringan', 'analis mikro', 'qc mikro', 'laboratorium',
      'laboratory', 'analis lab', 'peneliti', 'entomolog', 'guru biologi'] },
  { label: 'Ilmu Sosial & Politik', aka: ['ilmu politik', 'hubungan internasional', 'ilmu pemerintahan', 'sosiologi', 'antropologi', 'kesejahteraan sosial',
    'ilmu sejarah', 'sejarah', 'geografi', 'pembangunan sosial', 'ilmu sosial', 'ilmu sosial dan politik', 'international relations'],
    fns: [],
    kw: ['government relation', 'public affairs', 'community development', 'comdev', 'corporate social responsibility', 'tjsl', 'pemberdayaan', 'fasilitator desa', 'peneliti',
      'researcher', 'enumerator', 'policy', 'kebijakan', 'stakeholder', 'social worker', 'pekerja sosial', 'guru sejarah', 'guru geografi',
      'guru sosiologi', 'guru ips'] },
  { label: 'Studi Agama', aka: ['studi agama', 'studi islam', 'ilmu al quran dan tafsir', 'ilmu al quran', 'tafsir', 'dakwah', 'manajemen dakwah', 'ushuluddin',
    'bimbingan penyuluhan islam', 'perbandingan agama', 'aqidah dan filsafat islam', 'teologi'],
    fns: [],
    kw: ['ustadz', 'ustadzah', 'ustad', 'ustazah', 'guru agama', 'guru ngaji', 'mengaji', 'tahfidz', 'tahfiz', 'al quran', 'pendidikan agama',
      'pembimbing ibadah', 'muthawif', 'pembimbing haji', 'imam masjid', 'marbot'] },
  { label: 'Teknik Lingkungan', aka: ['teknik lingkungan', 'ilmu lingkungan', 'rekayasa lingkungan', 'environmental engineering'],
    fns: ['Teknik, Keselamatan'],
    kw: ['lingkungan', 'environment', 'environmental', 'limbah', 'waste', 'amdal', 'ipal', 'wwtp', 'water treatment', 'pengolahan air', 'sanitasi',
      'sanitation', 'k3l', 'ehs', 'emisi', 'limbah b3'] },
  { label: 'Penerbangan', aka: ['penerbangan', 'teknik penerbangan', 'aeronautika', 'teknik dirgantara', 'aviasi', 'manajemen transportasi udara',
    'teknik pesawat udara', 'pramugari', 'awak kabin', 'kebandarudaraan', 'manajemen bandar udara', 'teknik navigasi udara', 'aircraft maintenance', 'aviation'],
    fns: [],
    kw: ['pilot', 'pramugari', 'pramugara', 'flight attendant', 'cabin crew', 'ground staff', 'ground handling', 'aviation', 'avsec', 'aviation security',
      'aircraft', 'pesawat', 'airline', 'maskapai', 'check in counter', 'apron'] },
  { label: 'Kecantikan & Tata Rias', aka: ['tata kecantikan', 'kecantikan', 'tata rias', 'tata kecantikan kulit dan rambut', 'kecantikan kulit dan rambut',
    'tata rias pengantin', 'kosmetologi', 'estetika', 'cosmetology'],
    fns: [],
    kw: ['beautician', 'beauty advisor', 'beauty consultant', 'terapis', 'therapist', 'makeup artist', 'make up artist', 'mua', 'hairdresser', 'hair stylist',
      'kapster', 'salon', 'nail art', 'nail artist', 'eyelash', 'facial', 'klinik kecantikan', 'skincare', 'spa therapist', 'massage', 'pijat', 'barber',
      'barberman'] },
  { label: 'Olahraga', aka: ['olahraga', 'ilmu keolahragaan', 'keolahragaan', 'ilmu olahraga', 'pendidikan jasmani', 'penjaskes', 'pjkr',
    'kepelatihan olahraga', 'pendidikan kepelatihan olahraga', 'sport science'],
    fns: ['Pelatih Olahraga'],
    kw: ['pelatih', 'personal trainer', 'instruktur senam', 'instruktur renang', 'instruktur gym', 'fitness', 'gym', 'renang', 'swimming', 'lifeguard',
      'olahraga', 'sport', 'atlet', 'guru olahraga', 'guru penjas', 'yoga', 'pilates', 'zumba'] },
  { label: 'Seni, Film & Musik', aka: ['seni musik', 'pendidikan seni musik', 'seni tari', 'seni teater', 'seni pertunjukan', 'film dan televisi',
    'perfilman', 'produksi film', 'broadcasting dan perfilman', 'televisi dan film', 'seni karawitan', 'etnomusikologi', 'penciptaan musik', 'musik'],
    fns: ['Penyiar, TV / Radio'],
    kw: ['musik', 'music', 'musisi', 'musician', 'pianis', 'pianist', 'gitaris', 'drummer', 'vokalis', 'penyanyi', 'singer', 'guru musik', 'guru piano',
      'guru vokal', 'penari', 'dancer', 'koreografer', 'aktor', 'aktris', 'filmmaker', 'film maker', 'sutradara', 'director of photography', 'produser', 'producer',
      'videografer', 'videographer', 'video editor', 'editor video', 'sound engineer', 'audio engineer', 'production assistant'] },
  { label: 'Perpustakaan & Kearsipan', aka: ['ilmu perpustakaan', 'perpustakaan', 'kearsipan', 'ilmu informasi dan perpustakaan', 'perpustakaan dan informasi',
    'manajemen informasi dan dokumentasi', 'kearsipan digital'],
    fns: ['Perpustakaan dan Kurator'],
    kw: ['pustakawan', 'librarian', 'perpustakaan', 'library', 'arsip', 'arsiparis', 'archive', 'archivist', 'kearsipan', 'document control',
      'dokumen kontrol', 'document controller', 'filing'] }
];

// Nama jurusan lain dan kompetensi keahlian SMK, supaya saran ketikan dan pencocokan jurusan lebih lengkap.
const MORE_AKA = {
  'Akuntansi': ['akuntansi syariah', 'akuntansi sektor publik', 'akuntansi perpajakan', 'akuntansi keuangan', 'akuntansi dan keuangan lembaga',
    'keuangan', 'akuntansi bisnis', 'akuntansi manajemen'],
  'Manajemen': ['manajemen keuangan', 'manajemen ritel', 'bisnis ritel', 'bisnis retail', 'bisnis digital', 'kewirausahaan', 'ilmu manajemen',
    'bisnis manajemen', 'manajemen perusahaan', 'bisnis internasional', 'manajemen bisnis internasional', 'manajemen operasional'],
  'Ekonomi & Perbankan': ['ilmu ekonomi', 'ekonomi islam', 'ekonomi bisnis', 'studi pembangunan', 'asuransi', 'manajemen asuransi', 'perbankan dan keuangan',
    'layanan perbankan', 'keuangan syariah', 'manajemen keuangan syariah', 'ekonomi'],
  'Teknik Informatika': ['manajemen informatika', 'sains data', 'data science', 'teknik komputer dan jaringan', 'teknik jaringan komputer dan telekomunikasi',
    'tjkt', 'pengembangan perangkat lunak dan gim', 'pplg', 'sistem informasi jaringan dan aplikasi', 'sija', 'keamanan siber', 'cyber security',
    'teknologi rekayasa perangkat lunak', 'teknik perangkat lunak', 'sistem informasi akuntansi', 'bisnis digital informatika', 'informatika medis'],
  'Desain Komunikasi Visual': ['desain grafika', 'teknik grafika', 'produksi grafika', 'kriya', 'desain dan produksi kriya', 'seni rupa murni',
    'desain interaktif', 'desain grafis multimedia'],
  'Ilmu Komunikasi': ['komunikasi dan penyiaran islam', 'periklanan', 'jurnalisme', 'komunikasi massa', 'manajemen komunikasi', 'produksi siaran'],
  'Pemasaran': ['pemasaran digital', 'komunikasi pemasaran', 'e-commerce', 'manajemen pemasaran digital'],
  'Teknik Mesin': ['teknik manufaktur', 'teknik mesin industri', 'teknik pendingin dan tata udara', 'teknik pendingin', 'tptu', 'teknik pengecoran logam',
    'teknik fabrikasi logam dan manufaktur', 'teknik fabrikasi logam', 'tflm', 'teknik konversi energi', 'teknik perawatan mesin', 'teknik perancangan mesin',
    'teknik mekanik industri', 'teknik perawatan'],
  'Teknik Otomotif': ['teknik kendaraan ringan otomotif', 'tkro', 'teknik bisnis sepeda motor', 'teknik alat berat', 'teknik bodi otomotif',
    'teknik ototronik', 'teknik otomotif elektronik', 'teknik mesin otomotif'],
  'Teknik Elektro': ['teknik elektronika', 'elektronika industri', 'teknik elektronika industri', 'teknik audio video', 'teknik ketenagalistrikan',
    'teknik energi', 'teknik otomasi industri', 'teknik pembangkit tenaga listrik', 'teknik jaringan tenaga listrik', 'teknik elektromedik',
    'elektromedis', 'teknik instrumentasi', 'teknik kontrol', 'teknik tenaga listrik', 'teknik energi terbarukan'],
  'Teknik Sipil & Arsitektur': ['teknik konstruksi gedung', 'teknik bangunan', 'desain pemodelan dan informasi bangunan', 'teknik geodesi', 'geodesi',
    'geomatika', 'teknik geomatika', 'perencanaan wilayah dan kota', 'pwk', 'planologi', 'teknik konstruksi', 'teknik sipil hidro',
    'teknik konstruksi dan perumahan', 'teknik survei dan pemetaan', 'survei dan pemetaan', 'teknik konstruksi jalan dan jembatan'],
  'Teknik Industri': ['teknik manajemen industri', 'manajemen produksi', 'teknik industri pertanian', 'teknik sistem industri'],
  'Kimia': ['kimia industri', 'kimia murni', 'teknik kimia industri', 'kimia analisis', 'kimia analitik', 'teknologi kimia industri', 'analis kimia industri'],
  'Pertambangan & Geologi': ['teknik geofisika', 'geofisika', 'teknik metalurgi', 'metalurgi', 'teknik material', 'teknik material dan metalurgi',
    'geologi pertambangan', 'teknik pengolahan migas', 'teknik produksi migas', 'teknik eksplorasi', 'teknik geologi pertambangan'],
  'Logistik & Transportasi': ['manajemen rantai pasok', 'kepabeanan', 'kepabeanan dan cukai', 'logistik bisnis', 'teknik transportasi', 'transportasi darat',
    'manajemen logistik dan rantai pasok'],
  'Psikologi & SDM': ['msdm', 'psikologi industri', 'psikologi industri dan organisasi', 'manajemen sdm'],
  'Hukum': ['hukum ekonomi syariah', 'hukum keluarga', 'hukum tata negara', 'hukum pidana islam', 'hukum keluarga islam'],
  'Pendidikan': ['pgmi', 'pendidikan anak usia dini', 'bimbingan dan konseling', 'manajemen pendidikan', 'teknologi pendidikan', 'pendidikan agama islam',
    'pendidikan matematika', 'pendidikan biologi', 'pendidikan fisika', 'pendidikan kimia', 'pendidikan ekonomi', 'pendidikan sejarah',
    'pendidikan geografi', 'pendidikan bahasa indonesia', 'pendidikan pancasila dan kewarganegaraan', 'ppkn', 'pendidikan luar sekolah',
    'pendidikan luar biasa', 'pendidikan khusus', 'pendidikan ips', 'pendidikan ipa', 'pendidikan guru sekolah dasar', 'pg paud',
    'pendidikan guru madrasah ibtidaiyah', 'pendidikan teknik informatika', 'pendidikan akuntansi'],
  'Bahasa & Sastra': ['sastra indonesia', 'bahasa dan sastra indonesia', 'sastra arab', 'bahasa arab', 'sastra jerman', 'sastra prancis', 'sastra belanda',
    'sastra cina', 'sastra china', 'linguistik', 'bahasa korea', 'pendidikan bahasa jepang', 'pendidikan bahasa arab', 'pendidikan bahasa mandarin',
    'bahasa dan sastra inggris', 'pendidikan bahasa inggris', 'bahasa dan kebudayaan jepang', 'sastra daerah'],
  'Keperawatan & Kebidanan': ['ilmu keperawatan', 'profesi ners', 'asisten keperawatan', 'asisten keperawatan dan caregiver', 'keperawatan gigi',
    'terapis gigi', 'terapis gigi dan mulut', 'pendidikan profesi bidan', 'pendidikan profesi ners'],
  'Farmasi': ['farmasi klinis dan komunitas', 'profesi apoteker', 'farmasi industri', 'analis farmasi dan makanan', 'kefarmasian', 'farmasi klinis dan komunitas'],
  'Kedokteran': ['pendidikan dokter', 'profesi dokter', 'pendidikan dokter gigi', 'pendidikan dokter hewan'],
  'Kesehatan Masyarakat & Gizi': ['tlm', 'radiodiagnostik', 'teknik radiodiagnostik dan radioterapi', 'kesehatan lingkungan', 'rekam medis',
    'perekam medis', 'rekam medis dan informasi kesehatan', 'rmik', 'administrasi rumah sakit', 'manajemen rumah sakit',
    'keselamatan dan kesehatan kerja', 'kesehatan dan keselamatan kerja', 'okupasi terapi', 'terapi wicara', 'akupunktur', 'teknik gigi',
    'dietisien', 'promosi kesehatan', 'epidemiologi', 'teknologi bank darah', 'ortotik prostetik'],
  'Perhotelan & Pariwisata': ['manajemen perhotelan', 'akomodasi perhotelan', 'perhotelan dan jasa pariwisata', 'usaha layanan pariwisata', 'ulp',
    'divisi kamar', 'manajemen pariwisata', 'destinasi pariwisata', 'manajemen kapal pesiar', 'mice', 'manajemen event', 'usaha perjalanan wisata'],
  'Tata Boga & Kuliner': ['patiseri', 'seni kuliner dan pengolahan', 'kuliner perhotelan', 'tata hidang', 'manajemen tata boga', 'culinary art', 'seni kuliner'],
  'Pertanian & Peternakan': ['agroekoteknologi', 'agrikultur', 'agribisnis tanaman', 'agribisnis ternak', 'agribisnis tanaman pangan dan hortikultura', 'atph',
    'agribisnis perikanan', 'budidaya perairan', 'akuakultur', 'ilmu kelautan', 'teknologi hasil pertanian', 'teknologi hasil perikanan',
    'teknologi industri pertanian', 'ilmu dan teknologi pangan', 'ilmu tanah', 'proteksi tanaman', 'hortikultura', 'perkebunan', 'agrobisnis',
    'ilmu peternakan', 'nutrisi dan teknologi pakan', 'kesehatan hewan', 'agribisnis pengolahan hasil pertanian', 'manajemen sumberdaya perairan',
    'pemanfaatan sumberdaya perikanan', 'budidaya tanaman perkebunan'],
  'Administrasi Perkantoran': ['manajemen perkantoran dan layanan bisnis', 'otomatisasi dan tata kelola perkantoran', 'administrasi kantor',
    'ilmu administrasi negara', 'administrasi negara', 'ilmu administrasi publik', 'ilmu administrasi', 'administrasi bisnis perkantoran'],
  'Tata Busana & Fashion': ['desain fashion', 'desain fesyen', 'desain dan produksi busana', 'kriya tekstil', 'teknik tekstil', 'kimia tekstil', 'produksi garmen'],
  'Pelayaran': ['nautika kapal niaga', 'teknika kapal niaga', 'nautika kapal penangkap ikan', 'teknika kapal penangkap ikan', 'ketatalaksanaan pelayaran',
    'manajemen pelabuhan', 'teknik kelautan', 'teknik sistem perkapalan', 'transportasi laut', 'kepelabuhanan']
};
for (const m of MAJORS) {
  for (const a of MORE_AKA[m.label] || []) if (!m.aka.includes(a)) m.aka.push(a);
}

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
      via: pick(row, 'via'),
      tags: at('tags') >= 0 ? +row[at('tags')] || 0 : 0
    };
    job.eduLevel = job.edu in EDU_LEVEL ? EDU_LEVEL[job.edu] : -1;
    job.pay = salaryMid(job);
    job.titleFold = fold(job.title);
    job.coFold = fold(job.company);
    job.indFold = fold(job.industry);
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
  const kat = CATEGORY_BY_KEY.get(f.kat);
  return jobs.filter((j) => {
    if (skip !== 'jur' && jur && !jur(j)) return false;
    if (skip !== 'kat' && kat && !kat.test(j)) return false;
    if (skip !== 'prov' && f.prov && j.province !== f.prov) return false;
    if (skip !== 'city' && skip !== 'prov' && f.city && j.city !== f.city) return false;
    if (skip !== 'fn' && f.fn && j.fn !== f.fn) return false;
    if (skip !== 'src' && f.src) {
      // '@perusahaan' = semua lowongan yang ditarik langsung dari situs karier perusahaan.
      if (f.src === DIRECT ? !isCompanySite(j) : j.platform !== f.src) return false;
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

const KEYS = ['q', 'jur', 'kat', 'prov', 'city', 'fn', 'edu', 'gaji', 'waktu', 'src', 'sort'];

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
  for (const k of ['jur', 'kat', 'prov', 'city', 'fn', 'edu', 'gaji', 'waktu', 'src']) if (f[k]) n += 1;
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

// ---------------------------------------------------------------- saran ketikan

/** Kunci pencocokan saran: huruf kecil tanpa aksen, tanda baca jadi spasi. */
export function suggestKey(text) {
  return fold(text).replace(/[^a-z0-9]+/g, ' ').trim();
}

const SMALL_WORDS = new Set(['dan', 'di', 'ke', 'of', 'and', 'the', 'for', 'to', 'in', 'on', 'at', '&']);
const ACRONYMS = new Set(['it', 'ti', 'hr', 'hrd', 'ga', 'gm', 'qc', 'qa', 'qhse', 'hse', 'ehs', 'k3', 'ppic', 'spg', 'spb', 'mt', 'cs', 'crm',
  'seo', 'sem', 'ui', 'ux', 'sap', 'erp', 'pic', 'smk', 'sma', 'smp', 's1', 's2', 'd3', 'd4', 'abk', 'b2b', 'b2c', 'kol', 'ai', 'api', 'ios',
  'vp', 'avp', 'svp', 'ceo', 'cfo', 'cto', 'coo', 'pm', 'po', 'qs', 'mep', 'cnc', 'plc', 'sop', 'ojt', 'bd', 'r&d', 'rnd', 'apd', 'atm', 'cctv',
  'dkv', 'rpl', 'tkj', 'tkr', 'tsm', 'tbsm', 'titl', 'tp', 'dpib', 'akl', 'bdp', 'otkp', 'mplb', 'sdm', 'fkip', 'pgsd', 'paud', 'pgpaud', 'ttk',
  'upw', 'kesmas', 'mr', 'nde', 'ppn', 'pph', 'bpjs', 'umkm', 'sales/spg', 'admin/hrd', 'ipa', 'ips', 'ppkn', 'pai', 'pgmi', 'pwk', 'tjkt',
  'pplg', 'sija', 'tkro', 'tptu', 'tflm', 'atph', 'rmik', 'tlm', 'msdm', 'ulp', 'mice', 'pjkr', 'k3l', 'tkj']);
// Nama jurusan berbahasa Inggris tetap dikenali saat diketik lengkap, tapi tidak ditawarkan sebagai saran.
const ENGLISH_MAJORS = new Set(['accounting', 'management', 'business', 'banking', 'design', 'mechanical', 'electrical', 'civil', 'industrial engineering',
  'chemistry', 'chemical', 'mining', 'logistic', 'human resource', 'law', 'nursing', 'pharmacy', 'medical', 'hospitality', 'tourism', 'culinary',
  'agriculture', 'mathematics', 'statistics', 'physics', 'biology', 'biotechnology', 'international relations', 'environmental engineering',
  'aircraft maintenance', 'aviation', 'cosmetology', 'sport science', 'culinary art', 'computer science']);

/** Judul huruf kapital semua dirapikan: "SALES ADMINISTRATOR" -> "Sales Administrator", "STAFF IT" -> "Staff IT". */
export function prettyTitle(text) {
  const s = String(text || '').trim();
  if (/[a-z]/.test(s)) return s;
  const out = s.toLowerCase().replace(/[a-z0-9][a-z0-9&'’.+#]*/g, (w) => {
    const bare = w.replace(/[.]+$/, '');
    if (ACRONYMS.has(bare)) return w.toUpperCase();
    if (SMALL_WORDS.has(bare)) return w;
    return w[0].toUpperCase() + w.slice(1);
  });
  return out.charAt(0).toUpperCase() + out.slice(1);
}

// Bentuk badan usaha tidak ikut dicocokkan: ketik "bank" langsung ketemu "PT Bank Central Asia Tbk".
const LEGAL_FORM = /^(pt|cv|ud|pd|perum|perumda|koperasi|yayasan)\s+|\s+(tbk|persero)$/;
function companyKey(name) {
  let key = suggestKey(name);
  for (let i = 0; i < 3; i++) key = key.replace(LEGAL_FORM, '').trim();
  return key;
}

/** Inti judul untuk saran: tanpa keterangan kota/kebutuhan di belakang ("Sales Executive - Jakarta (Urgent)"). */
function titleCore(title) {
  return String(title || '').split(/\s+[-–—|]\s+|\s*[([]|,\s/)[0].trim();
}

/** Daftar saran untuk kolom "Posisi atau perusahaan", dari lowongan yang sedang aktif. */
export function buildJobSuggestions(jobs) {
  const titles = new Map();
  const companies = new Map();
  for (const j of jobs) {
    const core = titleCore(j.title);
    const key = suggestKey(core);
    if (key.length >= 3 && core.length <= 60) {
      let t = titles.get(key);
      if (!t) titles.set(key, (t = { count: 0, forms: new Map() }));
      t.count++;
      t.forms.set(core, (t.forms.get(core) || 0) + 1);
    }
    if (j.company && j.company.length <= 80) {  // nama yang lebih panjang biasanya alamat yang salah isi
      const c = companies.get(j.company);
      if (c) c.count++;
      else companies.set(j.company, { count: 1 });
    }
  }
  const items = [];
  for (const [key, t] of titles) {
    const forms = [...t.forms].sort((a, b) => b[1] - a[1]);
    // Tulisan dari sumber yang sudah memakai huruf kecil lebih rapi daripada versi kapital semua.
    const best = (forms.find(([f]) => /[a-z]/.test(f)) || forms[0])[0];
    items.push({ kind: 'posisi', label: prettyTitle(best), value: prettyTitle(best), keys: [key], count: t.count });
  }
  for (const [name, c] of companies) {
    const full = suggestKey(name);
    const keys = [...new Set([companyKey(name), full])].filter(Boolean);
    // Nama perusahaan hanya cocok di tengah bila ketikan cukup panjang dan namanya pendek, supaya
    // "adm" tidak memunculkan perusahaan yang namanya berisi "Kota Adm. Jakarta Barat".
    items.push({ kind: 'perusahaan', label: name, value: name, keys, count: c.count, strict: name.length > 50 ? 2 : 1 });
  }
  return items;
}

/** Saran untuk kolom jurusan: nama rumpun jurusan dan nama jurusan yang dikenalinya. */
export function buildMajorSuggestions(majors = MAJORS) {
  const seen = new Set();
  const items = [];
  majors.forEach((m, i) => {
    const key = suggestKey(m.label);
    seen.add(key);
    items.push({ kind: 'rumpun', label: m.label, value: m.label, keys: [key], count: 1000 - i });
  });
  majors.forEach((m) => {
    for (const aka of m.aka) {
      const key = suggestKey(aka);
      if (!key || seen.has(key) || ENGLISH_MAJORS.has(aka)) continue;
      seen.add(key);
      items.push({ kind: 'jurusan', label: prettyTitle(aka.toUpperCase()), value: prettyTitle(aka.toUpperCase()), sub: m.label, keys: [key], count: 0 });
    }
  });
  return items;
}

/**
 * Saran yang benar-benar melanjutkan ketikan: "ek" -> "Ekonomi", "Ekonomi Pembangunan", tapi tidak "Teknik".
 * Urutan: yang diawali ketikan dulu, lalu yang salah satu katanya diawali ketikan; di dalamnya yang lowongannya lebih banyak.
 * Tidak ada tebakan salah ketik.
 */
export function matchSuggestions(items, query, limits = { total: 8 }) {
  const q = suggestKey(query);
  if (!q) return [];
  const hits = [];
  for (const item of items) {
    let tier = 9;
    // Ketikan pendek (1-2 huruf) hanya melanjutkan dari awal nama; mulai 3 huruf boleh juga awal kata berikutnya.
    const inner = q.length >= 3 && item.strict !== 2;
    for (const key of item.keys) {
      if (key.startsWith(q)) { tier = 0; break; }
      if (inner && tier > 1 && key.includes(' ' + q)) tier = 1;
    }
    if (tier < 9) hits.push({ item, tier });
  }
  hits.sort((a, b) => a.tier - b.tier || b.item.count - a.item.count || a.item.label.length - b.item.label.length
    || a.item.label.localeCompare(b.item.label));
  const total = limits.total || 8;
  const perKind = limits.perKind || {};
  const used = {};
  const out = [];
  for (const { item } of hits) {
    const cap = perKind[item.kind];
    if (cap != null && (used[item.kind] || 0) >= cap) continue;
    used[item.kind] = (used[item.kind] || 0) + 1;
    out.push(item);
    if (out.length >= total) break;
  }
  if (out.length < total) {  // jatah satu jenis tidak terpakai: isi dengan jenis lain
    for (const { item } of hits) {
      if (out.length >= total) break;
      if (!out.includes(item)) out.push(item);
    }
    const rank = new Map(hits.map((h, i) => [h.item, i]));
    out.sort((a, b) => (a.kind === b.kind ? rank.get(a) - rank.get(b) : 0));
  }
  return out;
}

/** Bagian label yang cocok dengan ketikan, untuk ditebalkan: [sebelum, cocok, sesudah]. */
export function splitMatch(label, query) {
  const q = suggestKey(query);
  const text = String(label || '');
  if (!q) return [text, '', ''];
  const pattern = q.split(' ').map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^a-z0-9]+');
  const m = new RegExp(`(^|[^a-z0-9])(${pattern})`).exec(fold(text).length === text.length ? fold(text) : text.toLowerCase());
  if (!m) return [text, '', ''];
  const start = m.index + m[1].length;
  const end = start + m[2].length;
  return [text.slice(0, start), text.slice(start, end), text.slice(end)];
}
