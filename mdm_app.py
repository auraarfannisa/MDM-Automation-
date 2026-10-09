"""
MDM Automation - Streamlit app
Jalankan lokal : streamlit run mdm_app.py
Jalankan Colab : lihat notebook MDM_Streamlit_Colab.ipynb
"""
import io
import re
from collections import defaultdict

import numpy as np
import pandas as pd

# ==============================================================================
# MODUL 1: STANDARDISASI KOTA & KAMUS ALIAS
# ==============================================================================
KAMUS_17_DAERAH = {
    "SAMPIT": "KAB. KOTAWARINGIN TIMUR", "BATURAJA": "KAB. OGAN KOMERING ULU",
    "SUNGGUMINASA": "KAB. GOWA", "MUARABUNGO": "KAB. BUNGO", "MUARA BUNGO": "KAB. BUNGO",
    "TONDANO": "KAB. MINAHASA", "WATAMPONE": "KAB. BONE", "PADANGSIDEMPUAN": "KOTA PADANGSIDIMPUAN",
    "PADANGSIDIMPUAN": "KOTA PADANGSIDIMPUAN", "SEMARAPURA": "KAB. KLUNGKUNG",
    "SENGKANG": "KAB. WAJO", "TANJUNGTABALONG": "KAB. TABALONG", "TANJUNG TABALONG": "KAB. TABALONG",
    "BIAK": "KAB. BIAK NUMFOR", "AMBOINA": "KOTA AMBON", "LHOSEUMAWE": "KOTA LHOKSEUMAWE",
    "LHOKSEUMAWE": "KOTA LHOKSEUMAWE", "TANJUNG UBAN": "KAB. BINTAN", "TANJUNGUBAN": "KAB. BINTAN",
    "KUALATUNGKAL": "KAB. TANJUNG JABUNG BARAT", "KUALA TUNGKAL": "KAB. TANJUNG JABUNG BARAT",
    "MATARAM BARAT": "KOTA MATARAM", "MATARAMBARAT": "KOTA MATARAM",
    "SURABAYA BARAT": "KOTA SURABAYA", "SURABAYABARAT": "KOTA SURABAYA",
    "SOLO": "KOTA SURAKARTA", "PURWOKERTO": "KAB. BANYUMAS", "SERPONG": "KOTA TANGERANG SELATAN",
}


def clean_viva_dan_daerah(val):
    if pd.isna(val):
        return val
    s = str(val).strip()
    s = re.sub(r"^(VIVA\s+(APOTEK|APT\.?|FARMA)\b|APOTEK\s+VIVA\b)[\s\-\:\.]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    s_upper = s.upper()
    s_nospace = re.sub(r"[^A-Z0-9]", "", s_upper)
    if s_upper in KAMUS_17_DAERAH:
        return KAMUS_17_DAERAH[s_upper]
    if s_nospace in KAMUS_17_DAERAH:
        return KAMUS_17_DAERAH[s_nospace]
    return s


# ==============================================================================
# MODUL 2: CLEANSING NAMA & SEGMENTASI
# ==============================================================================
SEGMENT_SUFFIX = {
    "APT": "APT", "APOTEK": "APT", "KFA": "APT", "INSTANSI": "PT", "PMI": "PMI",
    "RS.PEM": "RS", "RS PEM": "RS", "RSUD": "RSUD", "RSUP": "RSUP", "RS.SWA": "RS",
    "RS.SWASTA": "RS", "RS IHC": "RS", "RS.TNI-POL": "RS", "RS.UNIV": "RS UNIV",
    "MMR": "MART", "TENDER": "TENDER", "PKM": "PKM", "RET": "TOKO", "LAB": "LAB",
    "POL": "KLINIK", "TOB": "TO", "INS": "INS", "PBF": "PT", "DINKES": "DINKES",
}
# kata utuh (bukan substring) agar "UNIVERSAL" tidak ikut terdeteksi sebagai universitas
_UNIV_RE = re.compile(r"\b(UNIVERSITAS|UNIV|FAKULTAS|FKUI|UGM)\b")


# Kata kunci nama -> suffix khusus (hanya untuk konteks RS: segmen RS* atau nama memuat RS/RSU/RUMAH SAKIT)
_RS_KONTEKS = re.compile(r"^RS\b|\b(RS|RSU|RSUD|RSUP|RSIA|RSAD|RSAL|RSAU|RSB|RSJ|RUMAH SAKIT)\b")
_KATA_SUFIKS = [
    (re.compile(r"\bTNI\s*-?\s*AD\b"), "RSAD"),
    (re.compile(r"\bTNI\s*-?\s*AL\b"), "RSAL"),
    (re.compile(r"\bTNI\s*-?\s*AU\b"), "RSAU"),
    (re.compile(r"\bBHAYANGKARA\b"), "RSPOL"),
]
SUFIKS_EKSTRA = {"RSAD", "RSAL", "RSAU", "RSPOL"}


def bangun_nama(dasar, kota, segment, suffix=None):
    """Pola PNAMLANG_AKHIR di master: NAMA (KOTA), SUFFIX. `suffix` (jika ada) menggantikan suffix bawaan segmen."""
    seg = "" if segment is None or pd.isna(segment) else str(segment).strip().upper()
    suffix = suffix if (suffix is not None and not pd.isna(suffix) and str(suffix).strip()) else SEGMENT_SUFFIX.get(seg, "")
    t = "" if dasar is None or pd.isna(dasar) else str(dasar).strip()
    if not t:
        return ""
    if kota is not None and not pd.isna(kota) and str(kota).strip():
        t = f"{t} ({str(kota).strip()})"
    return f"{t}, {suffix}" if suffix else t


def clean_name_parts(raw_name, raw_segment):
    """Kembalikan (nama dasar tanpa descriptor lokasi/fasilitas & suffix, segmen, suffix khusus)."""
    if pd.isna(raw_name) or str(raw_name).strip() == "":
        return "", "", None

    name = str(raw_name).strip().upper()
    segment = str(raw_segment).strip().upper() if pd.notna(raw_segment) else ""

    # Normalisasi format yang umum muncul dari Excel.
    name = re.sub(r'"{2,}', '"', name)
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\bK\s*-\s*24\b", "K24", name)
    name = re.sub(r"^PT\b\.?[\s,]*", "", name)

    # DINAS KESEHATAN: lokasi administratif bukan bagian nama outlet.
    # Untuk pola ini segment yang benar adalah DINKES.
    if re.match(r"^DINAS\s+KESEHATAN\b", name):
        name = "DINAS KESEHATAN"
        segment = "DINKES"

    # Buang keterangan lokasi setelah slash, mis. /BONE, /JPR,
    # /SELAYAR, /BANGGAI LAUT. Descriptor segment di depannya juga dibuang.
    name = re.sub(
        r"\s*,?\s*(?:APT|APOTEK|APOTIK|KLINIK(?:\s+(?:PRATAMA|UTAMA))?|"
        r"RSU?\.?|RSUD|RSUP|RSIA|RSAD|RSAL|RSAU|RSPOL)?\s*/\s*[A-Z0-9][A-Z0-9 .'-]*$",
        "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*/\s*[A-Z0-9][A-Z0-9 .'-]*$", "", name)

    # Buang lokasi kabupaten yang tersisip di nama, dan kode lokasi seperti (PML).
    name = re.sub(r"\s+KAB(?:UPATEN)?\.?\s+[A-Z][A-Z .'-]*?(?:\s+\([A-Z0-9]+\))?$", "", name)
    name = re.sub(r"\s+\(PML\)\s*$", "", name)

    # Deteksi suffix khusus rumah sakit sebelum descriptor dibersihkan.
    konteks_rs = segment.startswith("RS") or bool(_RS_KONTEKS.search(name))
    suffix_khusus = None
    if konteks_rs:
        for rx, sfx in _KATA_SUFIKS:
            if rx.search(name):
                suffix_khusus = sfx
                break

    if _UNIV_RE.search(name) and (segment.startswith("RS") or re.search(r"\bRS\b", name)):
        segment = "RS.UNIV"
        if suffix_khusus is None:
            suffix_khusus = "RS UNIV"

    # Prefix fasilitas generik. RSU. APBD -> nama tidak menyisakan APBD.
    name = re.sub(
        r"^(?:PUSKESMAS\b|PKM\b|RUMAH\s+SAKIT|RSUD|RSUP|RSIA|RSAD|RSAL|RSAU|RSPOL|RSU?\.?|"
        r"APOTEK|APOTIK|APT|KLINIK)\s*[\.,:\-]?\s*",
        "", name, flags=re.IGNORECASE)

    # Descriptor fasilitas generik di ujung nama.
    name = re.sub(r"(?:,\s*|\s+)KLINIK\s+(?:PRATAMA|UTAMA)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(?:,\s*)RSU\.?\s+APBD\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(?:,\s*|\s+)(?:KLINIK|APOTEK|APOTIK|APT|RSU|RSUD|RSUP|RSIA)\.?\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+APBD\s*$", "", name, flags=re.IGNORECASE)

    # Hapus suffix segment, termasuk format tanpa spasi: ',APT'.
    suffixes = sorted(set(SEGMENT_SUFFIX.values()) | SUFIKS_EKSTRA, key=len, reverse=True)
    for sfx in suffixes:
        name = re.sub(r",\s*" + re.escape(sfx) + r"\.?\s*$", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+" + re.escape(sfx) + r"\.?\s*$", "", name, flags=re.IGNORECASE)

    name = re.sub(r"\s+", " ", name).strip(" ,.-")
    return name, segment, suffix_khusus


def clean_name_and_segment(raw_name, raw_segment, kota=None):
    dasar, segment, sfx = clean_name_parts(raw_name, raw_segment)
    return bangun_nama(dasar, kota, segment, sfx), segment


# ==============================================================================
# HELPER
# ==============================================================================
def pick(df, *cols):
    """Ambil nilai non-kosong pertama dari beberapa kolom kandidat (yang ada saja)."""
    out = pd.Series([np.nan] * len(df), index=df.index, dtype=object)
    for c in cols:
        if c in df.columns:
            s = df[c].replace(r"^\s*$", np.nan, regex=True)
            out = out.where(out.notna(), s)
    return out


def norm_keputusan(series):
    s = series.fillna("").astype(str).str.strip().str.upper()
    return s.str.replace(r"\.0$", "", regex=True)  # Excel sering membaca 0 sebagai 0.0


def clean_dataframe_baru(df, pedoman=None):
    """Cleansing kota + nama + segmen pada data calon outlet baru (PNAMLANG_AKHIR = NAMA (KOTA), SUFFIX).
    Dengan `pedoman`, KOTA_BARU dinormalkan ke nama resmi pedoman (tambah KAB./KOTA, perbaiki spasi)."""
    df = df.copy()
    df["KOTA_ASAL"] = pick(df, "KOTA", "KOTA_CLEAN")          # kota sebelum cleansing
    df["KOTA_BARU"] = pick(df, "KOTA_CLEAN", "KOTA").apply(clean_viva_dan_daerah).apply(lambda v: kanonik_kota(v, pedoman))
    df["PNAMLANG_ASAL"] = pick(df, "PNAMLANG", "PNAMLANG_CLEAN")  # nama sebelum cleansing
    nama = pick(df, "PNAMLANG_CLEAN", "PNAMLANG")
    seg = pick(df, "SEGMENT_CLEAN", "SEGMENT")
    parts = [clean_name_parts(n, s) for n, s in zip(nama, seg)]
    df["_NAMA_DASAR"] = [p[0] for p in parts]
    df["SEGMENT_BARU"] = [p[1] for p in parts]
    df["_SUFIKS"] = [p[2] for p in parts]
    df["PNAMLANG_AKHIR"] = [bangun_nama(p[0], k, p[1], p[2]) for p, k in zip(parts, df["KOTA_BARU"])]
    return df


def rapatkan(df):
    """Taruh kolom hasil cleansing tepat di sebelah kolom aslinya (KOTA|KOTA_BARU, PNAMLANG|PNAMLANG_AKHIR)."""
    cols = list(df.columns)
    for asal, hasil in (("KOTA", "KOTA_BARU"), ("PNAMLANG", "PNAMLANG_AKHIR")):
        if asal in cols and hasil in cols and cols.index(hasil) != cols.index(asal) + 1:
            cols.remove(hasil)
            cols.insert(cols.index(asal) + 1, hasil)
    return df[cols]


# ==============================================================================
# MODUL 2B: PENCOCOKAN CUST_ID (nama + alamat mirip -> eliminasi, beda -> cek manual)
# ==============================================================================
from difflib import SequenceMatcher

KANDIDAT_KOLOM = {
    "cust_id": ["CUSTID", "CUSTOMERID", "IDCUST", "IDCUSTOMER", "KODECUSTOMER", "KODECUST"],
    "alamat": ["ALAMAT", "ALAMATCLEAN", "ALAMAT1", "ADDRESS", "ALAMATLENGKAP"],
    "distributor": ["DISTRIBUTOR", "NAMADISTRIBUTOR", "DISTRIBUTORNAME", "KODEDISTRIBUTOR", "DISTRIB", "DIST"],
}
STOP_NAMA = {"APOTEK", "APOTIK", "APT", "KLINIK", "RS", "RSU", "RUMAH", "SAKIT", "TOKO", "PT", "CV", "UD"}
STOP_ALAMAT = {"JL", "JALAN", "NO", "NOMOR", "RT", "RW", "KEL", "KELURAHAN", "KEC", "KECAMATAN", "KAB", "KOTA"}


def deteksi_kolom(df, jenis):
    peta = {re.sub(r"[^A-Z0-9]", "", str(c).upper()): c for c in df.columns}
    for k in KANDIDAT_KOLOM[jenis]:
        if k in peta:
            return peta[k]
    return None


def _norm_id(v):
    if v is None or pd.isna(v):
        return None
    s = re.sub(r"\.0$", "", str(v).strip().upper())
    return s or None


def _norm_dist(v):
    return "" if v is None or pd.isna(v) else re.sub(r"\s+", " ", str(v).strip().upper())


def _is_khusus(v, daftar):
    d = _norm_dist(v)
    return bool(d) and any(re.search(r"\b" + re.escape(t) + r"\b", d) for t in daftar)


def sim(a, b, stop=()):
    """Skor kemiripan 0..1; None jika salah satu kosong."""
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return None
    ta = [t for t in re.sub(r"[^A-Z0-9 ]", " ", str(a).upper()).split() if t not in stop]
    tb = [t for t in re.sub(r"[^A-Z0-9 ]", " ", str(b).upper()).split() if t not in stop]
    if not ta or not tb:
        return None
    r1 = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    r2 = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(r1, r2)


def _tanpa_kota(v):
    """Buang '(KOTA ...)' dan akhiran ', APT' berulang agar nama master & nama baru sebanding."""
    if v is None or pd.isna(v):
        return v
    t = re.sub(r"\([^)]*\)", " ", str(v))
    t = re.sub(r"(,\s*[A-Z ]+?)(\1)+\s*$", r"\1", t.upper())
    return t


LABEL_AKSI = {
    "BARU": "ID BARU",
    "ELIMINASI": "ELIMINASI (duplikat)",
    "TIMPA": "TIMPA NAMA MASTER",
    "TIMPA_GABUNG": "TIMPA NAMA + GABUNG ROW",
    "GABUNG_LAMA": "GABUNG ROW (NAMA LAMA)",
}
AKSI_DARI_LABEL = {v: k for k, v in LABEL_AKSI.items()}


def _aksi_sah(aksi, via):
    """Sesuaikan aksi dengan jenis kecocokan. cust_id sama persis: tidak ada 'gabung' (cust_id sudah ada di master).
    Tail saja: 'timpa' selalu diikuti gabung row (tail = outlet sama, cust_id lain)."""
    if aksi == "SAMA":
        aksi = "ELIMINASI"
    if via == "CUST_ID":
        return {"TIMPA_GABUNG": "TIMPA", "GABUNG_LAMA": "ELIMINASI"}.get(aksi, aksi)
    return "TIMPA_GABUNG" if aksi == "TIMPA" else aksi


def cocokkan_cust(df_new, df_lama, cfg, keputusan, cache=None):
    """Cocokkan baris data baru ke master lewat cust_id (dan tail untuk distributor khusus).
    Aksi per baris: ELIMINASI | TIMPA (nama semua baris ber-ID_STR sama diganti) | GABUNG_LAMA (tambah row, nama lama)
    | TIMPA_GABUNG (nama diganti + tambah row) | BARU (jadi ID baru)."""
    kb, km = cfg["kol_baru"], cfg["kol_master"]
    hasil = {"eliminasi": [], "manual": [], "update": [], "gabung": [], "semua": [], "paksa_baru": set(), "info": []}
    if not kb.get("cust_id") or not km.get("cust_id"):
        hasil["info"].append("Pencocokan cust_id dilewati: kolom cust_id tidak ada di "
                             + ("data baru" if not kb.get("cust_id") else "master") + ".")
        return hasil
    khusus = [t.strip().upper() for t in cfg.get("distributor_khusus", []) if t.strip()]
    ada_dist = bool(kb.get("distributor") and km.get("distributor"))
    pakai_dist = bool(cfg.get("lingkup_distributor") and ada_dist)
    tail_aktif = bool(ada_dist and khusus)
    min_tail = cfg.get("min_tail", 3)
    if not ada_dist:
        hasil["info"].append("Kolom distributor tidak ada di data baru/master: cust_id dicocokkan tanpa lingkup distributor, "
                             "dan pencocokan tail cust_id tidak dijalankan.")
    an, aa = cfg["ambang_nama"], cfg["ambang_alamat"]
    ada_alamat = bool(kb.get("alamat") and km.get("alamat"))
    if not ada_alamat:
        hasil["info"].append("Kolom alamat tidak ada di data baru/master: kemiripan dinilai dari nama saja.")

    # Indeks cust_id/tail/ID_STR master tidak berubah selama master & pengaturan sama: dibuat sekali lalu dipakai ulang
    sig_idx = (km.get("cust_id"), km.get("distributor"), pakai_dist, tail_aktif, tuple(khusus), min_tail, len(df_lama))
    ada_cache = cache is not None and cache.get("idx") is not None and cache["idx"][0] == sig_idx
    if ada_cache:
        _, idx1, idx2, idmap = cache["idx"]
    else:
        idx1, idx2 = defaultdict(list), defaultdict(list)
        dm = df_lama[km["distributor"]] if km.get("distributor") else [""] * len(df_lama)
        for ix, c, d in zip(df_lama.index, df_lama[km["cust_id"]], dm):
            c = _norm_id(c)
            if c is None:
                continue
            dn = _norm_dist(d) if pakai_dist else ""
            idx1[(dn, c)].append(ix)
            if tail_aktif and "-" in c and _is_khusus(d, khusus):
                t = c.rsplit("-", 1)[1].strip()
                if len(t) >= min_tail:
                    idx2[(dn, t)].append(ix)
        idmap = defaultdict(list)  # ID_STR_OUTLET -> index baris master (untuk menampilkan cust_id lain di outlet yang sama)
        for ix, i_ in zip(df_lama.index, df_lama["ID_STR_OUTLET"].astype(str)):
            idmap[i_].append(ix)
        if cache is not None:
            cache["idx"] = (sig_idx, idx1, idx2, idmap)

    nama_m = df_lama["PNAMLANG_AKHIR"]
    alamat_m = df_lama[km["alamat"]] if km.get("alamat") else None
    for _, row in df_new.iterrows():
        c = _norm_id(row[kb["cust_id"]])
        if c is None:
            continue
        d_raw = row[kb["distributor"]] if kb.get("distributor") else ""
        dn = _norm_dist(d_raw) if pakai_dist else ""
        cand, via = idx1.get((dn, c), []), "CUST_ID"
        if not cand and tail_aktif and "-" in c and _is_khusus(d_raw, khusus):
            t = c.rsplit("-", 1)[1].strip()
            if len(t) >= min_tail:
                cand, via = idx2.get((dn, t), []), "TAIL CUST_ID"
        if not cand:
            continue
        alamat_b = row[kb["alamat"]] if kb.get("alamat") else None
        best = None
        for mi in cand:
            sn = sim(_tanpa_kota(row["PNAMLANG_AKHIR"]), _tanpa_kota(nama_m.at[mi]), STOP_NAMA)
            sa = sim(alamat_b, alamat_m.at[mi], STOP_ALAMAT) if (ada_alamat and alamat_m is not None) else None
            ok_n = sn is not None and sn >= an
            ok_a = sa is None or sa >= aa
            skor = (ok_n and ok_a, (sn or 0) + (sa or 0))
            if best is None or skor > best[0]:
                best = (skor, mi, sn, sa, ok_n, ok_a)
        _, mi, sn, sa, ok_n, ok_a = best
        if not ok_n and not ok_a:
            sebab = "NAMA & ALAMAT BERUBAH"
        elif not ok_n:
            sebab = "NAMA BERUBAH"
        elif not ok_a:
            sebab = "ALAMAT BERUBAH"
        else:
            sebab = "MIRIP"
        id_m = df_lama.at[mi, "ID_STR_OUTLET"]
        baris_id = idmap.get(str(id_m), [mi])
        lain = []
        for x in baris_id:
            v = df_lama.at[x, km["cust_id"]]
            if pd.notna(v) and str(v) not in lain:
                lain.append(str(v))
        jenis_match = "CUST_ID" if via == "CUST_ID" else "TAIL"
        if ok_n and ok_a:
            saran = "Mirip: kemungkinan outlet sama (" + ("eliminasi/timpa" if jenis_match == "CUST_ID" else "gabung row") + ")"
        else:
            saran = sebab + ": periksa, bisa outlet berbeda"
        rec = {
            "BARIS_EXCEL": row["BARIS_EXCEL"], "JENIS_MATCH": jenis_match, "MATCH_PADA": via,
            "CUST_ID_BARU": row[kb["cust_id"]], "DISTRIBUTOR_BARU": d_raw if kb.get("distributor") else "",
            "PNAMLANG_ASAL": row.get("PNAMLANG_ASAL"), "PNAMLANG_BARU": row["PNAMLANG_AKHIR"], "ALAMAT_BARU": alamat_b,
            "KOTA_BARU": row.get("KOTA_BARU"),
            "ID_STR_OUTLET_MASTER": id_m,
            "CUST_ID_MASTER": df_lama.at[mi, km["cust_id"]],
            "DISTRIBUTOR_MASTER": df_lama.at[mi, km["distributor"]] if km.get("distributor") else "",
            "PNAMLANG_MASTER": nama_m.at[mi], "ALAMAT_MASTER": alamat_m.at[mi] if alamat_m is not None else None,
            "KOTA_MASTER": df_lama.at[mi, "KOTA_BARU"] if "KOTA_BARU" in df_lama.columns else None,
            "JML_ROW_ID_STR_MASTER": len(baris_id), "CUST_ID_DI_ID_STR": ", ".join(lain[:8]) + (" ..." if len(lain) > 8 else ""),
            "JML_KANDIDAT": len(cand),
            "SKOR_NAMA": None if sn is None else round(sn, 2), "SKOR_ALAMAT": None if sa is None else round(sa, 2),
            "KEMIRIPAN": sebab, "SARAN": saran, "NAMA_KOTOR": "; ".join(cek_nama_kotor(row["PNAMLANG_AKHIR"])),
            "_IDX_MASTER": mi, "_KOTA": row.get("KOTA_BARU"), "_ALAMAT_RAW": alamat_b,
        }
        # Tidak ada aksi otomatis: setiap baris diputuskan sendiri di tab 'Keputusan cust_id'.
        kep = keputusan.get(row["BARIS_EXCEL"])
        aksi = None if not kep else ("BARU" if kep == "BARU" else _aksi_sah(kep, jenis_match))
        rec["AKSI"] = aksi
        hasil["semua"].append(rec)
        if aksi is None:
            hasil["manual"].append(rec)
        elif aksi == "BARU":
            hasil["paksa_baru"].add(row["BARIS_EXCEL"])
        elif aksi == "ELIMINASI":
            hasil["eliminasi"].append(rec)
        else:
            if aksi in ("TIMPA", "TIMPA_GABUNG"):
                hasil["update"].append(rec)
            if aksi in ("GABUNG_LAMA", "TIMPA_GABUNG"):
                hasil["gabung"].append(rec)
    return hasil


# ==============================================================================
# MODUL 3: MDM ENGINE
# ==============================================================================
KOLOM_LOG = ["DISTRIBUTOR", "KOCAB", "CABANG_DIST", "CUST_ID", "ID_STR_OUTLET", "PNAMLANG", "PNAMLANG_AKHIR",
             "ALAMAT", "KOTA_BARU", "SEGMENT"]


def snap_log(row):
    """Ambil kolom-kolom KOLOM_LOG dari satu baris data (ID_STR_OUTLET diisi oleh L sendiri)."""
    out = {}
    for k in KOLOM_LOG:
        if k == "ID_STR_OUTLET":
            continue
        v = row.get(k)
        if (v is None or pd.isna(v)) and k == "SEGMENT":
            v = row.get("SEGMENT_BARU")
        if (v is None or pd.isna(v)) and k == "PNAMLANG":
            v = row.get("PNAMLANG_ASAL")
        out[k] = v
    return out


def log_tampil(df):
    """Tampilan log perubahan: JENIS + kolom data yang terkena perubahan."""
    if df is None or len(df) == 0:
        return df
    d = df.copy()
    kol = ["SUMBER", "JENIS"] + KOLOM_LOG
    for c in kol:
        if c not in d.columns:
            d[c] = None
    return d[kol]


def _nkey(v):
    return re.sub(r"[^A-Z0-9]", "", str(_tanpa_kota(v)).upper())


def _kunci_nks(d):
    """Kunci nama+kota+segmen untuk deteksi duplikat dengan master."""
    return (d["PNAMLANG_AKHIR"].map(_nkey) + "|" + d["KOTA_BARU"].map(lambda x: kunci_wilayah(x)[1]) + "|"
            + d["SEGMENT_BARU"].astype(str).str.strip().str.upper())


def run_mdm(df_lama, sheets_baru, df_wilayah=None, timpa_pasangan=False, fallback_prefix="1.10.31",
            sheet_baru="Data_Baru", sheet_match=None, lewati_duplikat=True,
            cust_cfg=None, keputusan_manual=None, pedoman=None, kota_override=None, nama_override=None, master_nama_override=None,
            cache=None):
    log = []

    def L(jenis, id_, detail, row=None):
        e = {"JENIS": jenis, "ID_STR_OUTLET": id_, "DETAIL": detail}
        if row is not None:
            e.update(snap_log(row))
        log.append(e)

    if sheet_baru not in sheets_baru:
        raise ValueError(f"Sheet data baru '{sheet_baru}' tidak ditemukan. Sheet tersedia: {list(sheets_baru)}")
    df_lama = df_lama.copy()
    ids_asli = df_lama[["ID_STR_OUTLET"]].copy()  # untuk nomor urut: ID hasil merge tidak boleh dipakai ulang
    df_murni = sheets_baru[sheet_baru].copy()
    df_murni["BARIS_EXCEL"] = df_murni.index + 2  # perkiraan nomor baris di Excel (baris 1 = header)
    for kolom, kandidat in (("nama", ("PNAMLANG_CLEAN", "PNAMLANG")), ("kota", ("KOTA_CLEAN", "KOTA"))):
        if not any(c in df_murni.columns for c in kandidat):
            raise ValueError(
                f"Sheet '{sheet_baru}' tidak punya kolom {kolom} ({' / '.join(kandidat)}). "
                f"Kolom yang ada: {list(df_murni.columns)}"
            )

    for c in ["ID_STR_OUTLET"]:
        if c not in df_lama.columns:
            raise ValueError(f"Kolom '{c}' tidak ada di master lama.")
    # --- Siapkan kolom standar master lama (hanya jika belum ada) ---
    if "KOTA_BARU" not in df_lama.columns:
        df_lama["KOTA_BARU"] = pick(df_lama, "KOTA_CLEAN", "KOTA").apply(clean_viva_dan_daerah)
        L("INFO", "", "Kolom KOTA_BARU tidak ada di master lama, dibuat dari KOTA_CLEAN/KOTA.")
    if "SEGMENT_BARU" not in df_lama.columns:
        df_lama["SEGMENT_BARU"] = pick(df_lama, "SEGMENT_CLEAN", "SEGMENT")
        L("INFO", "", "Kolom SEGMENT_BARU tidak ada di master lama, dibuat dari SEGMENT_CLEAN/SEGMENT.")
    if "PNAMLANG_AKHIR" not in df_lama.columns:
        nm = pick(df_lama, "PNAMLANG_CLEAN", "PNAMLANG")
        sg = df_lama["SEGMENT_BARU"]
        df_lama["PNAMLANG_AKHIR"] = [clean_name_and_segment(n, s, k)[0] for n, s, k in zip(nm, sg, df_lama["KOTA_BARU"])]
        L("INFO", "", "Kolom PNAMLANG_AKHIR tidak ada di master lama, dibuat dari PNAMLANG_CLEAN/PNAMLANG.")

    # Kunci nama+kota+segmen master dihitung sekali (mahal untuk 86 ribu baris); hanya baris master yang namanya diubah dihitung ulang
    kl_dasar = cache.get("kunci_lama") if cache is not None else None
    if kl_dasar is None or len(kl_dasar) != len(df_lama) or not kl_dasar.index.equals(df_lama.index):
        kl_dasar = _kunci_nks(df_lama)
        if cache is not None:
            cache["kunci_lama"] = kl_dasar
    diubah_master = set()
    # Keputusan cust_id/tail dibuat per baris di tab 'Keputusan cust_id'
    merge_map = {}
    df_setuju = pd.DataFrame()
    df_ditolak = pd.DataFrame()

    # --- B. Calon ID baru + sorting ---
    df_murni = clean_dataframe_baru(df_murni, pedoman)
    # Kota yang dipilih user (dropdown pedoman di tab Keputusan cust_id): nama akhir dibangun ulang mengikuti kota
    for ix_, b_ in zip(df_murni.index, df_murni["BARIS_EXCEL"]):
        k_ = (kota_override or {}).get(b_)
        if k_:
            df_murni.at[ix_, "KOTA_BARU"] = k_
            df_murni.at[ix_, "PNAMLANG_AKHIR"] = bangun_nama(
                df_murni.at[ix_, "_NAMA_DASAR"], k_, df_murni.at[ix_, "SEGMENT_BARU"], df_murni.at[ix_, "_SUFIKS"])
        n_ = (nama_override or {}).get(b_)   # nama yang diedit user di tab Keputusan cust_id menang atas hasil cleansing
        if n_:
            df_murni.at[ix_, "PNAMLANG_AKHIR"] = n_

    if cust_cfg:
        for k_ in ("cust_id", "alamat", "distributor"):
            a_, b_ = cust_cfg["kol_baru"].get(k_), cust_cfg["kol_master"].get(k_)
            if a_ and b_ and a_ != b_ and a_ in df_murni.columns and b_ not in df_murni.columns:
                df_murni[b_] = df_murni[a_]

    df_all = df_murni   # salinan acuan (semua baris data baru) untuk melengkapi kolom di log
    peta_baris = {b_: ix_ for ix_, b_ in zip(df_all.index, df_all["BARIS_EXCEL"])}

    def rb(b):
        ix = peta_baris.get(b)
        return None if ix is None else df_all.loc[ix]

    # --- B0. Pencocokan cust_id (nama + alamat mirip -> eliminasi; beda -> cek manual) ---
    cek_manual = pd.DataFrame()
    cust_match = pd.DataFrame()
    n_cust_elim = n_timpa = n_gabung = 0
    paksa_baru = set()
    df_gabung = pd.DataFrame()
    if cust_cfg:
        hc = cocokkan_cust(df_murni, df_lama, cust_cfg, keputusan_manual or {}, cache=cache)
        for t in hc["info"]:
            L("INFO", "", t)
        paksa_baru = hc["paksa_baru"]

        # Nama master yang diedit user di tab Keputusan cust_id: ganti di SEMUA baris master ber-ID_STR sama
        peta_rec = {r_["BARIS_EXCEL"]: r_ for r_ in hc["semua"]}
        for b_, n_ in (master_nama_override or {}).items():
            r_ = peta_rec.get(b_)
            if r_ is None:
                continue
            id_m_ = r_["ID_STR_OUTLET_MASTER"]
            sama_ = df_lama.index[df_lama["ID_STR_OUTLET"].astype(str) == str(id_m_)]
            lama_ = df_lama.at[r_["_IDX_MASTER"], "PNAMLANG_AKHIR"]
            df_lama.loc[sama_, "PNAMLANG_AKHIR"] = n_
            diubah_master.update(sama_)
            for x_ in hc["semua"]:
                if str(x_["ID_STR_OUTLET_MASTER"]) == str(id_m_):
                    x_["PNAMLANG_MASTER"] = n_   # tampilan di menu ikut berubah
            L("EDIT NAMA MASTER", id_m_, f"{len(sama_)} baris ber-ID_STR sama: '{lama_}' -> '{n_}'", row=rb(b_))

        for r in hc["eliminasi"]:
            L("CUST_ID SAMA (DIELIMINASI)", r["ID_STR_OUTLET_MASTER"],
              f"[{r['MATCH_PADA']}] '{r['PNAMLANG_BARU']}' ~ '{r['PNAMLANG_MASTER']}' (nama {r['SKOR_NAMA']}, alamat {r['SKOR_ALAMAT']}) - {r['KEMIRIPAN']}", row=rb(r["BARIS_EXCEL"]))
        # TIMPA: PNAMLANG_AKHIR (dan KOTA_BARU agar nama konsisten) diganti di SEMUA baris master ber-ID_STR_OUTLET sama
        for r in hc["update"]:
            mi, id_m = r["_IDX_MASTER"], r["ID_STR_OUTLET_MASTER"]
            sama_id = df_lama.index[df_lama["ID_STR_OUTLET"].astype(str) == str(id_m)]
            lama_n, lama_k = df_lama.at[mi, "PNAMLANG_AKHIR"], df_lama.at[mi, "KOTA_BARU"]
            df_lama.loc[sama_id, "PNAMLANG_AKHIR"] = r["PNAMLANG_BARU"]
            diubah_master.update(sama_id)
            if pd.notna(r["_KOTA"]):
                df_lama.loc[sama_id, "KOTA_BARU"] = r["_KOTA"]
            cat_kota = (f"; KOTA {lama_k} -> {r['_KOTA']} (periksa prefix ID)"
                        if pd.notna(r["_KOTA"]) and _s(lama_k) != _s(r["_KOTA"]) else "")
            L("TIMPA PNAMLANG", id_m, f"[{r['MATCH_PADA']}] {len(sama_id)} baris ber-ID_STR sama: "
              f"'{lama_n}' -> '{r['PNAMLANG_BARU']}'{cat_kota}", row=rb(r["BARIS_EXCEL"]))
        # GABUNG: baris baru ditambahkan ke master dengan ID_STR_OUTLET outlet yang cocok (bukan ID baru)
        df_gabung = pd.DataFrame()
        peta_gab = {r["BARIS_EXCEL"]: r for r in hc["gabung"]}
        if peta_gab:
            kb_, km_ = cust_cfg["kol_baru"], cust_cfg["kol_master"]
            df_gabung = df_murni[df_murni["BARIS_EXCEL"].isin(peta_gab)].copy()
            for k_ in ("cust_id", "alamat", "distributor"):
                if kb_.get(k_) and km_.get(k_) and kb_[k_] != km_[k_]:
                    df_gabung[km_[k_]] = df_gabung[kb_[k_]]
            mis = [peta_gab[b]["_IDX_MASTER"] for b in df_gabung["BARIS_EXCEL"]]
            for kol in ("ID_STR_OUTLET", "PNAMLANG_AKHIR", "KOTA_BARU", "SEGMENT_BARU"):  # ikut outlet master (setelah timpa)
                df_gabung[kol] = [df_lama.at[m, kol] for m in mis]
            for (_, g), b in zip(df_gabung.iterrows(), df_gabung["BARIS_EXCEL"]):
                r = peta_gab[b]
                L("GABUNG ROW", g["ID_STR_OUTLET"],
                  f"[{r['MATCH_PADA']}] cust_id {r['CUST_ID_BARU']} ditambahkan ke outlet '{g['PNAMLANG_AKHIR']}' "
                  f"({'nama ditimpa' if r in hc['update'] else 'nama master lama dipertahankan'})", row=rb(b))
        if hc["manual"]:
            cek_manual = pd.DataFrame(hc["manual"])
            cek_manual = cek_manual[[c for c in cek_manual.columns if not c.startswith("_")]]
        if hc["semua"]:  # semua baris yang cocok cust_id/tail, lengkap dengan keputusan terakhir (AKSI kosong = belum diputuskan)
            cust_match = pd.DataFrame(hc["semua"])
            cust_match = cust_match[[c for c in cust_match.columns if not c.startswith("_")]]
        n_cust_elim = len(hc["eliminasi"])
        n_timpa, n_gabung = len(hc["update"]), len(hc["gabung"])
        hapus = {r["BARIS_EXCEL"] for r in hc["eliminasi"] + hc["manual"] + hc["update"] + hc["gabung"]}
        df_murni = df_murni[~df_murni["BARIS_EXCEL"].isin(hapus)]

    n_dup_lewat = 0
    if len(df_murni):
        df_murni = df_murni.copy()
        df_murni["_CATATAN_DUP"] = ""
        for c_ in KOLOM_SAMA:
            df_murni[c_] = pd.Series([None] * len(df_murni), index=df_murni.index, dtype=object)
        idmap_m = defaultdict(list)   # ID_STR_OUTLET -> index baris master (untuk data pembanding)
        for ix_, i_ in zip(df_lama.index, df_lama["ID_STR_OUTLET"].astype(str)):
            idmap_m[i_].append(ix_)

        kunci = _kunci_nks
        kl = kl_dasar
        if diubah_master:
            kl = kl_dasar.copy()
            idx_u = [i_ for i_ in df_lama.index if i_ in diubah_master]
            kl.loc[idx_u] = _kunci_nks(df_lama.loc[idx_u])
        peta_master = defaultdict(list)
        for ix_, k_ in zip(df_lama.index, kl):
            peta_master[k_].append(ix_)
        km = kunci(df_murni)
        cfg_ = cust_cfg or {}
        kol_ab = (cfg_.get("kol_baru") or {}).get("alamat") or deteksi_kolom(df_murni, "alamat")
        kol_am = (cfg_.get("kol_master") or {}).get("alamat") or deteksi_kolom(df_lama, "alamat")
        amb_alamat = cfg_.get("ambang_alamat", 0.70)
        kol_cm = (cfg_.get("kol_master") or {}).get("cust_id") or deteksi_kolom(df_lama, "cust_id")
        pakai_alamat = bool(kol_ab and kol_am and kol_ab in df_murni.columns and kol_am in df_lama.columns)
        if not pakai_alamat:
            L("INFO", "", "Cek duplikat nama+kota+segmen tanpa alamat (kolom alamat tidak ditemukan di data baru/master).")
        dup_list = []
        for ix_, k_, b_ in zip(df_murni.index, km, df_murni["BARIS_EXCEL"]):
            cand = peta_master.get(k_)
            if not cand or b_ in paksa_baru:
                continue
            skor, mi_best = None, cand[0]
            if pakai_alamat:
                sk = [(sim(df_murni.at[ix_, kol_ab], df_lama.at[mi_, kol_am], STOP_ALAMAT), mi_) for mi_ in cand]
                sk = [t_ for t_ in sk if t_[0] is not None]
                if sk:
                    skor, mi_best = max(sk, key=lambda t_: t_[0])
            id_m = df_lama.at[mi_best, "ID_STR_OUTLET"]
            if skor is None or skor >= amb_alamat:
                dup_list.append((ix_, id_m, skor))
            else:
                df_murni.at[ix_, "_CATATAN_DUP"] = (f"Nama+kota+segmen sama dengan outlet master {id_m} tetapi alamat berbeda "
                                                    f"(skor {skor:.2f}); pastikan ini outlet lain. Jika ternyata outlet yang sama, "
                                                    f"centang GABUNG (jadi row baru ber-ID {id_m})")
                df_murni.at[ix_, "ID_MASTER_SAMA"] = id_m
                df_murni.at[ix_, "ALAMAT_MASTER_SAMA"] = df_lama.at[mi_best, kol_am] if pakai_alamat else None
                df_murni.at[ix_, "_NAMA_MASTER_SAMA"] = df_lama.at[mi_best, "PNAMLANG_AKHIR"]
                df_murni.at[ix_, "_KOTA_MASTER_SAMA"] = df_lama.at[mi_best, "KOTA_BARU"]
                df_murni.at[ix_, "_SEG_MASTER_SAMA"] = df_lama.at[mi_best, "SEGMENT_BARU"]
                df_murni.at[ix_, "PNAMLANG_MASTER_SAMA"] = df_lama.at[mi_best, "PNAMLANG_AKHIR"]
                df_murni.at[ix_, "SKOR_ALAMAT_SAMA"] = None if skor is None else round(skor, 2)
                baris_id_ = idmap_m.get(str(id_m), [])
                df_murni.at[ix_, "JML_ROW_MASTER_SAMA"] = len(baris_id_)
                if kol_cm:
                    cl_ = []
                    for x_ in baris_id_:
                        v_ = df_lama.at[x_, kol_cm]
                        if pd.notna(v_) and str(v_) not in cl_:
                            cl_.append(str(v_))
                    df_murni.at[ix_, "CUST_ID_MASTER_SAMA"] = ", ".join(cl_[:8]) + (" ..." if len(cl_) > 8 else "")
        sama = pd.Series(False, index=df_murni.index)
        for ix_, _, _ in dup_list:
            sama.at[ix_] = True
        if lewati_duplikat and dup_list:
            for ix_, id_m, skor in dup_list:
                L("DUPLIKAT DILEWATI", id_m, f"'{df_murni.at[ix_, 'PNAMLANG_AKHIR']}' sama dengan outlet master (nama+kota+segmen"
                  + (f", alamat mirip {skor:.2f}" if skor is not None else ", alamat tidak dibandingkan") + "); tidak dibuat ID baru", row=rb(df_murni.at[ix_, "BARIS_EXCEL"]))
            n_dup_lewat = len(dup_list)
        elif dup_list:
            L("INFO", "", f"{len(dup_list)} baris sama dengan master tetapi tetap diberi ID baru (opsi lewati duplikat mati)")
            sama[:] = False
        nm_map = dict(zip(km, df_murni["PNAMLANG_AKHIR"]))
        sisa = km[~sama]
        for k_ in sisa[sisa.duplicated(keep=False)].unique():
            L("PERINGATAN", "", f"Muncul lebih dari sekali di file data baru: {nm_map[k_]}")
        df_murni = df_murni[~sama]
    df_ditolak = clean_dataframe_baru(df_ditolak) if len(df_ditolak) else df_ditolak
    df_calon = pd.concat([df_murni] + ([df_ditolak] if len(df_ditolak) else []), ignore_index=True)
    if df_calon.empty:
        df_calon = pd.DataFrame(columns=list(df_murni.columns) + [c for c in ("KOTA_BARU", "SEGMENT_BARU", "PNAMLANG_AKHIR") if c not in df_murni.columns])
    df_calon = df_calon.sort_values(
        by=["KOTA_BARU", "SEGMENT_BARU", "PNAMLANG_AKHIR"], ascending=True, na_position="last"
    ).reset_index(drop=True)

    max_seq, prefix_map = peta_id(df_lama, ids_asli)
    return {
        "master_lama": df_lama,
        "calon": df_calon,
        "log": pd.DataFrame(log),
        "cek_manual": cek_manual,
        "cust_match": cust_match,
        "gabung": df_gabung,
        "max_seq": max_seq,
        "prefix_map": prefix_map,
        "stats": {
            "Master lama": len(df_lama),
            "Cust_id sama (dieliminasi)": n_cust_elim,
            "PNAMLANG ditimpa": n_timpa,
            "Digabung (tambah row)": n_gabung,
            "Cust_id belum diputuskan": len(cek_manual),
            "Duplikat dilewati": n_dup_lewat,
        },
    }


# ==============================================================================
# MODUL 4: PEDOMAN ID_STR_OUTLET  (Segment.Provinsi.Kab/Kota.Urutan)
# ==============================================================================
def _norm_kab(v):
    """Samakan penulisan: KABUPATEN/KAB/KAB. -> 'KAB. ', 'KOTA ADM(INISTRASI)' -> 'KOTA '."""
    if v is None or pd.isna(v):
        return ""
    s = re.sub(r"\s+", " ", str(v).strip().upper())
    s = re.sub(r"^KOTA (ADMINISTRASI|ADM\.?) ", "KOTA ", s)  # pedoman: KOTA ADMINISTRASI JAKARTA X = KOTA JAKARTA X
    s = re.sub(r"^(KABUPATEN|KAB)(\.\s*|\s+)", "KAB. ", s)
    return s


def kunci_wilayah(v):
    """(jenis, nama tanpa spasi/tanda baca). jenis = 'KAB', 'KOTA', atau '' bila tidak ada awalan."""
    s = _norm_kab(v)
    m = re.match(r"^(KAB|KOTA)\.?\s+(.*)$", s)
    jenis, sisa = (m.group(1), m.group(2)) if m else ("", s)
    return jenis, re.sub(r"[^A-Z0-9]", "", sisa)


def kanonik_kota(val, pedoman):
    """Ubah ke nama resmi pedoman. Nama yang hanya ada sebagai KAB atau KOTA otomatis diberi awalannya;
    nama yang ada sebagai keduanya (mis. BOGOR) dibiarkan jika tanpa awalan."""
    if val is None or pd.isna(val) or not pedoman or not pedoman.get("by_base"):
        return val
    s = _norm_kab(val)
    if not s:
        return val
    j, base = kunci_wilayah(s)
    kand = pedoman["by_base"].get(base, [])
    if not kand:
        return s
    if len(kand) == 1:
        c = kand[0]
        return c if (j == "" or c.startswith(j)) else s   # awalan eksplisit yang bertentangan dibiarkan (akan ditandai)
    for c in kand:                                           # ada KAB dan KOTA
        if j and c.startswith(j):
            return c
    return s


def parse_pedoman(data):
    """Baca sheet pedoman: tabel SEGMENT (+kode) dan tabel Provinsi/Kab-Kota (+kode)."""
    raw = pd.read_excel(io.BytesIO(data), sheet_name=0, header=None)
    hdr = None
    for i in range(min(len(raw), 30)):
        v = [str(x).strip().upper() for x in raw.iloc[i]]
        if "SEGMENT" in v and "KODE PROVINSI" in v and "KODE KAB/KOTA" in v:
            hdr = i
            break
    if hdr is None:
        raise ValueError("Baris judul pedoman (SEGMENT, Provinsi, Kode Provinsi, Kab/Kota, Kode Kab/Kota) tidak ditemukan.")
    v = [str(x).strip().upper() for x in raw.iloc[hdr]]
    last = lambda n: max(i for i, x in enumerate(v) if x == n)
    sc, pc, pk, kc, kk = last("SEGMENT"), last("PROVINSI"), last("KODE PROVINSI"), last("KAB/KOTA"), last("KODE KAB/KOTA")
    seg, wil = [], []
    for r in range(hdr + 1, len(raw)):
        if pd.notna(raw.iat[r, sc]) and pd.notna(raw.iat[r, sc + 1]):
            seg.append((str(raw.iat[r, sc]).strip().upper(), int(raw.iat[r, sc + 1])))
        if pd.notna(raw.iat[r, kc]) and pd.notna(raw.iat[r, kk]) and pd.notna(raw.iat[r, pk]):
            wil.append((str(raw.iat[r, pc]).strip().upper(), int(raw.iat[r, pk]),
                        str(raw.iat[r, kc]).strip().upper(), int(raw.iat[r, kk])))
    return (pd.DataFrame(seg, columns=["SEGMENT", "KODE_SEGMENT"]),
            pd.DataFrame(wil, columns=["PROVINSI", "KODE_PROVINSI", "KAB_KOTA", "KODE_KAB_KOTA"]))


def bangun_pedoman(df_seg, df_wil):
    segm = {str(a).strip().upper(): int(b) for a, b in zip(df_seg["SEGMENT"], df_seg["KODE_SEGMENT"])}
    wm, amb = {}, set()
    for k, kp, kk in zip(df_wil["KAB_KOTA"], df_wil["KODE_PROVINSI"], df_wil["KODE_KAB_KOTA"]):
        key = _norm_kab(k)
        if key in wm and wm[key] != (int(kp), int(kk)):
            amb.add(key)
        wm.setdefault(key, (int(kp), int(kk)))
    by_base = defaultdict(list)
    for key in wm:
        by_base[kunci_wilayah(key)[1]].append(key)
    return {"seg": segm, "wil": wm, "amb": amb, "by_base": dict(by_base),
            "n_prov": int(df_wil["KODE_PROVINSI"].nunique()), "n_wil": len(df_wil)}


def peta_id(df_lama, ids_asli=None):
    """Nomor urut tertinggi per prefix, dan prefix master per (kota, segmen)."""
    max_seq, prefix_map = defaultdict(int), {}
    for src in (df_lama, ids_asli):
        if src is None:
            continue
        p = src["ID_STR_OUTLET"].dropna().astype(str).str.rsplit(".", n=1, expand=True)
        if p.shape[1] != 2:
            continue
        ok = p[1].str.isdigit().fillna(False)
        g = pd.DataFrame({"p": p.loc[ok, 0], "s": p.loc[ok, 1].astype(int)}).groupby("p")["s"].max()
        for k, v in g.items():
            max_seq[k] = max(max_seq[k], int(v))
    ids = df_lama[["ID_STR_OUTLET", "KOTA_BARU", "SEGMENT_BARU"]].dropna()
    p = ids["ID_STR_OUTLET"].astype(str).str.rsplit(".", n=1, expand=True)
    if p.shape[1] == 2:
        ids = ids.assign(PREFIX=p[0])
        first = ids.drop_duplicates(["KOTA_BARU", "SEGMENT_BARU"])
        prefix_map = {(k, s): x for k, s, x in zip(first["KOTA_BARU"], first["SEGMENT_BARU"], first["PREFIX"])}
    return dict(max_seq), prefix_map


def _s(v):
    return "" if v is None or pd.isna(v) else str(v).strip().upper()


KOLOM_SAMA = ["ID_MASTER_SAMA", "PNAMLANG_MASTER_SAMA", "ALAMAT_MASTER_SAMA", "SKOR_ALAMAT_SAMA",
              "CUST_ID_MASTER_SAMA", "JML_ROW_MASTER_SAMA", "_NAMA_MASTER_SAMA", "_KOTA_MASTER_SAMA", "_SEG_MASTER_SAMA"]
KOLOM_TEKNIS_REVIEW = {"GABUNG", "NAMA_KOTOR", "ID_MASTER_SAMA", "PNAMLANG_MASTER_SAMA", "ALAMAT_MASTER_SAMA",
                       "SKOR_ALAMAT_SAMA", "CUST_ID_MASTER_SAMA", "JML_ROW_MASTER_SAMA", "KEPUTUSAN"}


def cek_nama_kotor(nama):
    """Daftar masalah pada PNAMLANG_AKHIR. Pola yang diharapkan: NAMA (KOTA), SEGMENT."""
    if nama is None or pd.isna(nama) or not str(nama).strip():
        return []
    t, m = str(nama).strip(), []
    if "-" in t:
        m.append("ada tanda '-'")
    if t.count(",") > 1:
        m.append(f"tanda ',' {t.count(',')} kali")
    if "/" in t or "\\" in t:
        m.append("ada tanda '/'")
    if re.search(r"[;:\"`@#*+=\[\]{}|<>?!~^_%$]", t):
        m.append("ada simbol tidak lazim")
    if t.count("(") != t.count(")") or t.count("(") > 1 or re.search(r"\(\s*\)", t):
        m.append("tanda kurung tidak wajar")
    if re.search(r"\s{2,}", t) or re.search(r"\.{2,}", t):
        m.append("spasi/titik ganda")
    if re.search(r"^[\s,.\-]|[\s,\-]$", t):
        m.append("diawali/diakhiri tanda baca")
    if t != t.upper():
        m.append("ada huruf kecil")
    if not re.search(r",\s*[A-Z0-9][A-Z0-9 .]*$", t):
        m.append("belum ada ', SEGMENT' di akhir")
    return m


def beri_id(calon, max_seq, prefix_map, pedoman, known_wil=None):
    """Beri ID_STR_OUTLET (pratinjau) + CATATAN_CEK. Urutan alfabet: kota, segmen, nama. Baris BUANG dilewati."""
    d = calon.copy()
    if "BUANG" not in d.columns:
        d["BUANG"] = False
    d["BUANG"] = d["BUANG"].fillna(False).astype(bool)
    ids = pd.Series("", index=d.index, dtype=object)
    cat = pd.Series("", index=d.index, dtype=object)
    seg_map = pedoman["seg"] if pedoman else {}
    wil_map = pedoman["wil"] if pedoman else {}
    amb = pedoman["amb"] if pedoman else set()
    nm = d["PNAMLANG_AKHIR"].map(_s)
    kt = d["KOTA_BARU"].map(_norm_kab)
    sg = d["SEGMENT_BARU"].map(_s)
    if "GABUNG" not in d.columns:
        d["GABUNG"] = False
    d["GABUNG"] = d["GABUNG"].fillna(False).astype(bool)
    idm = d["ID_MASTER_SAMA"].fillna("").astype(str).str.strip() if "ID_MASTER_SAMA" in d.columns else pd.Series("", index=d.index)
    gab = d["GABUNG"] & (idm != "") & ~d["BUANG"]   # digabung: ID mengikuti outlet master, tidak memakai nomor urut baru
    aktif = ~d["BUANG"] & ~gab
    dupkey = nm + "|" + kt + "|" + sg
    dup = dupkey[aktif].duplicated(keep=False).reindex(d.index, fill_value=False) & (nm != "")
    nk = pd.Series("", index=d.index, dtype=object)
    seq = dict(max_seq)
    order = sorted(d.index[aktif], key=lambda i: (kt[i] == "", kt[i], sg[i], nm[i]))
    for i in order:
        notes = []
        k, s = kt[i], sg[i]
        sc, wc = seg_map.get(s), wil_map.get(k)
        if pedoman:
            if not s:
                notes.append("Segmen kosong")
            elif sc is None:
                notes.append(f"Segmen '{s}' tidak ada di pedoman")
            if not k:
                notes.append("Kota kosong")
            elif wc is None:
                kand = pedoman.get("by_base", {}).get(kunci_wilayah(k)[1], [])
                if len(kand) > 1:
                    notes.append(f"Kota '{k}' ada sebagai {' dan '.join(kand)} di pedoman; pilih salah satu di kolom KOTA_BARU")
                else:
                    notes.append(f"Kota '{k}' tidak ada di pedoman")
            elif k in amb:
                notes.append("Nama kota ganda di pedoman (pastikan provinsinya)")
        else:
            notes.append("Pedoman ID belum diunggah (menu Pedoman ID)")
        mp = prefix_map.get((d.at[i, "KOTA_BARU"], d.at[i, "SEGMENT_BARU"]))
        prefix = None
        if sc is not None and wc is not None:
            prefix = f"{sc}.{wc[0]}.{wc[1]}"
            if mp and mp != prefix:
                notes.append(f"Prefix pedoman ({prefix}) berbeda dari master ({mp})")
        elif mp:
            prefix = mp
            notes.append("Prefix diambil dari master (tidak lengkap di pedoman)")
        if prefix is None:
            notes.append("ID belum bisa dibuat (kode tidak ditemukan)")
        else:
            seq[prefix] = seq.get(prefix, 0) + 1
            ids[i] = f"{prefix}.{seq[prefix]}"
        if not nm[i]:
            notes.append("Nama kosong")
        if s == "RS.TNI-POL" and not re.search(r",\s*(RSAD|RSAL|RSAU|RSPOL)\s*$", str(d.at[i, "PNAMLANG_AKHIR"]).upper()):
            notes.append("Segmen RS.TNI-POL: suffix di belakang koma (RSAD/RSAL/RSAU/RSPOL) tidak bisa dipastikan; "
                         "isi manual di PNAMLANG_AKHIR")
        kotor = cek_nama_kotor(d.at[i, "PNAMLANG_AKHIR"])
        if kotor:
            nk[i] = "; ".join(kotor)
            notes.append("Nama masih kotor: " + nk[i])
        if d.at[i, "GABUNG"] and idm[i] == "":
            notes.append("GABUNG dipilih tetapi tidak ada outlet master yang cocok")
        if dup[i]:
            notes.append("Muncul lebih dari sekali di file data baru")
        if known_wil and k and not kota_dikenal(k, known_wil):
            notes.append("Kota tidak ada di master_wilayah")
        cd = d.at[i, "_CATATAN_DUP"] if "_CATATAN_DUP" in d.columns else ""
        if isinstance(cd, str) and cd:
            notes.append(cd)
        cat[i] = "; ".join(notes)
    for i in d.index[gab]:
        ids[i], cat[i] = idm[i], ""
    d["ID_STR_OUTLET"] = ids
    d["CATATAN_CEK"] = cat
    d["NAMA_KOTOR"] = nk
    return d


def terapkan_edit(rv, ed, max_seq, prefix_map, pedoman, known_wil):
    """Terapkan hasil edit pengguna (kota/nama akhir/segmen/centang), nama akhir otomatis ikut kota & segmen."""
    d = rv.copy()
    idx = ed.index
    for c in ("KOTA_BARU", "SEGMENT_BARU"):
        d[c] = d[c].astype(object)
        d.loc[idx, c] = [None if _s(x) == "" else _s(x) for x in ed[c]]
    d["PNAMLANG_AKHIR"] = d["PNAMLANG_AKHIR"].astype(object)
    d.loc[idx, "PNAMLANG_AKHIR"] = ed["PNAMLANG_AKHIR"].values
    for c in ("SETUJU", "BUANG", "GABUNG"):
        if c not in ed.columns:
            continue
        d[c] = d[c].astype(bool) if c in d.columns else False
        d.loc[idx, c] = ed[c].fillna(False).astype(bool).values
    ubah = [i for i in idx
            if _s(rv.at[i, "KOTA_BARU"]) != _s(d.at[i, "KOTA_BARU"]) or _s(rv.at[i, "SEGMENT_BARU"]) != _s(d.at[i, "SEGMENT_BARU"])]
    for i in ubah:
        if str(ed.at[i, "PNAMLANG_AKHIR"]) == str(rv.at[i, "PNAMLANG_AKHIR"]):  # nama tidak diedit langsung -> ikut kota/segmen
            suf = d.at[i, "_SUFIKS"] if "_SUFIKS" in d.columns else None
            d.at[i, "PNAMLANG_AKHIR"] = bangun_nama(d.at[i, "_NAMA_DASAR"], d.at[i, "KOTA_BARU"], d.at[i, "SEGMENT_BARU"], suf)
    return beri_id(d, max_seq, prefix_map, pedoman, known_wil)


def siapkan_rv(calon, res, pedoman, known_wil):
    rv = calon.copy().reset_index(drop=True)
    for c in ("KOTA_ASAL", "PNAMLANG_ASAL", "_NAMA_DASAR", "KOTA_BARU", "SEGMENT_BARU", "PNAMLANG_AKHIR"):
        if c not in rv.columns:
            rv[c] = None
    rv["_KOTA_AWAL"], rv["_AKHIR_AWAL"], rv["_SEG_AWAL"] = rv["KOTA_BARU"], rv["PNAMLANG_AKHIR"], rv["SEGMENT_BARU"]
    rv["SETUJU"] = False
    rv["BUANG"] = False
    rv["GABUNG"] = False
    for c in KOLOM_SAMA:
        if c not in rv.columns:
            rv[c] = None
    return beri_id(rv, res["max_seq"], res["prefix_map"], pedoman, known_wil)


SUMBER_REVIEW, SUMBER_SAMA, SUMBER_CUST, SUMBER_OTO = (
    "Review cleansing & ID baru", "Sama dengan outlet master", "Keputusan cust_id", "Cek otomatis")
JENIS_SUMBER_ENGINE = {"CUST_ID SAMA (DIELIMINASI)": SUMBER_CUST, "TIMPA PNAMLANG": SUMBER_CUST, "GABUNG ROW": SUMBER_CUST,
                       "EDIT NAMA MASTER": SUMBER_CUST}


def susun_log(res, rv):
    """Log perubahan dari SEMUA tab: keputusan cust_id (dari mesin), serta Review dan 'Sama dengan outlet master'
    (dari keadaan rv saat ini). Kolom SUMBER menunjukkan tab asalnya. Tidak memerlukan semua baris sudah ber-ID."""
    log = []
    lg = res.get("log")
    for e in (lg.to_dict("records") if lg is not None and len(lg) else []):
        e = dict(e)
        e["SUMBER"] = JENIS_SUMBER_ENGINE.get(e.get("JENIS"), SUMBER_OTO)
        log.append(e)
    L = lambda sumber, j, i, d, row=None: log.append(
        {"SUMBER": sumber, "JENIS": j, "ID_STR_OUTLET": i, "DETAIL": d, **(snap_log(row) if row is not None else {})})
    cm = res.get("cust_match")
    cust_baru = set(cm.loc[cm["AKSI"] == "BARU", "BARIS_EXCEL"]) if cm is not None and len(cm) else set()
    for _, r in rv.iterrows():
        ada_m = _t(r.get("ID_MASTER_SAMA")).strip() != ""
        sm = SUMBER_SAMA if ada_m else (SUMBER_CUST if r.get("BARIS_EXCEL") in cust_baru else SUMBER_REVIEW)
        nama = r["PNAMLANG_AKHIR"]
        if r["BUANG"]:
            L(sm, "DIBUANG (DUPLIKAT)", "", f"{nama} (baris {r.get('BARIS_EXCEL')}) tidak dijadikan ID baru", row=r)
            continue
        if r["GABUNG"] and ada_m:
            L(sm, "GABUNG ROW (OUTLET SAMA)", r["ID_STR_OUTLET"],
              f"'{nama}' (baris {r.get('BARIS_EXCEL')}) digabung ke outlet master; nama+kota+segmen sama, "
              f"alamat baru '{r.get('ALAMAT')}' vs master '{r.get('ALAMAT_MASTER_SAMA')}'; row baru dengan ID master", row=r)
            continue
        if (_s(r["KOTA_BARU"]) != _s(r["_KOTA_AWAL"]) or _s(r["SEGMENT_BARU"]) != _s(r["_SEG_AWAL"])
                or _s(nama) != _s(r["_AKHIR_AWAL"])):
            L(sm, "EDIT MANUAL", r["ID_STR_OUTLET"], f"{r['_AKHIR_AWAL']} / {r['_KOTA_AWAL']} / {r['_SEG_AWAL']}  ->  "
              f"{nama} / {r['KOTA_BARU']} / {r['SEGMENT_BARU']}", row=r)
        if r["SETUJU"] and _t(r.get("CATATAN_CEK")).strip() and not ada_m:
            L(sm, "DISETUJUI", r["ID_STR_OUTLET"], f"{nama}: catatan disetujui ({r['CATATAN_CEK']})", row=r)
        ket = " (diputuskan outlet berbeda dari master " + _t(r.get("ID_MASTER_SAMA")) + ")" if ada_m and r["SETUJU"] else ""
        L(sm, "ID BARU", r["ID_STR_OUTLET"], f"{nama} | {r['KOTA_BARU']} | {r['SEGMENT_BARU']}{ket}", row=r)
    return pd.DataFrame(log)


def selesaikan(res, rv):
    """Susun master final dari master lama + calon (setelah edit & persetujuan)."""
    calon = rv[~rv["BUANG"]].copy()
    if (calon["ID_STR_OUTLET"].fillna("") == "").any():
        raise ValueError("Masih ada baris tanpa ID_STR_OUTLET. Perbaiki kota/segmen atau centang BUANG.")
    log_df = susun_log(res, rv)
    log = log_df.to_dict("records")
    L = lambda j, i, d, row=None: log.append(
        {"SUMBER": SUMBER_OTO, "JENIS": j, "ID_STR_OUTLET": i, "DETAIL": d, **(snap_log(row) if row is not None else {})})
    calon = calon.sort_values("ID_STR_OUTLET", kind="stable")
    kolom_calon = list(calon.columns)
    gm = calon["GABUNG"].astype(bool) & (calon["ID_MASTER_SAMA"].fillna("").astype(str).str.strip() != "")
    calon_gab = calon[gm].copy()
    calon = calon[~gm]
    for kol_, sumber_ in (("PNAMLANG_AKHIR", "_NAMA_MASTER_SAMA"), ("KOTA_BARU", "_KOTA_MASTER_SAMA"), ("SEGMENT_BARU", "_SEG_MASTER_SAMA")):
        calon_gab[kol_] = calon_gab[sumber_]   # nama/kota/segmen mengikuti outlet master
    df_lama = res["master_lama"]
    baku = ["KOTA_BARU", "SEGMENT_BARU", "PNAMLANG_AKHIR"]
    kolom_master = list(df_lama.columns) + [c for c in baku if c not in df_lama.columns]
    teknis = {"BARIS_EXCEL", "SETUJU", "BUANG", "CATATAN_CEK", "KOTA_ASAL", "PNAMLANG_ASAL", "SUMBER", "GRUP",
              "KEPUTUSAN", "KEPUTUSAN (isi manual)", "OPSI_NAMA"} | KOLOM_TEKNIS_REVIEW
    dibuang = [c for c in kolom_calon if c not in kolom_master and c not in teknis and not str(c).startswith("_")]
    if dibuang:
        L("INFO", "", "Kolom data baru yang tidak ada di skema master (tidak dimasukkan): " + ", ".join(map(str, dibuang)))
    bagian = [df_lama, calon[[c for c in calon.columns if c in kolom_master]]]
    gabung_res = res.get("gabung")
    ekstra = [g for g in (gabung_res if gabung_res is not None else pd.DataFrame(), calon_gab) if len(g)]
    for g in ekstra:   # row tambahan ber-ID master: dari pencocokan cust_id/tail dan dari opsi GABUNG di Review
        bagian.append(g[[c for c in g.columns if c in kolom_master]])
    gabung = pd.concat(ekstra, ignore_index=True) if ekstra else pd.DataFrame()
    df_final = pd.concat(bagian, ignore_index=True)
    df_final = df_final.reindex(columns=kolom_master)
    perlu = []
    for _, r in rv[~rv["BUANG"] & (rv["CATATAN_CEK"].astype(str).str.strip() != "")].iterrows():
        perlu.append({"MASALAH": r["CATATAN_CEK"], "ID_STR_OUTLET": r["ID_STR_OUTLET"], "DETAIL": r["PNAMLANG_AKHIR"],
                      "DISETUJUI": "YA" if r["SETUJU"] else "BELUM"})
    dup = df_final[df_final["ID_STR_OUTLET"].isin(set(calon["ID_STR_OUTLET"])) & df_final["ID_STR_OUTLET"].duplicated(keep=False)]
    for _, r in dup.iterrows():
        perlu.append({"MASALAH": "ID baru bentrok dengan ID lain", "ID_STR_OUTLET": r["ID_STR_OUTLET"],
                      "DETAIL": r.get("PNAMLANG_AKHIR", ""), "DISETUJUI": "BELUM"})
    id_baru = calon[[c for c in calon.columns if not str(c).startswith("_") and c not in
                     ({"SETUJU", "BUANG", "KOTA_ASAL", "PNAMLANG_ASAL"} | KOLOM_TEKNIS_REVIEW)]]
    id_baru = id_baru[["ID_STR_OUTLET"] + [c for c in id_baru.columns if c != "ID_STR_OUTLET"]]
    stats = dict(res["stats"])
    stats.update({"ID baru dibuat": len(calon), "Digabung ke outlet master (Review)": len(calon_gab),
                  "Master final": len(df_final), "Perlu dicek": len(perlu)})
    return {"master": df_final, "id_baru": id_baru, "log": pd.DataFrame(log), "cek_manual": res["cek_manual"], "cust_match": res.get("cust_match", pd.DataFrame()),
            "gabung": gabung if gabung is not None else pd.DataFrame(),
            "perlu_cek": pd.DataFrame(perlu, columns=["MASALAH", "ID_STR_OUTLET", "DETAIL", "DISETUJUI"]), "stats": stats}


OPSI_REVIEW = ["(belum)", "SETUJU", "BUANG"]
OPSI_SAMA = ["(belum)", "ID BARU (outlet berbeda)", "GABUNG KE MASTER", "BUANG"]


def tabel_review(rv, sama):
    """Tabel tampilan Review dengan kolom centang SETUJU / GABUNG / BUANG (tidak pernah dua centang sekaligus).
    sama=False: baris tanpa pembanding master; sama=True: baris yang nama+kota+segmennya sama dengan outlet master."""
    mask = rv["ID_MASTER_SAMA"].fillna("").astype(str).str.strip() != ""
    d = rv[mask if sama else ~mask].copy()
    buang = d["BUANG"].fillna(False).astype(bool)
    gab = d["GABUNG"].fillna(False).astype(bool) & bool(sama) & ~buang
    d["BUANG"] = buang
    d["GABUNG"] = gab
    d["SETUJU"] = d["SETUJU"].fillna(False).astype(bool) & ~buang & ~gab
    return d


def keputusan_ke_data(rv, ed):
    """Ubah hasil edit tabel (kolom centang) menjadi kolom SETUJU/BUANG/GABUNG untuk terapkan_edit.
    Centang yang baru ditekan menang atas centang lama pada baris yang sama (BUANG > GABUNG > SETUJU)."""
    sub = rv.loc[ed.index].copy()
    ambil = lambda t, c: t[c].fillna(False).astype(bool) if c in t.columns else pd.Series(False, index=ed.index)
    b, g, s_ = ambil(ed, "BUANG"), ambil(ed, "GABUNG"), ambil(ed, "SETUJU")
    pb, pg, ps = ambil(sub, "BUANG"), ambil(sub, "GABUNG"), ambil(sub, "SETUJU")
    nb, ng, ns = b & ~pb, g & ~pg, s_ & ~ps
    baru = nb | ng | ns
    fb = np.where(baru, nb, b)
    fg = np.where(baru, ng & ~nb, g & ~b)
    fs = np.where(baru, ns & ~nb & ~ng, s_ & ~b & ~g)
    sub["BUANG"], sub["GABUNG"], sub["SETUJU"] = fb.astype(bool), fg.astype(bool), fs.astype(bool)
    for c in ("KOTA_BARU", "SEGMENT_BARU", "PNAMLANG_AKHIR"):
        if c in ed.columns:
            sub[c] = ed[c].values
    return sub


def master_serupa(df_lama, id_str, nama_baru, alamat_baru):
    """Semua baris master ber-ID_STR_OUTLET tertentu, diurutkan dari yang paling mirip dengan data baru."""
    sub = df_lama[df_lama["ID_STR_OUTLET"].astype(str) == str(id_str)].copy()
    kol_a = deteksi_kolom(df_lama, "alamat")
    sub["SKOR_NAMA"] = [None if (v := sim(_tanpa_kota(nama_baru), _tanpa_kota(n), STOP_NAMA)) is None else round(v, 2)
                        for n in sub["PNAMLANG_AKHIR"]]
    sub["SKOR_ALAMAT"] = [None if kol_a is None or (v := sim(alamat_baru, a, STOP_ALAMAT)) is None else round(v, 2)
                          for a in (sub[kol_a] if kol_a else [None] * len(sub))]
    sub = sub.sort_values(["SKOR_ALAMAT", "SKOR_NAMA"], ascending=False, na_position="last")
    kol = [deteksi_kolom(df_lama, "cust_id"), deteksi_kolom(df_lama, "distributor"), "PNAMLANG_AKHIR", kol_a,
           "KOTA_BARU", "SEGMENT_BARU", "SKOR_NAMA", "SKOR_ALAMAT"]
    return sub[[c for c in dict.fromkeys(kol) if c and c in sub.columns]]


# ------------------------------------------------------------------------------
# TABEL KEPUTUSAN (tab 'Sama dengan outlet master' & 'Keputusan cust_id'): susunan kolom
#   KEPUTUSAN | CATATAN_CEK | ID_STR_OUTLET_BARU | DATA_BARU (PNAMLANG, ALAMAT, KOTA) | DATA_LAMA (PNAMLANG, ALAMAT, KOTA)
# ------------------------------------------------------------------------------
KEP_BARU, KEP_GABUNG, KEP_BUANG, KEP_BELUM = "ID BARU (outlet berbeda)", "GABUNG KE MASTER", "BUANG", "(belum)"
LABEL_BARU, LABEL_LAMA = "🟦 ", "🟧 "   # penanda kelompok kolom: DATA_BARU / DATA_LAMA (master)


def _t(v):
    return "" if v is None or pd.isna(v) else str(v)


def keputusan_sama_label(d):
    """Label keputusan per baris tab 'Sama dengan outlet master' dari centang BUANG / GABUNG / SETUJU."""
    return pd.Series(np.select([d["BUANG"].astype(bool), d["GABUNG"].astype(bool), d["SETUJU"].astype(bool)],
                               [KEP_BUANG, KEP_GABUNG, KEP_BARU], default=KEP_BELUM), index=d.index, dtype=object)


def id_baru_tampil(kep, id_str):
    """ID_STR_OUTLET_BARU baru terisi setelah ada keputusan: ID BARU (nomor urut) atau GABUNG (ID outlet master).
    BUANG dan yang belum diputuskan dikosongkan."""
    ok = kep.isin([KEP_BARU, KEP_GABUNG])
    return id_str.fillna("").astype(str).where(ok, "")


def tabel_sama_editor(rv, kol_ab, pilih=None):
    """Tabel editor tab 'Sama dengan outlet master' (indeks = indeks rv)."""
    d = tabel_review(rv, True)
    kep = keputusan_sama_label(d)
    t = pd.DataFrame({
        "DETAIL": [pilih is not None and i == pilih for i in d.index],
        "KEPUTUSAN": kep,
        "CATATAN_CEK": d["CATATAN_CEK"],
        "ID_STR_OUTLET_BARU": id_baru_tampil(kep, d["ID_STR_OUTLET"]),
        "PNAMLANG_BARU": d["PNAMLANG_AKHIR"],
        "ALAMAT_BARU": d[kol_ab] if kol_ab and kol_ab in d.columns else "",
        "KOTA_BARU": d["KOTA_BARU"],
        "PNAMLANG_MASTER": d["PNAMLANG_MASTER_SAMA"],
        "ALAMAT_MASTER": d["ALAMAT_MASTER_SAMA"],
        "KOTA_MASTER": d["_KOTA_MASTER_SAMA"],
        "ID_STR_OUTLET_MASTER": d["ID_MASTER_SAMA"],
    }, index=d.index)
    for c in t.columns:
        if c != "DETAIL":
            t[c] = t[c].map(_t)
    return t


def sama_edit_ke_rv(rv, ed):
    """Hasil edit tabel (KEPUTUSAN, PNAMLANG_BARU, KOTA_BARU) -> kolom yang dipahami terapkan_edit."""
    sub = rv.loc[ed.index, ["KOTA_BARU", "SEGMENT_BARU", "PNAMLANG_AKHIR", "SETUJU", "BUANG", "GABUNG"]].copy()
    sub["KOTA_BARU"] = [None if _s(x) == "" else str(x) for x in ed["KOTA_BARU"]]
    sub["PNAMLANG_AKHIR"] = ed["PNAMLANG_BARU"].map(_t).values
    k = ed["KEPUTUSAN"]
    sub["BUANG"], sub["GABUNG"], sub["SETUJU"] = (k == KEP_BUANG).values, (k == KEP_GABUNG).values, (k == KEP_BARU).values
    return sub


def pilih_detail(ed_detail, lama):
    """Satu baris DETAIL saja: centang yang baru ditekan menang; None bila tidak ada yang tercentang."""
    on = [i for i, v in ed_detail.items() if bool(v)]
    if not on:
        return None
    baru = [i for i in on if i != lama]
    return baru[-1] if baru else on[-1]


def aksi_id_cust(aksi, id_rv, id_master):
    """ID_STR_OUTLET_BARU untuk baris cust_id: BARU -> ID baru dari rv; GABUNG -> ID outlet master; lainnya kosong."""
    if aksi == "BARU":
        return _t(id_rv)
    if aksi in ("GABUNG_LAMA", "TIMPA_GABUNG"):
        return _t(id_master)
    return ""


def tabel_cust_editor(cmatch, rv, jenis, opsi_label, pilih=None):
    """Tabel editor keputusan cust_id (indeks = BARIS_EXCEL). Baris yang sudah jadi calon ID baru memakai nilai terkini di rv,
    sehingga edit di tab Review dan di sini saling mengikuti."""
    d = cmatch[cmatch["JENIS_MATCH"] == jenis]
    rvx = rv.drop_duplicates("BARIS_EXCEL").set_index("BARIS_EXCEL") if len(rv) else rv.set_index("BARIS_EXCEL")
    baris, kep, idb, nama, kota = [], [], [], [], []
    for _, r in d.iterrows():
        b, a = r["BARIS_EXCEL"], r["AKSI"]
        a = None if a is None or pd.isna(a) else a
        in_rv = a == "BARU" and b in rvx.index
        kep.append(LABEL_AKSI[a] if a in LABEL_AKSI and LABEL_AKSI[a] in opsi_label else opsi_label[0])
        idb.append(aksi_id_cust(a, rvx.at[b, "ID_STR_OUTLET"] if in_rv else "", r["ID_STR_OUTLET_MASTER"]))
        nama.append(_t(rvx.at[b, "PNAMLANG_AKHIR"]) if in_rv else _t(r["PNAMLANG_BARU"]))
        kota.append(_t(rvx.at[b, "KOTA_BARU"]) if in_rv else _t(r["KOTA_BARU"]))
        baris.append(b)
    t = pd.DataFrame({
        "DETAIL": [pilih is not None and b == pilih for b in baris],
        "KEPUTUSAN": kep,
        "CATATAN_CEK": [_t(x) for x in d["SARAN"]],
        "ID_STR_OUTLET_BARU": idb,
        "PNAMLANG_BARU": nama,
        "ALAMAT_BARU": [_t(x) for x in d["ALAMAT_BARU"]],
        "KOTA_BARU": kota,
        "PNAMLANG_MASTER": [_t(x) for x in d["PNAMLANG_MASTER"]],
        "ALAMAT_MASTER": [_t(x) for x in d["ALAMAT_MASTER"]],
        "KOTA_MASTER": [_t(x) for x in d["KOTA_MASTER"]],
        "ID_STR_OUTLET_MASTER": [_t(x) for x in d["ID_STR_OUTLET_MASTER"]],
        "CUST_ID_BARU": [_t(x) for x in d["CUST_ID_BARU"]],
        "CUST_ID_MASTER": [_t(x) for x in d["CUST_ID_MASTER"]],
        "SKOR_NAMA": [_t(x) for x in d["SKOR_NAMA"]],
        "SKOR_ALAMAT": [_t(x) for x in d["SKOR_ALAMAT"]],
        "NAMA_KOTOR": [_t(x) for x in d["NAMA_KOTOR"]],
    }, index=pd.Index(baris, name="BARIS_EXCEL"))
    return t


def selisih_cust(t0, ed):
    """Bandingkan tabel cust sebelum/sesudah diedit. Kembalikan dict baris -> {kolom: nilai baru} untuk
    KEPUTUSAN / PNAMLANG_BARU / KOTA_BARU / PNAMLANG_MASTER yang berubah."""
    out = {}
    for b in ed.index:
        if b not in t0.index:
            continue
        ch = {c: _t(ed.at[b, c]).strip() for c in ("KEPUTUSAN", "PNAMLANG_BARU", "KOTA_BARU", "PNAMLANG_MASTER")
              if _t(ed.at[b, c]).strip() != _t(t0.at[b, c]).strip()}
        if ch:
            out[b] = ch
    return out


def terapkan_selisih_overrides(selisih, keputusan, ko, no, pm, label_ke_aksi=None):
    """Ubah dict keputusan/override dari selisih tabel cust. Mengembalikan salinan baru (dec, ko, no, pm)."""
    label_ke_aksi = label_ke_aksi or AKSI_DARI_LABEL
    dec, ko, no, pm = dict(keputusan), dict(ko), dict(no), dict(pm)
    for b, ch in selisih.items():
        if "KEPUTUSAN" in ch:
            a = label_ke_aksi.get(ch["KEPUTUSAN"])
            if a is None:
                dec.pop(b, None)
            else:
                dec[b] = a
        if "KOTA_BARU" in ch:
            if ch["KOTA_BARU"]:
                ko[b] = ch["KOTA_BARU"]
            else:
                ko.pop(b, None)
            if "PNAMLANG_BARU" not in ch:
                no.pop(b, None)          # hanya kota yang diganti: nama dibangun ulang mengikuti kota
        if "PNAMLANG_BARU" in ch:
            if ch["PNAMLANG_BARU"]:
                no[b] = ch["PNAMLANG_BARU"]
            else:
                no.pop(b, None)
        if "PNAMLANG_MASTER" in ch and ch["PNAMLANG_MASTER"]:
            pm[b] = ch["PNAMLANG_MASTER"]
    return dec, ko, no, pm


# ==============================================================================
# PENYIMPANAN SQLITE (master permanen, backup, riwayat)
# ==============================================================================
import glob
import hashlib
import os
import shutil
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

DB_PATH = os.environ.get("MDM_DB_PATH", "mdm_master.db")
DRIVE_DIR = os.environ.get("MDM_DRIVE_DIR", "")  # opsional: folder Google Drive untuk salinan permanen
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backup")
KEEP_BACKUP = 20


def now_wib():
    return datetime.now(ZoneInfo("Asia/Jakarta"))


def _con():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute(
        "CREATE TABLE IF NOT EXISTS riwayat (id INTEGER PRIMARY KEY AUTOINCREMENT, waktu TEXT, jenis TEXT, "
        "nama_file TEXT, hash_file TEXT, ringkasan TEXT, backup TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS log_perubahan (batch INTEGER, jenis TEXT, id_str_outlet TEXT, detail TEXT)"
    )
    con.commit()
    return con


def db_ready():
    if not os.path.exists(DB_PATH):
        return False
    con = _con()
    try:
        return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='master'").fetchone() is not None
    finally:
        con.close()


def master_info():
    con = _con()
    try:
        n = con.execute("SELECT COUNT(*) FROM master").fetchone()[0]
        last = con.execute("SELECT id, waktu, jenis, nama_file FROM riwayat ORDER BY id DESC LIMIT 1").fetchone()
        return n, last
    finally:
        con.close()


def load_master():
    con = _con()
    try:
        return pd.read_sql("SELECT * FROM master", con)
    finally:
        con.close()


def load_wilayah():
    con = _con()
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wilayah'").fetchone() is None:
            return None
        return pd.read_sql("SELECT * FROM wilayah", con)
    finally:
        con.close()


def save_pedoman(df_seg, df_wil):
    con = _con()
    try:
        df_seg.to_sql("pedoman_segment", con, if_exists="replace", index=False)
        df_wil.to_sql("pedoman_wilayah", con, if_exists="replace", index=False)
        con.commit()
    finally:
        con.close()
    sync_to_drive()


def load_pedoman():
    if not os.path.exists(DB_PATH):
        return None
    con = _con()
    try:
        ada = lambda t: con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None
        if not (ada("pedoman_segment") and ada("pedoman_wilayah")):
            return None
        seg = pd.read_sql("SELECT * FROM pedoman_segment", con)
        wil = pd.read_sql("SELECT * FROM pedoman_wilayah", con)
    finally:
        con.close()
    return bangun_pedoman(seg, wil)


def load_riwayat(limit=50):
    con = _con()
    try:
        return pd.read_sql(f"SELECT * FROM riwayat ORDER BY id DESC LIMIT {int(limit)}", con)
    finally:
        con.close()


def daftar_batch_update():
    con = _con()
    try:
        return pd.read_sql("SELECT id, waktu, nama_file FROM riwayat WHERE jenis='UPDATE' ORDER BY id DESC", con)
    finally:
        con.close()


def load_id_baru(batch=None):
    """Baris master yang mendapat ID baru (log 'ID BARU') pada satu batch update, atau semua batch bila batch=None."""
    con = _con()
    try:
        sub = "SELECT id_str_outlet FROM log_perubahan WHERE jenis='ID BARU'" + (" AND batch=?" if batch is not None else "")
        return pd.read_sql(f"SELECT * FROM master WHERE ID_STR_OUTLET IN ({sub})", con,
                           params=(int(batch),) if batch is not None else None)
    finally:
        con.close()


def hash_sudah_disimpan(h):
    con = _con()
    try:
        return con.execute("SELECT 1 FROM riwayat WHERE hash_file=? AND jenis='UPDATE'", (h,)).fetchone() is not None
    finally:
        con.close()


def _prune(folder):
    files = sorted(glob.glob(os.path.join(folder, "*.db")))
    for f in files[:-KEEP_BACKUP]:
        os.remove(f)


def make_backup(label):
    if not os.path.exists(DB_PATH):
        return ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    fn = os.path.join(BACKUP_DIR, f"mdm_{now_wib():%Y%m%d_%H%M%S}_{label}.db")
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(fn)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    _prune(BACKUP_DIR)
    return fn


def sync_to_drive():
    """Salin DB + backup ke Drive (tulis ke file sementara lalu diganti, supaya tidak setengah tertulis)."""
    if not DRIVE_DIR:
        return
    os.makedirs(os.path.join(DRIVE_DIR, "backup"), exist_ok=True)
    tujuan = os.path.join(DRIVE_DIR, os.path.basename(DB_PATH))
    shutil.copy2(DB_PATH, tujuan + ".tmp")
    os.replace(tujuan + ".tmp", tujuan)
    for f in glob.glob(os.path.join(BACKUP_DIR, "*.db")):
        d = os.path.join(DRIVE_DIR, "backup", os.path.basename(f))
        if not os.path.exists(d):
            shutil.copy2(f, d)
    _prune(os.path.join(DRIVE_DIR, "backup"))


def save_master(df_master, df_log, jenis, nama_file, hash_file, ringkasan, df_wil=None):
    """Tulis master baru secara atomik: tabel sementara dulu, lalu tukar dalam satu transaksi."""
    bk = make_backup(f"sebelum_{jenis.lower()}")
    con = _con()
    try:
        con.execute("DROP TABLE IF EXISTS master_tmp")
        df_master.to_sql("master_tmp", con, if_exists="replace", index=False, chunksize=5000)
        if df_wil is not None:
            df_wil.to_sql("wilayah", con, if_exists="replace", index=False)
        con.isolation_level = None
        con.execute("BEGIN")
        try:
            con.execute("DROP TABLE IF EXISTS master")
            con.execute("ALTER TABLE master_tmp RENAME TO master")
            cur = con.execute(
                "INSERT INTO riwayat (waktu, jenis, nama_file, hash_file, ringkasan, backup) VALUES (?,?,?,?,?,?)",
                (now_wib().strftime("%Y-%m-%d %H:%M:%S"), jenis, nama_file, hash_file, ringkasan, os.path.basename(bk)),
            )
            batch = cur.lastrowid
            if df_log is not None and len(df_log):
                con.executemany(
                    "INSERT INTO log_perubahan VALUES (?,?,?,?)",
                    [(batch, str(r.JENIS), str(r.ID_STR_OUTLET),
                      (f"[{r.SUMBER}] " if getattr(r, "SUMBER", None) else "") + str(r.DETAIL))
                     for r in df_log.itertuples(index=False)],
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    sync_to_drive()


def restore_backup(path):
    make_backup("sebelum_restore")
    src, dst = sqlite3.connect(path), sqlite3.connect(DB_PATH)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    con = _con()
    con.execute(
        "INSERT INTO riwayat (waktu, jenis, nama_file, hash_file, ringkasan, backup) VALUES (?,?,?,?,?,?)",
        (now_wib().strftime("%Y-%m-%d %H:%M:%S"), "RESTORE", os.path.basename(path), "", "Dikembalikan dari backup", ""),
    )
    con.commit()
    con.close()
    sync_to_drive()


# ==============================================================================
# EXCEL
# ==============================================================================
def _engine():
    try:
        import xlsxwriter  # noqa: F401
        return "xlsxwriter"  # jauh lebih cepat untuk 86K baris
    except ImportError:
        return "openpyxl"


def df_to_excel_bytes(sheets):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine=_engine()) as xw:
        for name, d in sheets.items():
            d.to_excel(xw, sheet_name=name, index=False)
    return buf.getvalue()


def to_excel_bytes(res):
    sheets = {
        "MASTER_FINAL": rapatkan(res["master"]), "ID_BARU": rapatkan(res["id_baru"]),
        "LOG_PERUBAHAN": res["log"], "PERLU_DICEK": res["perlu_cek"],
    }
    if len(res.get("cust_match", [])):
        sheets["KEPUTUSAN_CUST"] = res["cust_match"]
    if len(res.get("gabung", [])):
        sheets["GABUNG_ROW"] = res["gabung"][[c for c in res["gabung"].columns if not str(c).startswith("_")]]
    return df_to_excel_bytes(sheets)


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def nama_file_master():
    return f"DATA_MASTER_{now_wib():%Y%m%d}.xlsx"


# ------------------------------------------------------------------------------
# FILTER BERGAYA EXCEL (dipakai di beberapa tabel) + EKSPOR HASIL FILTER
# ------------------------------------------------------------------------------
OP_FILTER = {
    "pilih nilai (daftar)": "daftar", "mengandung": "has", "tidak mengandung": "nothas", "sama dengan": "eq",
    "diawali": "starts", "diakhiri": "ends", "kosong": "blank", "tidak kosong": "notblank",
    "lebih besar dari (>)": "gt", "lebih besar atau sama (>=)": "ge", "lebih kecil dari (<)": "lt",
    "lebih kecil atau sama (<=)": "le", "antara (angka)": "between",
}


def _angka(v):
    try:
        t = str(v).strip().replace(",", ".")
        return float(t) if t else None
    except ValueError:
        return None


def mask_kondisi(s, op, nilai):
    """Mask boolean satu kondisi filter pada Series s. None bila nilai belum diisi (kondisi diabaikan).
    op: kode di OP_FILTER. Teks tidak membedakan huruf besar/kecil."""
    t = s.astype(str).where(s.notna(), "")
    kosong = t.str.strip() == ""
    tl = t.str.strip().str.lower()
    if op == "blank":
        return kosong
    if op == "notblank":
        return ~kosong
    if op == "daftar":
        if not nilai:
            return None
        m = t.isin({str(v) for v in nilai if v != "(kosong)"})
        return (m | kosong) if "(kosong)" in nilai else m
    if op in ("has", "nothas", "eq", "starts", "ends"):
        q = str(nilai or "").strip().lower()
        if not q:
            return None
        return {"has": lambda: tl.str.contains(q, regex=False), "nothas": lambda: ~tl.str.contains(q, regex=False),
                "eq": lambda: tl == q, "starts": lambda: tl.str.startswith(q), "ends": lambda: tl.str.endswith(q)}[op]()
    x = pd.to_numeric(t.str.replace(",", ".", regex=False), errors="coerce")
    if op == "between":
        lo, hi = _angka(nilai[0]), _angka(nilai[1])
        if lo is None and hi is None:
            return None
        m = pd.Series(True, index=s.index)
        if lo is not None:
            m &= x >= lo
        if hi is not None:
            m &= x <= hi
        return m
    a = _angka(nilai)
    if a is None:
        return None
    return {"gt": x > a, "ge": x >= a, "lt": x < a, "le": x <= a}[op]


def filter_excel(st, df, key):
    """UI filter seperti Excel: banyak kondisi (kolom + operator + nilai) digabung DAN/ATAU, lalu urut & pilih kolom."""
    n_key = f"{key}_nkond"
    st.session_state.setdefault(n_key, 1)

    def _tambah():
        st.session_state[n_key] += 1

    def _reset():
        for k in [k for k in st.session_state if str(k).startswith(f"{key}_")]:
            del st.session_state[k]

    kolom = list(df.columns)
    mode = st.radio("Gabungkan kondisi dengan", ["DAN (semua terpenuhi)", "ATAU (salah satu terpenuhi)"],
                    horizontal=True, key=f"{key}_mode")
    mask = None
    for i in range(st.session_state[n_key]):
        c1, c2, c3 = st.columns([2, 2, 4])
        kol = c1.selectbox("Kolom", kolom, key=f"{key}_c{i}_kol", index=None, placeholder="pilih kolom",
                           label_visibility="visible" if i == 0 else "collapsed")
        if kol is None:
            continue
        op_label = c2.selectbox("Kondisi", list(OP_FILTER), key=f"{key}_c{i}_op",
                                label_visibility="visible" if i == 0 else "collapsed")
        op = OP_FILTER[op_label]
        nilai = None
        if op == "daftar":
            uniq = df[kol].dropna().astype(str)
            uniq = sorted(uniq[uniq.str.strip() != ""].unique())
            if len(uniq) > 5000:
                c3.warning("Terlalu banyak nilai unik; gunakan 'mengandung'.")
            else:
                opsi = (["(kosong)"] if len(uniq) < len(df) and df[kol].isna().any() else []) + uniq
                nilai = c3.multiselect("Nilai", opsi, key=f"{key}_c{i}_val", placeholder="pilih satu atau beberapa nilai (kosong = semua)",
                                       label_visibility="visible" if i == 0 else "collapsed")
        elif op in ("has", "nothas", "eq", "starts", "ends", "gt", "ge", "lt", "le"):
            nilai = c3.text_input("Nilai", key=f"{key}_c{i}_val", label_visibility="visible" if i == 0 else "collapsed")
        elif op == "between":
            d1, d2 = c3.columns(2)
            nilai = (d1.text_input("Dari", key=f"{key}_c{i}_lo"), d2.text_input("Sampai", key=f"{key}_c{i}_hi"))
        m = mask_kondisi(df[kol], op, nilai)
        if m is not None:
            mask = m if mask is None else ((mask & m) if mode.startswith("DAN") else (mask | m))
    b1, b2, _ = st.columns([1, 1, 4])
    b1.button("+ Tambah kondisi", key=f"{key}_add", on_click=_tambah)
    b2.button("Reset filter", key=f"{key}_reset", on_click=_reset)
    hasil = df if mask is None else df[mask]
    with st.expander("Urutkan dan pilih kolom yang ditampilkan/diekspor"):
        u1, u2 = st.columns([3, 1])
        urut = u1.selectbox("Urutkan berdasarkan", ["(tanpa urutan)"] + kolom, key=f"{key}_urut")
        naik = u2.radio("Arah", ["A-Z / kecil-besar", "Z-A / besar-kecil"], key=f"{key}_arah") == "A-Z / kecil-besar"
        pilih_kol = st.multiselect("Kolom (kosong = semua kolom)", kolom, key=f"{key}_kolom")
    if urut != "(tanpa urutan)":
        x = pd.to_numeric(hasil[urut], errors="coerce")
        angka = x.notna().any() and x.notna().sum() >= hasil[urut].notna().sum() * 0.9
        kunci = x if angka else hasil[urut].astype(str).str.lower().where(hasil[urut].notna())
        hasil = hasil.assign(_kunci_urut=kunci.values).sort_values(
            "_kunci_urut", ascending=naik, na_position="last", kind="stable").drop(columns="_kunci_urut")
    if pilih_kol:
        hasil = hasil[pilih_kol]
    return hasil


def tampil_filter_export(st, df, key, nama_dasar):
    """Filter bergaya Excel + pratinjau + unduh Excel/CSV dari hasil filter (file dibuat setelah tombol Siapkan ditekan)."""
    hasil = filter_excel(st, df, key)
    st.write(f"Hasil filter: **{len(hasil):,}** dari {len(df):,} baris")
    st.dataframe(hasil.head(500), width="stretch")
    if len(hasil) > 500:
        st.caption("Pratinjau menampilkan 500 baris pertama; file unduhan memuat seluruh hasil filter.")
    if len(hasil) == 0:
        return hasil
    sig = (len(hasil), tuple(map(str, hasil.columns)), int(pd.util.hash_pandas_object(hasil.index, index=False).sum()),
           tuple(hasil.index[:5]))
    sk = f"{key}_file"
    if st.button("Siapkan file Excel & CSV dari hasil filter", key=f"{key}_siap"):
        with st.spinner(f"Menyusun {len(hasil):,} baris..."):
            nama = f"{nama_dasar}_{now_wib():%Y%m%d_%H%M}"
            st.session_state[sk] = (sig, nama, df_to_excel_bytes({"HASIL_FILTER": hasil}),
                                    hasil.to_csv(index=False).encode("utf-8-sig"))
    siap = st.session_state.get(sk)
    if siap and siap[0] == sig:
        d1, d2 = st.columns(2)
        d1.download_button(f"Unduh {siap[1]}.xlsx", siap[2], file_name=siap[1] + ".xlsx", mime=XLSX_MIME, key=f"{key}_dl_x")
        d2.download_button(f"Unduh {siap[1]}.csv", siap[3], file_name=siap[1] + ".csv", mime="text/csv", key=f"{key}_dl_c")
    elif siap:
        st.caption("Filter berubah sejak file disiapkan. Tekan tombol di atas lagi untuk memperbarui file.")
    return hasil


def master_cached(st):
    """Master dari database, disimpan di session_state selama versinya (riwayat terakhir) belum berubah."""
    n, last = master_info()
    ver = (last[0] if last else 0, n)
    c = st.session_state.get("master_cache")
    if not c or c[0] != ver:
        st.session_state["master_cache"] = (ver, load_master())
    return st.session_state["master_cache"][1]


# ==============================================================================
# UI STREAMLIT
# ==============================================================================
def page_inisialisasi(st):
    st.subheader("Inisialisasi master (cukup sekali)")
    if db_ready():
        n, _ = master_info()
        st.warning(f"Database sudah berisi master ({n:,} baris). Menjalankan ini akan MENGGANTI master (backup dibuat otomatis).")
    f_master = st.file_uploader("File master lama (.xlsx)", type=["xlsx"], key="init_master")
    sheet = None
    if f_master:
        dm = f_master.getvalue()
        hm = hashlib.sha256(dm).hexdigest()
        if st.session_state.get("init_hash") != hm:
            st.session_state["init_sheets"] = pd.ExcelFile(io.BytesIO(dm)).sheet_names
            st.session_state["init_hash"] = hm
        daftar = st.session_state["init_sheets"]
        sheet = st.selectbox("Sheet master", daftar, index=daftar.index("Hasil ID") if "Hasil ID" in daftar else 0)
    f_wil = st.file_uploader("master_wilayah.csv", type=["csv"], key="init_wil")
    konfirmasi = st.checkbox("Saya yakin", value=not db_ready())
    if st.button("Simpan ke database", type="primary", disabled=not (f_master and sheet and konfirmasi)):
        with st.spinner("Membaca dan menyimpan..."):
            data = f_master.getvalue()
            df = pd.read_excel(io.BytesIO(data), sheet_name=sheet)
            if "ID_STR_OUTLET" not in df.columns:
                st.error("Kolom ID_STR_OUTLET tidak ditemukan di sheet ini.")
                return
            dwil = pd.read_csv(f_wil) if f_wil else None
            save_master(df, None, "INISIALISASI", f_master.name, hashlib.sha256(data).hexdigest(),
                        f"{len(df)} baris", dwil)
        st.success(f"Master tersimpan: {len(df):,} baris. Lanjut ke menu 'Update mingguan'.")


def master_columns():
    con = _con()
    try:
        return [d[0] for d in con.execute("SELECT * FROM master LIMIT 0").description]
    finally:
        con.close()


def _known_dari(df_wil):
    """Peta nama-kota (tanpa spasi/awalan) -> set jenis. Tahan variasi KAB./KABUPATEN/spasi."""
    if df_wil is None:
        return None
    peta = defaultdict(set)
    for c in df_wil.select_dtypes(include="object").columns:
        for x in df_wil[c].dropna():
            j, b = kunci_wilayah(x)
            if b:
                peta[b].add(j)
    return dict(peta) or None


def kota_dikenal(k, known):
    j, b = kunci_wilayah(k)
    if b not in known:
        return False
    js = known[b]
    return j == "" or "" in js or j in js


def _rerun(st):
    """Muat ulang hanya bagian hasil (fragment) bila sedang di dalam fragment; jika tidak, muat ulang penuh."""
    try:
        st.rerun(scope="fragment")
    except TypeError:        # Streamlit lama tanpa parameter scope
        st.rerun()
    except Exception as e:   # bukan di dalam fragment
        if type(e).__name__ == "StreamlitAPIException":
            st.rerun()
        else:
            raise


def cache_db(st):
    """Master, wilayah, dan pedoman dari database disimpan di session_state selama file database belum berubah, supaya tiap
    keputusan tidak membaca ulang 86 ribu baris. 'mdm' menampung indeks cust_id & kunci duplikat yang dipakai run_mdm."""
    ver = os.stat(DB_PATH).st_mtime_ns if os.path.exists(DB_PATH) else 0
    c = st.session_state.get("db_cache")
    if not c or c["ver"] != ver:
        wil = load_wilayah()
        c = {"ver": ver, "wil": wil, "pedoman": load_pedoman(), "known": _known_dari(wil), "master": load_master(), "mdm": {}}
        st.session_state["db_cache"] = c
    return c


def _jalankan(st, keputusan, pertahankan=False):
    a = st.session_state["run_args"]
    c = cache_db(st)
    wil, pedoman, known = c["wil"], c["pedoman"], c["known"]
    res = run_mdm(c["master"], st.session_state["sh_baru"], wil, a["timpa"], a["fallback"],
                  a["sheet_baru"], a["sheet_match"], a["lewati"], a["cust_cfg"], keputusan, pedoman=pedoman,
                  kota_override=st.session_state.get("kota_override", {}), nama_override=st.session_state.get("nama_override", {}),
                  master_nama_override=st.session_state.get("master_nama_override", {}), cache=c["mdm"])
    rv = siapkan_rv(res["calon"], res, pedoman, known)
    lama = st.session_state.get("rv")
    if pertahankan and lama is not None and len(rv):  # edit & centang yang sudah dibuat tidak hilang
        pl = lama.drop_duplicates("BARIS_EXCEL").set_index("BARIS_EXCEL")
        ko_, no_ = st.session_state.get("kota_override", {}), st.session_state.get("nama_override", {})
        for i, b in zip(rv.index, rv["BARIS_EXCEL"]):
            if b in pl.index:
                # baris yang kota/namanya diubah di tab Keputusan cust_id: mengikuti pilihan itu, bukan edit lama di Review
                for c in ("KOTA_BARU", "PNAMLANG_AKHIR", "SEGMENT_BARU", "SETUJU", "BUANG", "GABUNG"):
                    if (c == "KOTA_BARU" and b in ko_) or (c == "PNAMLANG_AKHIR" and (b in ko_ or b in no_)):
                        continue
                    rv.at[i, c] = pl.at[b, c]
        rv = beri_id(rv, res["max_seq"], res["prefix_map"], pedoman, known)
    st.session_state.update(res=res, rv=rv, rv_ver=st.session_state.get("rv_ver", 0) + 1,
                            pedoman=pedoman, known=known, keputusan=dict(keputusan))
    if not pertahankan:  # run baru: mulai dari tab Review. Rerun biasa tidak mengubah tab.
        st.session_state["tab_aktif"] = "review"
        st.session_state["draft_cust"] = {}
        st.session_state["draft_kota"] = {}
        st.session_state["draft_nama"] = {}
        st.session_state["kota_override"] = {}
        st.session_state["nama_override"] = {}
        st.session_state["draft_master"] = {}
        st.session_state["master_nama_override"] = {}
    st.session_state.pop("xlsx", None)


def page_update(st):
    st.subheader("Update mingguan")
    if not db_ready():
        st.warning("Master belum ada di database. Buka menu 'Inisialisasi master' dulu.")
        return
    n, last = master_info()
    c1, c2, c3 = st.columns(3)
    c1.metric("Baris master", f"{n:,}")
    c2.metric("Update terakhir", last[1][:16] if last else "-")
    c3.metric("Versi", last[0] if last else 0)
    if load_pedoman() is None:
        st.warning("Pedoman ID belum diunggah (menu 'Pedoman ID'). Tanpa pedoman, kota/segmen baru tidak bisa diberi ID.")

    f_baru = st.file_uploader("Upload data baru mingguan (.xlsx)", type=["xlsx"])
    with st.expander("Opsi umum"):
        timpa = False
        lewati = st.checkbox(
            "Lewati data yang sama persis dengan master (nama + kota + segmen)", value=True,
            help="Baris yang nama, kota, dan segmennya (setelah cleansing) sudah ada di master tidak diberi ID baru.")
        fallback = ""

    if f_baru:
        data = f_baru.getvalue()
        h = hashlib.sha256(data).hexdigest()
        if st.session_state.get("sh_hash") != h:
            st.session_state["sh_baru"] = pd.read_excel(io.BytesIO(data), sheet_name=None)
            st.session_state["sh_hash"] = h
        sh_baru = st.session_state["sh_baru"]
        daftar = list(sh_baru)
        st.caption("Sheet di file: " + ", ".join(f"{k} ({len(v):,} baris)" for k, v in sh_baru.items()))
        sheet_baru = st.selectbox(
            "Sheet data baru", daftar, index=daftar.index("Data_Baru") if "Data_Baru" in daftar else 0)
        sheet_match = "(tidak ada)"

        # ---- pencocokan cust_id ----
        kol_b = ["(tidak ada)"] + list(sh_baru[sheet_baru].columns)
        kol_m = ["(tidak ada)"] + master_columns()

        def _pilih(wadah, label, opsi, jenis, df_ref):
            d = deteksi_kolom(df_ref, jenis)
            return wadah.selectbox(label, opsi, index=opsi.index(d) if d in opsi else 0, key=f"{label}_{jenis}")

        with st.expander("Pencocokan cust_id & tail (keputusan per baris di tab 'Keputusan cust_id')", expanded=True):
            aktif = st.checkbox("Aktifkan pencocokan cust_id", value=True)
            ca, cb = st.columns(2)
            ca.markdown("**Kolom di data baru**")
            cb.markdown("**Kolom di master**")
            cb_id = _pilih(ca, "cust_id (data baru)", kol_b, "cust_id", sh_baru[sheet_baru])
            cm_id = _pilih(cb, "cust_id (master)", kol_m, "cust_id", pd.DataFrame(columns=kol_m[1:]))
            cb_al = _pilih(ca, "alamat (data baru)", kol_b, "alamat", sh_baru[sheet_baru])
            cm_al = _pilih(cb, "alamat (master)", kol_m, "alamat", pd.DataFrame(columns=kol_m[1:]))
            cb_di = _pilih(ca, "distributor (data baru)", kol_b, "distributor", sh_baru[sheet_baru])
            cm_di = _pilih(cb, "distributor (master)", kol_m, "distributor", pd.DataFrame(columns=kol_m[1:]))
            s1, s2 = st.columns(2)
            a_nama = s1.slider("Ambang mirip nama", 0.5, 1.0, 0.80, 0.01,
                               help="Hanya memengaruhi kolom SARAN di tab Keputusan cust_id (skor ≥ ambang dianggap mirip). Tidak ada aksi otomatis.")
            a_alamat = s2.slider("Ambang mirip alamat", 0.5, 1.0, 0.70, 0.01)
            khusus = st.text_input("Distributor yang cust_id tail-nya (setelah tanda '-') ikut dicocokkan", "KFTD, AAM")
            lingkup = st.checkbox("Cocokkan cust_id hanya di distributor yang sama", value=True,
                                  help="Berlaku jika kolom distributor ada di data baru & master.")
            st.caption("Keputusan untuk baris yang cocok (cust_id sama persis / tail) dibuat per baris di tab 'Keputusan cust_id'.")

        def _o(v):
            return None if v == "(tidak ada)" else v

        cust_cfg = None
        if aktif:
            cust_cfg = {
                "kol_baru": {"cust_id": _o(cb_id), "alamat": _o(cb_al), "distributor": _o(cb_di)},
                "kol_master": {"cust_id": _o(cm_id), "alamat": _o(cm_al), "distributor": _o(cm_di)},
                "ambang_nama": a_nama, "ambang_alamat": a_alamat, "lingkup_distributor": lingkup, "min_tail": 3,
                "distributor_khusus": [x.strip() for x in khusus.split(",") if x.strip()],
            }
        if hash_sudah_disimpan(h):
            st.warning("File ini identik dengan file yang sudah pernah disimpan ke master.")
        if st.button("Jalankan cek & cleansing", type="primary"):
            try:
                with st.spinner("Memproses..."):
                    st.session_state["run_args"] = dict(
                        timpa=timpa, fallback=fallback, sheet_baru=sheet_baru, lewati=lewati,
                        sheet_match=None if sheet_match == "(tidak ada)" else sheet_match, cust_cfg=cust_cfg)
                    _jalankan(st, {})
                    st.session_state.update(
                        fname=nama_file_master(), base_ver=last[0] if last else 0,
                        hash=h, nama_file=f_baru.name, saved=False)
            except Exception as e:
                st.error(f"Gagal: {e}")
                return

    def _isi():
        tampil_hasil_update(st)

    _fragment(st, _isi)


def _fragment(st, fn):
    """Jalankan fn sebagai fragment Streamlit: edit tabel/pilihan di dalamnya hanya memuat ulang bagian ini, bukan seluruh halaman
    (uploader, pengaturan, dan query database di atasnya tidak ikut dijalankan lagi). Streamlit lama tanpa fragment: berjalan biasa."""
    frag = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
    (frag(fn) if frag else fn)()


WARNA_TAB = {"review": "blue", "sama": "orange", "cust": "green", "log": "violet", "master": "gray"}


def pilih_tab(st, label_tab):
    """Pemilih tab dengan penanda jelas: titik hijau + label berwarna + banner 'Sedang dibuka'. Tab terpilih tidak bisa kosong."""
    ss = st.session_state
    aktif = ss.get("tab_aktif")
    if aktif not in label_tab:
        aktif = ss["tab_aktif"] = next(iter(label_tab))

    def fmt(k):
        return ("🟢 " if k == ss.get("tab_aktif") else "⚪ ") + label_tab[k]

    if hasattr(st, "segmented_control"):
        ss["tab_widget"] = aktif

        def _sinkron():
            v = ss.get("tab_widget")
            if v is None:        # klik ulang pada tab yang aktif tidak boleh mengosongkan pilihan
                ss["tab_widget"] = ss.get("tab_aktif")
            else:
                ss["tab_aktif"] = v

        st.segmented_control("Tampilan", list(label_tab), format_func=fmt, key="tab_widget", on_change=_sinkron,
                             label_visibility="collapsed")
        aktif = ss["tab_aktif"]
        st.markdown(f":{WARNA_TAB.get(aktif, 'blue')}-background[**Sedang dibuka: {label_tab[aktif]}**]")
        return aktif
    return st.radio("Tampilan", list(label_tab), format_func=fmt, key="tab_aktif", horizontal=True, label_visibility="collapsed")


def tampil_hasil_update(st):
    """Bagian hasil di Update mingguan (metrik, tab, simpan). Berjalan sebagai fragment."""


    res = st.session_state.get("res")
    if not res:
        return
    rv = st.session_state["rv"]
    st.divider()
    st.write(f"Hasil untuk file: **{st.session_state['nama_file']}**")
    ada_master = rv["ID_MASTER_SAMA"].fillna("").astype(str).str.strip() != ""
    aktif = rv[~rv["BUANG"] & ~(rv["GABUNG"] & ada_master)]
    n_gab_rv = int((~rv["BUANG"]).sum() - len(aktif))
    n_kotor = int((aktif["NAMA_KOTOR"].astype(str).str.strip() != "").sum())
    perlu = aktif["CATATAN_CEK"].astype(str).str.strip() != ""
    n_perlu, n_setuju = int(perlu.sum()), int((perlu & aktif["SETUJU"]).sum())
    n_noid = int((aktif["ID_STR_OUTLET"] == "").sum())
    stats = dict(res["stats"])
    stats.update({"Calon ID baru": len(aktif), "Digabung ke outlet master (Review)": n_gab_rv,
                  "Perlu disetujui": n_perlu, "Sudah disetujui": n_setuju, "Nama masih kotor": n_kotor})
    items = list(stats.items())
    for i in range(0, len(items), 4):
        cols = st.columns(4)
        for col, (k, v) in zip(cols, items[i:i + 4]):
            col.metric(k, f"{v:,}")
    cm = res.get("cek_manual", pd.DataFrame())
    # Pengganti st.tabs: st.tabs kembali ke tab pertama setiap _rerun(st) (itu penyebab klik BUANG pindah ke Cek manual).
    # Pilihan tab disimpan di session_state sehingga tetap di tab yang sedang dibuka.
    n_cm_tab = len(res.get("cust_match", []))
    n_cm_belum = len(res.get("cek_manual", []))
    label_tab = {"review": f"Review cleansing & ID baru ({int((~ada_master).sum())})",
                 "sama": f"Sama dengan outlet master ({int(ada_master.sum())})",
                 "cust": f"Keputusan cust_id ({n_cm_tab}, {n_cm_belum} belum)",
                 "log": "Log perubahan", "master": f"Master lama ({len(res['master_lama']):,} baris)"}
    if st.session_state.get("tab_aktif") not in label_tab:
        st.session_state["tab_aktif"] = "review"
    n_cm = len(res.get("cust_match", []))
    if n_cm:
        st.info(f"{n_cm} baris cocok dengan master lewat cust_id/tail ({len(cm)} belum diputuskan). "
                "Putuskan satu per satu di tab 'Keputusan cust_id' di bawah.")
    if n_kotor:
        st.warning(f"{n_kotor} baris PNAMLANG_AKHIR masih kotor (tanda '-', ',' lebih dari sekali, '/', simbol lain, atau belum ada "
                   "', SEGMENT'). Lihat kolom CATATAN_CEK, perbaiki di kolom PNAMLANG_AKHIR atau setujui bila sudah benar.")
    tab = pilih_tab(st, label_tab)

    if tab == "log":
        tampil_filter_export(st, log_tampil(susun_log(res, rv)), "upd_log", "LOG_PERUBAHAN")
    if tab == "master":
        st.caption("Seluruh master sebelum ID baru digabung (setelah timpa nama dari keputusan cust_id, bila ada).")
        tampil_filter_export(st, rapatkan(res["master_lama"]), "upd_master", "MASTER_LAMA")

    EDIT = ["SETUJU", "BUANG", "KOTA_BARU", "PNAMLANG_AKHIR", "SEGMENT_BARU"]

    def _opsi_kota(tampil_kota, sekarang=""):
        ped = st.session_state.get("pedoman")
        if not ped:
            return None
        opsi = sorted(ped["wil"].keys())
        tambahan = sorted({str(v) for v in list(tampil_kota) + [sekarang] if _t(v) and str(v) not in opsi})
        return opsi + tambahan

    def _tabel_review():
        d = tabel_review(rv, False)
        kolom = ["SETUJU", "BUANG", "CATATAN_CEK", "ID_STR_OUTLET", "PNAMLANG_ASAL", "PNAMLANG_AKHIR", "ALAMAT",
                 "KOTA_ASAL", "KOTA_BARU", "SEGMENT_BARU", "DISTRIBUTOR", "CUST_ID"]
        kolom = [c for c in kolom if c in d.columns]
        c1, c2 = st.columns(2)
        hanya = c1.checkbox("Tampilkan hanya baris yang perlu dicek", value=False)
        hanya_kotor = c2.checkbox("Tampilkan hanya nama yang masih kotor", value=False)
        tampil = d[kolom]
        if hanya:
            tampil = tampil[(d["CATATAN_CEK"].astype(str).str.strip() != "") | d["BUANG"]]
        if hanya_kotor:
            tampil = tampil[d["NAMA_KOTOR"].astype(str).str.strip() != ""]
        if len(tampil) == 0:
            st.info("Tidak ada baris untuk ditampilkan.")
            return
        opsi_k = _opsi_kota(tampil["KOTA_BARU"].dropna())
        if opsi_k:
            col_kota = st.column_config.SelectboxColumn(
                "KOTA_BARU (pilih dari pedoman)", options=opsi_k,
                help="Pilihan berasal dari file pedoman, sehingga penulisan seragam (mis. KOTA BANDAR LAMPUNG). "
                     "Nilai di luar pedoman ditampilkan di akhir daftar dan ditandai di CATATAN_CEK.")
        else:
            col_kota = st.column_config.TextColumn("KOTA_BARU (edit)")
        cfg = {
            "SETUJU": st.column_config.CheckboxColumn(
                "SETUJU", pinned=True, help="Centang bila baris sudah dicek dan disetujui."),
            "BUANG": st.column_config.CheckboxColumn(
                "BUANG", pinned=True, help="Centang bila tidak jadi membuat ID baru (duplikat / tidak diproses)."),
            "KOTA_BARU": col_kota,
            "PNAMLANG_AKHIR": st.column_config.TextColumn("PNAMLANG_AKHIR (edit)"),
            "SEGMENT_BARU": st.column_config.TextColumn("SEGMENT_BARU (edit)"),
            "ID_STR_OUTLET": st.column_config.TextColumn("ID_STR_OUTLET (pratinjau)"),
        }
        ed = st.data_editor(
            tampil, key=f"rv_review_{st.session_state['rv_ver']}", hide_index=True, width="stretch",
            disabled=[c for c in tampil.columns if c not in EDIT], column_config=cfg)
        baru = terapkan_edit(rv, keputusan_ke_data(rv, ed), res["max_seq"], res["prefix_map"],
                             st.session_state.get("pedoman"), st.session_state.get("known"))
        sig = lambda x: tabel_review(x, False)[kolom].fillna("").astype(str)
        if not sig(baru).equals(sig(rv)):
            st.session_state["rv"] = baru
            st.session_state["rv_ver"] += 1
            _rerun(st)

    def _kota_none(t):
        t = t.copy()
        t["KOTA_BARU"] = t["KOTA_BARU"].map(lambda v: v if _t(v) else None).astype(object)
        return t

    def _panel_sama(ix, kol_ab):
        """Perbandingan data baru vs data master untuk baris yang dipilih (DETAIL), sekaligus tempat memutuskan & mengedit.
        Edit di sini langsung mengubah tabel di atasnya, dan sebaliknya (keduanya membaca/menulis rv)."""
        r = rv.loc[ix]
        k = f"sm_{ix}_{st.session_state['rv_ver']}"
        id_m = r["ID_MASTER_SAMA"]
        lab_now = keputusan_sama_label(rv.loc[[ix]]).iloc[0]
        id_now = id_baru_tampil(pd.Series([lab_now], dtype=object), pd.Series([r["ID_STR_OUTLET"]], dtype=object)).iloc[0]
        st.markdown(f"**{_t(r['PNAMLANG_AKHIR'])}** dibandingkan dengan master **{id_m}**")
        if _t(r["CATATAN_CEK"]):
            st.caption("CATATAN_CEK: " + _t(r["CATATAN_CEK"]))
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"{LABEL_BARU}Data baru")
            st.text_input("ID_STR_OUTLET_BARU", value=id_now or "(terisi setelah keputusan ID BARU / GABUNG)", disabled=True,
                          key=k + "_id")
            nama = st.text_input("PNAMLANG_BARU (edit)", value=_t(r["PNAMLANG_AKHIR"]), key=k + "_n")
            kota_now = _t(r["KOTA_BARU"])
            opsi_k = _opsi_kota([], kota_now)
            if opsi_k:
                kota = st.selectbox("KOTA_BARU (pilih dari pedoman)", opsi_k,
                                    index=opsi_k.index(kota_now) if kota_now in opsi_k else None, key=k + "_k") or ""
            else:
                kota = st.text_input("KOTA_BARU (edit)", value=kota_now, key=k + "_k")
            seg = st.text_input("SEGMENT_BARU (edit)", value=_t(r["SEGMENT_BARU"]), key=k + "_s")
            kol_cid, kol_dis = deteksi_kolom(rv, "cust_id"), deteksi_kolom(rv, "distributor")
            info = [("PNAMLANG_ASAL", r.get("PNAMLANG_ASAL")), ("ALAMAT_BARU", r.get(kol_ab) if kol_ab else None),
                    ("CUST_ID", r.get(kol_cid) if kol_cid else None), ("DISTRIBUTOR", r.get(kol_dis) if kol_dis else None)]
            st.dataframe(pd.DataFrame({"kolom": [a for a, _ in info], "nilai": [_t(b) for _, b in info]}),
                         hide_index=True, width="stretch")
            lab = st.selectbox("KEPUTUSAN", OPSI_SAMA, index=OPSI_SAMA.index(lab_now), key=k + "_d",
                               help="ID BARU (outlet berbeda) = dibuatkan ID baru. GABUNG KE MASTER = outlet yang sama, jadi row baru "
                                    "ber-ID_STR_OUTLET master. BUANG = tidak diproses.")
        with c2:
            st.markdown(f"{LABEL_LAMA}Data master {id_m} ({int(r['JML_ROW_MASTER_SAMA'] or 0)} baris, diurutkan dari yang paling mirip)")
            st.dataframe(master_serupa(res["master_lama"], id_m, r["PNAMLANG_AKHIR"], r.get(kol_ab) if kol_ab else None),
                         hide_index=True, width="stretch")
        if (nama != _t(r["PNAMLANG_AKHIR"]) or _s(kota) != _s(r["KOTA_BARU"]) or _s(seg) != _s(r["SEGMENT_BARU"])
                or lab != lab_now):
            ed = rv.loc[[ix], ["KOTA_BARU", "SEGMENT_BARU", "PNAMLANG_AKHIR", "SETUJU", "BUANG", "GABUNG"]].copy()
            ed["KOTA_BARU"], ed["SEGMENT_BARU"], ed["PNAMLANG_AKHIR"] = kota or None, seg or None, nama
            ed["BUANG"], ed["GABUNG"], ed["SETUJU"] = lab == KEP_BUANG, lab == KEP_GABUNG, lab == KEP_BARU
            st.session_state["rv"] = terapkan_edit(rv, ed, res["max_seq"], res["prefix_map"],
                                                   st.session_state.get("pedoman"), st.session_state.get("known"))
            st.session_state["rv_ver"] += 1
            _rerun(st)

    def _tabel_sama():
        d = tabel_review(rv, True)
        if len(d) == 0:
            st.info("Tidak ada baris untuk ditampilkan.")
            return
        kol_ab = (((st.session_state.get("run_args") or {}).get("cust_cfg") or {}).get("kol_baru", {}).get("alamat")
                  or deteksi_kolom(rv, "alamat"))
        # DETAIL disimpan sebagai BARIS_EXCEL (stabil); indeks rv bergeser bila keputusan cust_id mengubah daftar calon
        cari = rv.index[rv["BARIS_EXCEL"] == st.session_state.get("sama_pilih")]
        pilih = cari[0] if len(cari) else None
        sver = st.session_state.setdefault("sama_ver", 0)
        hanya = st.checkbox("Tampilkan hanya yang belum diputuskan", value=False, key="hanya_sama")
        t0 = tabel_sama_editor(rv, kol_ab, pilih)
        if hanya:
            t0 = t0[(t0["KEPUTUSAN"] == KEP_BELUM) | t0["DETAIL"]]
        if len(t0) == 0:
            st.info("Semua baris sudah diputuskan.")
            return
        t0 = _kota_none(t0)
        st.caption(f"{LABEL_BARU}= DATA_BARU, {LABEL_LAMA}= DATA_LAMA (master). Kolom KEPUTUSAN, PNAMLANG_BARU, dan KOTA_BARU bisa "
                   "diedit langsung di tabel; ID_STR_OUTLET_BARU terisi otomatis setelah KEPUTUSAN dipilih (ID BARU atau GABUNG). "
                   "Nomor urut ID bersifat sementara sampai semua baris diputuskan. Centang DETAIL untuk membuka perbandingan "
                   "dengan data master di bawah tabel; edit di tabel dan di panel saling mengikuti.")
        opsi_k = _opsi_kota(t0["KOTA_BARU"].dropna())
        if opsi_k:
            col_kota = st.column_config.SelectboxColumn(LABEL_BARU + "KOTA_BARU (pilih)", options=opsi_k,
                                                        help="Pilihan dari file pedoman; nilai di luar pedoman ada di akhir daftar.")
        else:
            col_kota = st.column_config.TextColumn(LABEL_BARU + "KOTA_BARU (edit)")
        cfg = {
            "DETAIL": st.column_config.CheckboxColumn("DETAIL", pinned=True, help="Centang satu baris untuk membuka perbandingan di bawah."),
            "KEPUTUSAN": st.column_config.SelectboxColumn("KEPUTUSAN", options=OPSI_SAMA, required=True, pinned=True),
            "CATATAN_CEK": st.column_config.TextColumn("CATATAN_CEK"),
            "ID_STR_OUTLET_BARU": st.column_config.TextColumn("ID_STR_OUTLET_BARU", help="Terisi setelah keputusan ID BARU / GABUNG."),
            "PNAMLANG_BARU": st.column_config.TextColumn(LABEL_BARU + "PNAMLANG_BARU (edit)"),
            "ALAMAT_BARU": st.column_config.TextColumn(LABEL_BARU + "ALAMAT_BARU"),
            "KOTA_BARU": col_kota,
            "PNAMLANG_MASTER": st.column_config.TextColumn(LABEL_LAMA + "PNAMLANG_MASTER"),
            "ALAMAT_MASTER": st.column_config.TextColumn(LABEL_LAMA + "ALAMAT_MASTER"),
            "KOTA_MASTER": st.column_config.TextColumn(LABEL_LAMA + "KOTA_MASTER"),
            "ID_STR_OUTLET_MASTER": st.column_config.TextColumn(LABEL_LAMA + "ID_STR_OUTLET_MASTER"),
        }
        boleh = {"DETAIL", "KEPUTUSAN", "PNAMLANG_BARU", "KOTA_BARU"}
        ed = st.data_editor(t0, key=f"sama_{st.session_state['rv_ver']}_{sver}_{int(hanya)}", hide_index=True, width="stretch",
                            disabled=[c for c in t0.columns if c not in boleh] if not st.session_state.get("saved") else list(t0.columns),
                            column_config=cfg)
        pil = pilih_detail(ed["DETAIL"], pilih)
        baru = terapkan_edit(rv, sama_edit_ke_rv(rv, ed), res["max_seq"], res["prefix_map"],
                             st.session_state.get("pedoman"), st.session_state.get("known"))
        sig = lambda x: tabel_sama_editor(x, kol_ab).drop(columns="DETAIL").fillna("").astype(str)
        berubah = not sig(baru).equals(sig(rv))
        tick_rapi = {i for i, v in ed["DETAIL"].items() if v} == ({pil} if pil is not None else set())
        if berubah:
            st.session_state["rv"] = baru
            st.session_state["rv_ver"] += 1
        if berubah or pil != pilih or not tick_rapi:
            st.session_state["sama_pilih"] = None if pil is None else (st.session_state["rv"].at[pil, "BARIS_EXCEL"])
            st.session_state["sama_ver"] = sver + 1
            st.session_state.pop("xlsx", None)
            _rerun(st)
        if pil is None:
            st.info("Centang DETAIL pada satu baris untuk melihat perbandingan dengan data master dan mengedit di panel.")
            return
        _panel_sama(pil, kol_ab)

    if tab == "review":
        if not st.session_state.get("pedoman"):
            st.warning("Pedoman ID belum diunggah (menu 'Pedoman ID'). ID hanya bisa dibuat dari prefix master.")
        st.caption("KOTA_BARU, SEGMENT_BARU, dan PNAMLANG_AKHIR bisa diedit langsung; mengubah KOTA_BARU/SEGMENT_BARU otomatis "
                   "mengubah PNAMLANG_AKHIR dan ID. Baris yang punya CATATAN_CEK (termasuk nama masih kotor) harus diputuskan "
                   "dicentang SETUJU setelah dicek, atau dicentang BUANG bila duplikat yang tidak jadi dibuat ID baru. "
                   "Baris yang nama+kota+segmennya sama dengan outlet master ada di tab 'Sama dengan outlet master'.")
        _tabel_review()

    if tab == "sama":
        st.caption("Baris data baru yang nama+kota+segmennya sama dengan outlet di master tetapi alamatnya berbeda. Klik satu baris "
                   "untuk membandingkannya dengan data master, lalu pilih KEPUTUSAN: ID BARU (outlet berbeda), atau GABUNG KE MASTER "
                   "bila ternyata outlet yang sama (ditambahkan sebagai row baru ber-ID_STR_OUTLET master karena cust_id-nya baru).")
        _tabel_sama()

    if tab == "cust":
        ui_tab_cust(st, res, rv, _opsi_kota)

    if st.session_state.get("saved"):
        st.success("Sudah tersimpan ke master di database.")
    else:
        st.warning("Hasil ini belum disimpan ke master.")
        blok = []
        if n_noid:
            blok.append(f"{n_noid} baris belum punya ID (perbaiki kota/segmen di tab Review atau putuskan BUANG).")
        if n_perlu - n_setuju:
            blok.append(f"{n_perlu - n_setuju} baris bertanda perlu dicek belum diputuskan (SETUJU / GABUNG / BUANG).")
        for b in blok:
            st.error(b)
        ok = st.checkbox("Saya sudah memeriksa hasil di atas dan siap menyimpan ke master")
        ok_pending = True
        if len(cm):
            ok_pending = st.checkbox(f"Saya mengerti {len(cm)} baris cust_id/tail yang belum diputuskan (tab 'Keputusan cust_id') "
                                     "TIDAK ikut tersimpan")
        sudah = hash_sudah_disimpan(st.session_state.get("hash", ""))
        ok_ulang = True
        if sudah:
            ok_ulang = st.checkbox("File ini pernah disimpan sebelumnya; saya sengaja menyimpannya lagi")
        if st.button("Simpan ke master", disabled=bool(blok) or not (ok and ok_pending and ok_ulang)):
            _, now_last = master_info()
            ver_now = now_last[0] if now_last else 0
            if ver_now != st.session_state["base_ver"]:
                st.error("Master berubah sejak proses dijalankan. Jalankan ulang cek & cleansing.")
            else:
                with st.spinner("Menyimpan..."):
                    fin = selesaikan(res, rv)
                    save_master(
                        fin["master"], fin["log"], "UPDATE", st.session_state["nama_file"], st.session_state["hash"],
                        "; ".join(f"{k}: {v}" for k, v in fin["stats"].items()),
                    )
                st.session_state["saved"] = True
                st.rerun()   # muat ulang penuh: metrik 'Baris master' di atas ikut diperbarui


BAGIAN_CUST = (
    ("CUST_ID", "Cust_id sama persis dengan master",
     "Outlet yang sama dengan cust_id yang sama. Biasanya dieliminasi, atau PNAMLANG master ditimpa bila nama berubah.",
     ["TIMPA", "ELIMINASI", "BARU"]),
    ("TAIL", "Hanya tail cust_id yang sama (distributor khusus)",
     "Ujung cust_id sama dengan outlet master tetapi cust_id lengkapnya berbeda. Biasanya digabung sebagai row baru di outlet tersebut.",
     ["GABUNG_LAMA", "TIMPA_GABUNG", "ELIMINASI", "BARU"]),
)
LABEL_CUST_BELUM = "(belum diputuskan)"


def terapkan_selisih_cust(st, rv, res, selisih):
    """Terapkan selisih tabel cust. Perubahan keputusan, atau edit nama/kota baris yang bukan calon ID baru, menjalankan ulang
    pencocokan. Edit nama/kota pada calon ID baru yang sudah ada di rv cukup memperbarui rv (cepat). Selalu diakhiri _rerun(st)."""
    ss = st.session_state
    dec, ko, no, pm = terapkan_selisih_overrides(selisih, ss.get("keputusan", {}), ss.get("kota_override", {}),
                                                 ss.get("nama_override", {}), ss.get("master_nama_override", {}))
    ada_rv = set(rv["BARIS_EXCEL"])
    penuh = any(("KEPUTUSAN" in ch) or ("PNAMLANG_MASTER" in ch) or (b not in ada_rv) for b, ch in selisih.items())
    if penuh:
        ss["kota_override"], ss["nama_override"], ss["master_nama_override"] = ko, no, pm
        with st.spinner("Memproses ulang..."):
            _jalankan(st, dec, pertahankan=True)
    else:
        idx = {b: rv.index[rv["BARIS_EXCEL"] == b][0] for b in selisih}
        sub = rv.loc[list(idx.values()), ["KOTA_BARU", "SEGMENT_BARU", "PNAMLANG_AKHIR", "SETUJU", "BUANG", "GABUNG"]].copy()
        for b, ch in selisih.items():
            if "KOTA_BARU" in ch:
                sub.at[idx[b], "KOTA_BARU"] = ch["KOTA_BARU"] or None
            if "PNAMLANG_BARU" in ch:
                sub.at[idx[b], "PNAMLANG_AKHIR"] = ch["PNAMLANG_BARU"]
        ss["rv"] = terapkan_edit(rv, sub, res["max_seq"], res["prefix_map"], ss.get("pedoman"), ss.get("known"))
        ss["rv_ver"] += 1
    ss["cust_ver"] = ss.get("cust_ver", 0) + 1
    ss.pop("xlsx", None)
    _rerun(st)


def ui_tab_cust(st, res, rv, opsi_kota):
    """Tab 'Keputusan cust_id' di Update mingguan: tabel + panel perbandingan, susunan kolom sama dengan tab 'Sama dengan outlet master'."""
    cmatch = res.get("cust_match", pd.DataFrame())
    if len(cmatch) == 0:
        st.success("Tidak ada baris data baru yang cocok dengan master lewat cust_id maupun tail cust_id.")
        return
    ss = st.session_state
    saved = bool(ss.get("saved"))
    cver = ss.setdefault("cust_ver", 0)
    n_belum = int(cmatch["AKSI"].isna().sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cust_id sama persis", int((cmatch["JENIS_MATCH"] == "CUST_ID").sum()))
    c2.metric("Hanya tail sama", int((cmatch["JENIS_MATCH"] == "TAIL").sum()))
    c3.metric("Sudah diputuskan", len(cmatch) - n_belum)
    c4.metric("Belum diputuskan", n_belum)
    if saved:
        st.warning("Hasil ini sudah disimpan ke master. Jalankan ulang cek & cleansing untuk mengubah keputusan.")
    st.caption(f"{LABEL_BARU}= DATA_BARU, {LABEL_LAMA}= DATA_LAMA (master). Kolom KEPUTUSAN, PNAMLANG_BARU, KOTA_BARU, dan "
               "PNAMLANG_MASTER bisa diedit langsung di tabel; ID_STR_OUTLET_BARU terisi otomatis bila KEPUTUSAN = ID BARU (nomor urut) "
               "atau GABUNG ROW (ID outlet master). Baris yang dibiarkan '(belum diputuskan)' tidak diubah dan tidak ikut disimpan. "
               "TIMPA NAMA = PNAMLANG_AKHIR seluruh baris master ber-ID_STR sama diganti nama baru. GABUNG ROW = baris baru ditambahkan "
               "ke outlet master. ID BARU = bukan outlet yang sama. Setiap perubahan diterapkan langsung; centang DETAIL untuk membuka "
               "perbandingan dengan data master di bawah tabel (edit di tabel dan panel saling mengikuti).")
    hanya = st.checkbox("Tampilkan hanya yang belum diputuskan", value=False, key="hanya_cust")
    pilih = ss.get("cust_pilih")
    if pilih not in set(cmatch["BARIS_EXCEL"]):
        pilih = None
    boleh = {"DETAIL", "KEPUTUSAN", "PNAMLANG_BARU", "KOTA_BARU", "PNAMLANG_MASTER"}
    semua_t0, semua_ed, opsi_per_baris = [], [], {}
    for jenis, judul, ket, opsi in BAGIAN_CUST:
        opsi_label = [LABEL_CUST_BELUM] + [LABEL_AKSI[o] for o in opsi]
        t_full = tabel_cust_editor(cmatch, rv, jenis, opsi_label, pilih)
        for b in t_full.index:
            opsi_per_baris[b] = opsi_label
        t0 = t_full[(t_full["KEPUTUSAN"] == LABEL_CUST_BELUM) | t_full["DETAIL"]] if hanya else t_full
        st.markdown(f"#### {judul} ({len(t0)})")
        st.caption(ket)
        if len(t0) == 0:
            st.info("Tidak ada baris.")
            continue
        t0 = t0.copy()
        t0["KOTA_BARU"] = t0["KOTA_BARU"].map(lambda v: v if _t(v) else None).astype(object)
        opsi_k = opsi_kota(t0["KOTA_BARU"].dropna())
        if opsi_k:
            col_kota = st.column_config.SelectboxColumn(LABEL_BARU + "KOTA_BARU (pilih)", options=opsi_k,
                                                        help="Pilihan dari file pedoman; nilai di luar pedoman ada di akhir daftar.")
        else:
            col_kota = st.column_config.TextColumn(LABEL_BARU + "KOTA_BARU (edit)")
        cfg = {
            "DETAIL": st.column_config.CheckboxColumn("DETAIL", pinned=True, help="Centang satu baris untuk membuka perbandingan di bawah."),
            "KEPUTUSAN": st.column_config.SelectboxColumn("KEPUTUSAN", options=opsi_label, required=True, pinned=True),
            "CATATAN_CEK": st.column_config.TextColumn("CATATAN_CEK"),
            "ID_STR_OUTLET_BARU": st.column_config.TextColumn("ID_STR_OUTLET_BARU", help="Terisi setelah keputusan ID BARU / GABUNG ROW."),
            "PNAMLANG_BARU": st.column_config.TextColumn(LABEL_BARU + "PNAMLANG_BARU (edit)"),
            "ALAMAT_BARU": st.column_config.TextColumn(LABEL_BARU + "ALAMAT_BARU"),
            "KOTA_BARU": col_kota,
            "PNAMLANG_MASTER": st.column_config.TextColumn(
                LABEL_LAMA + "PNAMLANG_MASTER (edit)", help="Berlaku ke semua baris master ber-ID_STR_OUTLET sama."),
            "ALAMAT_MASTER": st.column_config.TextColumn(LABEL_LAMA + "ALAMAT_MASTER"),
            "KOTA_MASTER": st.column_config.TextColumn(LABEL_LAMA + "KOTA_MASTER"),
            "ID_STR_OUTLET_MASTER": st.column_config.TextColumn(LABEL_LAMA + "ID_STR_OUTLET_MASTER"),
        }
        ed = st.data_editor(
            t0, key=f"cust_{jenis}_{ss['rv_ver']}_{cver}_{int(hanya)}", hide_index=True, width="stretch",
            disabled=[c for c in t0.columns if c not in boleh] if not saved else list(t0.columns), column_config=cfg)
        semua_t0.append(t0)
        semua_ed.append(ed)

    if not semua_ed:
        return
    t0_all, ed_all = pd.concat(semua_t0), pd.concat(semua_ed)
    selisih = selisih_cust(t0_all, ed_all) if not saved else {}
    if selisih:
        terapkan_selisih_cust(st, rv, res, selisih)   # berakhir dengan _rerun(st)
    pil = pilih_detail(ed_all["DETAIL"], pilih)
    tick_rapi = {i for i, v in ed_all["DETAIL"].items() if v} == ({pil} if pil is not None else set())
    if pil != pilih or not tick_rapi:
        ss["cust_pilih"] = pil
        ss["cust_ver"] = cver + 1
        _rerun(st)
    if pil is None:
        st.info("Centang DETAIL pada satu baris untuk melihat perbandingan dengan data master dan mengedit di panel.")
        return
    panel_cust(st, res, rv, cmatch, pil, t0_all.loc[[pil]], opsi_per_baris[pil], opsi_kota, saved)


def panel_cust(st, res, rv, cmatch, b, t_row, opsi_label, opsi_kota, saved):
    """Panel perbandingan untuk satu baris cust_id: data baru (kiri, bisa diedit) vs data master ber-ID_STR yang sama (kanan)."""
    ss = st.session_state
    r = cmatch[cmatch["BARIS_EXCEL"] == b].iloc[0]
    tr = t_row.iloc[0]
    k = f"cp_{b}_{ss['rv_ver']}_{ss.get('cust_ver', 0)}"
    id_m = r["ID_STR_OUTLET_MASTER"]
    st.markdown(f"**{_t(tr['PNAMLANG_BARU'])}** dibandingkan dengan master **{id_m}**")
    if _t(r["SARAN"]):
        st.caption("CATATAN_CEK: " + _t(r["SARAN"]) + (f" | nama masih kotor: {r['NAMA_KOTOR']}" if _t(r["NAMA_KOTOR"]) else ""))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"{LABEL_BARU}Data baru")
        st.text_input("ID_STR_OUTLET_BARU", value=_t(tr["ID_STR_OUTLET_BARU"]) or "(terisi setelah keputusan ID BARU / GABUNG ROW)",
                      disabled=True, key=k + "_id")
        nama = st.text_input("PNAMLANG_BARU (edit)", value=_t(tr["PNAMLANG_BARU"]), key=k + "_n", disabled=saved)
        kota_now = _t(tr["KOTA_BARU"])
        opsi_k = opsi_kota([], kota_now)
        if opsi_k:
            kota = st.selectbox("KOTA_BARU (pilih dari pedoman)", opsi_k, index=opsi_k.index(kota_now) if kota_now in opsi_k else None,
                                key=k + "_k", disabled=saved) or ""
        else:
            kota = st.text_input("KOTA_BARU (edit)", value=kota_now, key=k + "_k", disabled=saved)
        kep = st.selectbox("KEPUTUSAN", opsi_label, index=opsi_label.index(tr["KEPUTUSAN"]), key=k + "_d", disabled=saved)
        info = [("PNAMLANG_ASAL", r.get("PNAMLANG_ASAL")), ("ALAMAT_BARU", r.get("ALAMAT_BARU")),
                ("CUST_ID_BARU", r.get("CUST_ID_BARU")), ("DISTRIBUTOR_BARU", r.get("DISTRIBUTOR_BARU")),
                ("SKOR_NAMA / SKOR_ALAMAT", f"{_t(r['SKOR_NAMA'])} / {_t(r['SKOR_ALAMAT'])}")]
        st.dataframe(pd.DataFrame({"kolom": [a for a, _ in info], "nilai": [_t(v) for _, v in info]}),
                     hide_index=True, width="stretch")
    with c2:
        st.markdown(f"{LABEL_LAMA}Data master {id_m} ({int(r['JML_ROW_ID_STR_MASTER'] or 0)} baris, diurutkan dari yang paling mirip)")
        nama_m = st.text_input("PNAMLANG_MASTER (edit, berlaku ke semua baris ber-ID_STR ini)", value=_t(tr["PNAMLANG_MASTER"]),
                               key=k + "_m", disabled=saved)
        st.dataframe(master_serupa(res["master_lama"], id_m, nama or tr["PNAMLANG_BARU"], r.get("ALAMAT_BARU")),
                     hide_index=True, width="stretch")
    if saved:
        return
    ed1 = t_row.copy()
    ed1["PNAMLANG_BARU"], ed1["KOTA_BARU"], ed1["KEPUTUSAN"], ed1["PNAMLANG_MASTER"] = nama, kota, kep, nama_m
    selisih = selisih_cust(t_row, ed1)
    if selisih:
        terapkan_selisih_cust(st, rv, res, selisih)


def page_pedoman(st):
    st.subheader("Pedoman ID_STR_OUTLET")
    st.caption("Format ID: KodeSegmen.KodeProvinsi.KodeKab/Kota.NomorUrut (urut alfabet; ID baru melanjutkan nomor tertinggi). "
               "Unggah file Pedoman Penamaan Outlet; tabel segmen, provinsi, dan kab/kota dibaca otomatis.")
    p = load_pedoman()
    if p:
        st.success(f"Pedoman tersimpan: {len(p['seg'])} segmen, {p['n_prov']} provinsi, {p['n_wil']} kab/kota.")
    else:
        st.warning("Belum ada pedoman tersimpan.")
    f = st.file_uploader("File pedoman (.xlsx)", type=["xlsx"], key="pedoman_up")
    if f:
        try:
            seg, wil = parse_pedoman(f.getvalue())
        except Exception as e:
            st.error(f"Gagal membaca pedoman: {e}")
            return
        st.write(f"Terbaca: {len(seg)} segmen, {wil['KODE_PROVINSI'].nunique()} provinsi, {len(wil)} kab/kota.")
        c1, c2 = st.columns(2)
        c1.dataframe(seg, width="stretch")
        c2.dataframe(wil, width="stretch", height=300)
        if st.button("Simpan pedoman", type="primary"):
            save_pedoman(seg, wil)
            st.success("Pedoman tersimpan.")


def page_riwayat(st):
    st.subheader("Riwayat, backup & unduh master")
    if not db_ready():
        st.info("Belum ada data.")
        return
    st.write("**Riwayat**")
    st.dataframe(load_riwayat(), width="stretch")

    st.write("**Unduh master (filter seperti Excel)**")
    st.caption("Tambahkan kondisi filter per kolom (daftar nilai, mengandung, kosong, angka, dan seterusnya), "
               "lalu siapkan file dari hasil filternya.")
    tampil_filter_export(st, rapatkan(master_cached(st)), "mst", "MASTER")

    st.write("**Unduh data yang mendapat ID baru**")
    bt = daftar_batch_update()
    if bt.empty:
        st.caption("Belum ada update yang tersimpan.")
    else:
        opsi = [None] + list(bt["id"])
        info = {r.id: f"Update #{r.id} - {r.waktu[:16]} - {r.nama_file}" for r in bt.itertuples()}
        pilih = st.selectbox(
            "Ambil dari", opsi, index=1,
            format_func=lambda b: "Semua update" if b is None else info[b] + (" (terbaru)" if b == bt["id"].iloc[0] else ""))
        df_id = load_id_baru(pilih)
        st.caption(f"{len(df_id):,} baris master dengan ID baru. Baris yang digabung ke outlet lama tidak termasuk.")
        if len(df_id):
            tampil_filter_export(st, rapatkan(df_id), f"idb{pilih}", "ID_BARU")

    st.write("**Kembalikan dari backup (rollback)**")
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "*.db")), reverse=True)
    if not files:
        st.caption("Belum ada backup.")
        return
    pilih = st.selectbox("Backup", files, format_func=os.path.basename)
    yakin = st.checkbox("Saya yakin ingin mengembalikan master ke backup ini")
    if st.button("Kembalikan", disabled=not yakin):
        restore_backup(pilih)
        st.session_state.pop("res", None)
        st.success(f"Master dikembalikan dari {os.path.basename(pilih)}.")


def main():
    import streamlit as st

    st.set_page_config(page_title="MDM Automation", layout="wide")
    st.title("Master Data Management (MDM) Automation")
    menu = st.sidebar.radio("Menu", ["Update mingguan", "Inisialisasi master", "Pedoman ID", "Riwayat & backup"])
    st.sidebar.caption(f"Database: {DB_PATH}")
    st.sidebar.caption("Salinan Drive: aktif" if DRIVE_DIR else "Salinan Drive: tidak aktif")
    {"Update mingguan": page_update, "Inisialisasi master": page_inisialisasi, "Pedoman ID": page_pedoman, "Riwayat & backup": page_riwayat}[menu](st)


if __name__ == "__main__":
    main()
