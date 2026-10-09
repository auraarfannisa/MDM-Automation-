"""
mdm_core.py
Logika murni MDM: cleansing nama/kota, pedoman ID, pencocokan (entity matching),
dan perencanaan keputusan. Tidak bergantung pada Streamlit maupun database,
sehingga mudah dites dan dipakai ulang oleh upload_initial_master.py.
"""
import io
import re
from collections import defaultdict
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

# Jika True, awalan "VIVA APOTEK / APOTEK VIVA / VIVA APT / VIVA FARMA" juga dibuang dari NAMA outlet
# (di skrip asli, pembersihan ini hanya dikenakan pada kolom kota).
HAPUS_VIVA_DARI_NAMA = False

# Batas kemiripan: nama >= AMBANG_NAMA dan alamat >= AMBANG_ALAMAT dianggap "MIRIP KUAT".
AMBANG_NAMA, AMBANG_ALAMAT = 0.80, 0.70
# Batas pencarian nama mirip (tanpa cust_id/nama persis) di kota+segmen yang sama.
AMBANG_FUZZY = 0.88


# ==============================================================================
# UTIL KECIL
# ==============================================================================
def _t(v):
    return "" if v is None or (not isinstance(v, (list, tuple, dict, set)) and pd.isna(v)) else str(v)


def _s(v):
    return _t(v).strip().upper()


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
    # ibukota kabupaten -> nama kabupaten
    "AMUNTAI": "KAB. HULU SUNGAI UTARA", "LIMBOTO": "KAB. GORONTALO",
    "LUBUKBASUNG": "KAB. AGAM", "LUBUK BASUNG": "KAB. AGAM",
    "POLEWALI": "KAB. POLEWALI MANDAR",
    "PLEIHARI": "KAB. TANAH LAUT", "PELAIHARI": "KAB. TANAH LAUT",
    "RANGKASBITUNG": "KAB. LEBAK", "TAHUNA": "KAB. KEPULAUAN SANGIHE", "TAKENGON": "KAB. ACEH TENGAH",
    "TANGGERONG": "KAB. KUTAI KARTANEGARA", "TENGGARONG": "KAB. KUTAI KARTANEGARA",
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
    tanpa_awalan = re.sub(r"^(KABUPATEN|KAB|KOTA)\.?\s+", "", s_upper)  # 'KAB. AMUNTAI' / 'KOTA SOLO' juga dikenali
    if tanpa_awalan != s_upper:
        if tanpa_awalan in KAMUS_17_DAERAH:
            return KAMUS_17_DAERAH[tanpa_awalan]
        if re.sub(r"[^A-Z0-9]", "", tanpa_awalan) in KAMUS_17_DAERAH:
            return KAMUS_17_DAERAH[re.sub(r"[^A-Z0-9]", "", tanpa_awalan)]
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
    if HAPUS_VIVA_DARI_NAMA:
        name = re.sub(r"^(VIVA\s+(APOTEK|APT\.?|FARMA)\b|APOTEK\s+VIVA\b)[\s\-\:\.]*", "", name)

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


# ==============================================================================
# HELPER DATAFRAME
# ==============================================================================
def pick(df, *cols):
    """Ambil nilai non-kosong pertama dari beberapa kolom kandidat (yang ada saja)."""
    out = pd.Series([np.nan] * len(df), index=df.index, dtype=object)
    for c in cols:
        if c in df.columns:
            s = df[c].replace(r"^\s*$", np.nan, regex=True)
            out = out.where(out.notna(), s)
    return out


def clean_dataframe_baru(df, pedoman=None):
    """Cleansing kota + nama + segmen pada data calon outlet baru (PNAMLANG_AKHIR = NAMA (KOTA), SUFFIX).
    Dengan `pedoman`, KOTA_BARU dinormalkan ke nama resmi pedoman (tambah KAB./KOTA, perbaiki spasi)."""
    df = df.copy()
    df["KOTA_ASAL"] = pick(df, "KOTA", "KOTA_CLEAN")
    df["KOTA_BARU"] = pick(df, "KOTA_CLEAN", "KOTA").apply(clean_viva_dan_daerah).apply(lambda v: kanonik_kota(v, pedoman))
    df["PNAMLANG_ASAL"] = pick(df, "PNAMLANG", "PNAMLANG_CLEAN")
    nama = pick(df, "PNAMLANG_CLEAN", "PNAMLANG")
    seg = pick(df, "SEGMENT_CLEAN", "SEGMENT")
    parts = [clean_name_parts(n, s) for n, s in zip(nama, seg)]
    df["_NAMA_DASAR"] = [p[0] for p in parts]
    df["SEGMENT_BARU"] = [p[1] for p in parts]
    df["_SUFIKS"] = [p[2] for p in parts]
    df["PNAMLANG_AKHIR"] = [bangun_nama(p[0], k, p[1], p[2]) for p, k in zip(parts, df["KOTA_BARU"])]
    return df


def siapkan_master_std(df):
    """Pastikan master punya KOTA_BARU, SEGMENT_BARU, PNAMLANG_AKHIR (dibuat dari kolom mentah bila belum ada)."""
    d, info = df.copy(), []
    if "KOTA_BARU" not in d.columns:
        d["KOTA_BARU"] = pick(d, "KOTA_CLEAN", "KOTA").apply(clean_viva_dan_daerah)
        info.append("Kolom KOTA_BARU dibuat dari KOTA_CLEAN/KOTA.")
    if "SEGMENT_BARU" not in d.columns:
        d["SEGMENT_BARU"] = pick(d, "SEGMENT_CLEAN", "SEGMENT")
        info.append("Kolom SEGMENT_BARU dibuat dari SEGMENT_CLEAN/SEGMENT.")
    if "PNAMLANG_AKHIR" not in d.columns:
        nm = pick(d, "PNAMLANG_CLEAN", "PNAMLANG")
        d["PNAMLANG_AKHIR"] = [clean_name_and_segment(n, s, k)[0]
                               for n, s, k in zip(nm, d["SEGMENT_BARU"], d["KOTA_BARU"])]
        info.append("Kolom PNAMLANG_AKHIR dibuat dari PNAMLANG_CLEAN/PNAMLANG.")
    return d, info


# ==============================================================================
# MODUL 3: PEDOMAN ID_STR_OUTLET  (Segment.Provinsi.Kab/Kota.Urutan)
# ==============================================================================
def _norm_kab(v):
    """Samakan penulisan: KABUPATEN/KAB/KAB. -> 'KAB. ', 'KOTA ADM(INISTRASI)' -> 'KOTA '."""
    if v is None or pd.isna(v):
        return ""
    s = re.sub(r"\s+", " ", str(v).strip().upper())
    s = re.sub(r"^KOTA (ADMINISTRASI|ADM\.?) ", "KOTA ", s)
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
        return c if (j == "" or c.startswith(j)) else s
    for c in kand:
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


def catatan_pedoman(kota, seg, pedoman):
    """Daftar catatan jika kota/segmen tidak bisa dipetakan ke kode di pedoman."""
    if not pedoman:
        return ["Pedoman ID belum diunggah (menu Pedoman ID)"]
    n, s, k = [], _s(seg), _norm_kab(kota)
    if not s:
        n.append("Segmen kosong")
    elif s not in pedoman["seg"]:
        n.append(f"Segmen '{s}' tidak ada di pedoman")
    if not k:
        n.append("Kota kosong")
    elif k not in pedoman["wil"]:
        kand = pedoman.get("by_base", {}).get(kunci_wilayah(k)[1], [])
        if len(kand) > 1:
            n.append(f"Kota '{k}' ada sebagai {' dan '.join(kand)} di pedoman; pilih salah satu")
        else:
            n.append(f"Kota '{k}' tidak ada di pedoman")
    elif k in pedoman["amb"]:
        n.append("Nama kota ganda di pedoman (pastikan provinsinya)")
    return n


def peta_id(ids, kota, seg):
    """Nomor urut tertinggi per prefix, dan prefix master per (kota, segmen). Semua input: list/Series sepanjang master."""
    d = pd.DataFrame({"id": pd.Series(list(ids), dtype=object).map(_t).str.strip(),
                      "kota": [_t(k) for k in kota], "seg": [_s(s) for s in seg]})
    d = d[d["id"] != ""]
    p = d["id"].str.rsplit(".", n=1, expand=True)
    if p.shape[1] != 2:
        return {}, {}
    ok = p[1].str.isdigit().fillna(False)
    d, p = d[ok], p[ok]
    if d.empty:
        return {}, {}
    g = pd.DataFrame({"p": p[0], "s": p[1].astype(int)}).groupby("p")["s"].max()
    max_seq = {k: int(v) for k, v in g.items()}
    d = d.assign(prefix=p[0]).drop_duplicates(["kota", "seg"])
    prefix_map = {(k, s): x for k, s, x in zip(d["kota"], d["seg"], d["prefix"])}
    return max_seq, prefix_map


def beri_id_baru(d, max_seq, prefix_map, pedoman):
    """Beri ID_STR_OUTLET baru (Segment.Provinsi.KabKota.Urutan) untuk baris-baris d, urut alfabet kota, segmen, nama.
    d wajib punya kolom KOTA_BARU, SEGMENT_BARU, PNAMLANG_AKHIR. Kembalikan (Series id, Series catatan)."""
    ids = pd.Series("", index=d.index, dtype=object)
    notes = pd.Series("", index=d.index, dtype=object)
    seg_map = pedoman["seg"] if pedoman else {}
    wil_map = pedoman["wil"] if pedoman else {}
    seq = dict(max_seq)
    kt = {i: _norm_kab(d.at[i, "KOTA_BARU"]) for i in d.index}
    sg = {i: _s(d.at[i, "SEGMENT_BARU"]) for i in d.index}
    nm = {i: _s(d.at[i, "PNAMLANG_AKHIR"]) for i in d.index}
    for i in sorted(d.index, key=lambda i: (kt[i] == "", kt[i], sg[i], nm[i])):
        sc, wc = seg_map.get(sg[i]), wil_map.get(kt[i])
        mp = prefix_map.get((_t(d.at[i, "KOTA_BARU"]), sg[i]))
        prefix, cat = None, []
        if sc is not None and wc is not None:
            prefix = f"{sc}.{wc[0]}.{wc[1]}"
            if mp and mp != prefix:
                cat.append(f"Prefix pedoman ({prefix}) berbeda dari master ({mp})")
        elif mp:
            prefix = mp
            cat.append("Prefix diambil dari master (kode tidak lengkap di pedoman)")
        if prefix is None:
            cat.append("ID belum bisa dibuat: " + ("; ".join(catatan_pedoman(d.at[i, "KOTA_BARU"], d.at[i, "SEGMENT_BARU"], pedoman))
                                                   or "kode tidak ditemukan"))
        else:
            seq[prefix] = seq.get(prefix, 0) + 1
            ids[i] = f"{prefix}.{seq[prefix]}"
        notes[i] = "; ".join(cat)
    return ids, notes


# ==============================================================================
# MODUL 4: PENCOCOKAN (ENTITY MATCHING)
# ==============================================================================
KANDIDAT_KOLOM = {
    "cust_id": ["CUSTID", "CUSTOMERID", "IDCUST", "IDCUSTOMER", "KODECUSTOMER", "KODECUST"],
    "alamat": ["ALAMAT", "ALAMATCLEAN", "ALAMAT1", "ADDRESS", "ALAMATLENGKAP"],
    "distributor": ["DISTRIBUTOR", "NAMADISTRIBUTOR", "DISTRIBUTORNAME", "KODEDISTRIBUTOR", "DISTRIB", "DIST"],
}
STOP_NAMA = {"APOTEK", "APOTIK", "APT", "KLINIK", "RS", "RSU", "RUMAH", "SAKIT", "TOKO", "PT", "CV", "UD"}
STOP_ALAMAT = {"JL", "JALAN", "NO", "NOMOR", "RT", "RW", "KEL", "KELURAHAN", "KEC", "KECAMATAN", "KAB", "KOTA"}
KOLOM_STD = ["ID_STR_OUTLET", "CUST_ID", "DISTRIBUTOR", "ALAMAT", "PNAMLANG_AKHIR", "KOTA_BARU", "SEGMENT_BARU"]


def deteksi_kolom(df_atau_kolom, jenis):
    """Cari nama kolom untuk 'cust_id' / 'alamat' / 'distributor' (abaikan huruf besar/kecil, spasi, tanda baca)."""
    kolom = list(getattr(df_atau_kolom, "columns", df_atau_kolom))
    peta = {re.sub(r"[^A-Z0-9]", "", str(c).upper()): c for c in kolom}
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


def _gabung_token(v, stop):
    return " ".join(t for t in re.sub(r"[^A-Z0-9 ]", " ", _t(v).upper()).split() if t not in stop)


def _nkey(v):
    t = _tanpa_kota(v)
    return "" if t is None or pd.isna(t) else re.sub(r"[^A-Z0-9]", "", str(t).upper())


class MasterIndex:
    """Indeks dalam memori atas master (dibangun sekali per versi master). Input: DataFrame dengan kolom KOLOM_STD."""

    def __init__(self, master, khusus=(), min_tail=3):
        m = master.reset_index(drop=True)
        for c in KOLOM_STD:
            if c not in m.columns:
                m[c] = None
        self.n = len(m)
        self.khusus = [str(t).strip().upper() for t in khusus if str(t).strip()]
        self.min_tail = min_tail
        self.id_str = [_t(v).strip() for v in m["ID_STR_OUTLET"]]
        self.cust_raw = m["CUST_ID"].tolist()
        self.cust = [_norm_id(v) for v in self.cust_raw]
        self.dist = [_norm_dist(v) for v in m["DISTRIBUTOR"]]
        self.nama = m["PNAMLANG_AKHIR"].tolist()
        self.alamat = m["ALAMAT"].tolist()
        self.kota = m["KOTA_BARU"].tolist()
        self.seg = [_s(v) for v in m["SEGMENT_BARU"]]
        self.nama_tk = [_tanpa_kota(v) for v in self.nama]
        self.nama_join = [_gabung_token(v, STOP_NAMA) for v in self.nama_tk]

        self.by_cust, self.by_cust_any = defaultdict(list), defaultdict(list)
        self.by_tail, self.by_id = defaultdict(list), defaultdict(list)
        self.by_nks, self.by_group = defaultdict(list), defaultdict(list)
        kk = {k: kunci_wilayah(k)[1] for k in set(_t(k) for k in self.kota)}
        for i in range(self.n):
            c, d = self.cust[i], self.dist[i]
            if c is not None:
                self.by_cust[(d, c)].append(i)
                self.by_cust_any[c].append(i)
                if self.khusus and "-" in c and _is_khusus(d, self.khusus):
                    t = c.rsplit("-", 1)[1].strip()
                    if len(t) >= self.min_tail:
                        self.by_tail[(d, t)].append(i)
                        self.by_tail[("", t)].append(i)
            if self.id_str[i]:
                self.by_id[self.id_str[i]].append(i)
            kkey = kk[_t(self.kota[i])]
            self.by_nks[_nkey(self.nama[i]) + "|" + kkey + "|" + self.seg[i]].append(i)
            self.by_group[(kkey, self.seg[i])].append(i)
        self.max_seq, self.prefix_map = peta_id(self.id_str, self.kota, self.seg)


def _kandidat_fuzzy(nb_join, grp, idx, ambang):
    """Saring cepat kandidat nama mirip memakai batas atas rasio (quick_ratio), baru dihitung penuh oleh sim()."""
    sm = SequenceMatcher(None, autojunk=False)
    sm.set_seq2(nb_join)
    out = []
    for mi in grp:
        sm.set_seq1(idx.nama_join[mi])
        if sm.real_quick_ratio() >= ambang and sm.quick_ratio() >= ambang:
            out.append(mi)
    return out


def cocokkan(df_new, idx, kol_baru, per_distributor=True, ambang_nama=AMBANG_NAMA,
             ambang_alamat=AMBANG_ALAMAT, ambang_fuzzy=AMBANG_FUZZY):
    """Cocokkan tiap baris data baru (sudah di-cleansing) ke master.
    Urutan pencarian kandidat: (1) cust_id sama persis, (2) tail cust_id (distributor khusus), (3) nama+kota+segmen sama,
    (4) nama mirip di kota+segmen yang sama. Hasil: DataFrame sejajar df_new dengan STATUS
    BARU / MIRIP KUAT / PERLU CEK dan data master pembanding."""
    kc, ka, kd = kol_baru.get("cust_id"), kol_baru.get("alamat"), kol_baru.get("distributor")
    skop = bool(per_distributor and kd and any(idx.dist))
    kolom = ["STATUS", "JENIS_MATCH", "CATATAN", "SARAN_MASTER_CUST_ID", "ID_STR_OUTLET_MASTER", "PNAMLANG_MASTER",
             "ALAMAT_MASTER", "KOTA_MASTER", "SKOR_NAMA", "SKOR_ALAMAT", "CUST_ID_DI_OUTLET", "JML_KANDIDAT"]
    rows = {}
    for ix, row in df_new.iterrows():
        cust = _norm_id(row[kc]) if kc else None
        d_raw = row[kd] if kd else None
        dn = _norm_dist(d_raw)
        alamat_b = row[ka] if ka else None
        nama_b = row["PNAMLANG_AKHIR"]
        kkey = kunci_wilayah(row["KOTA_BARU"])[1]
        seg = _s(row["SEGMENT_BARU"])
        cand, via = [], None
        if cust:
            cand = idx.by_cust.get((dn, cust), []) if skop else idx.by_cust_any.get(cust, [])
            via = "CUST_ID"
            if not cand and idx.khusus and kd and "-" in cust and _is_khusus(d_raw, idx.khusus):
                t = cust.rsplit("-", 1)[1].strip()
                if len(t) >= idx.min_tail:
                    cand = idx.by_tail.get((dn if skop else "", t), [])
                    via = "TAIL CUST_ID"
        if not cand and _t(nama_b):
            cand = idx.by_nks.get(_nkey(nama_b) + "|" + kkey + "|" + seg, [])
            via = "NAMA+KOTA+SEGMEN"
        if not cand and _t(nama_b):
            grp = idx.by_group.get((kkey, seg))
            if grp:
                nb = _tanpa_kota(nama_b)
                pra = _kandidat_fuzzy(_gabung_token(nb, STOP_NAMA), grp, idx, ambang_fuzzy)
                cand = [mi for mi in pra
                        if (v := sim(nb, idx.nama_tk[mi], STOP_NAMA)) is not None and v >= ambang_fuzzy]
                via = "NAMA MIRIP"
        if not cand:
            rows[ix] = {"STATUS": "BARU"}
            continue
        best = None
        for mi in cand[:60]:
            sn = sim(_tanpa_kota(nama_b), idx.nama_tk[mi], STOP_NAMA)
            sa = sim(alamat_b, idx.alamat[mi], STOP_ALAMAT) if ka else None
            ok_n = sn is not None and sn >= ambang_nama
            ok_a = sa is None or sa >= ambang_alamat
            skor = (ok_n and ok_a, (sn or 0) + (sa or 0))
            if best is None or skor > best[0]:
                best = (skor, mi, sn, sa, ok_n, ok_a)
        _, mi, sn, sa, ok_n, ok_a = best
        id_m = idx.id_str[mi]
        lain = []
        for x in idx.by_id.get(id_m, [mi]):
            v = idx.cust[x]
            if v and v not in lain:
                lain.append(v)
        if ok_n and ok_a:
            status, cat = "MIRIP KUAT", f"[{via}] Mirip: kemungkinan outlet sama"
        else:
            sebab = ("NAMA & ALAMAT BERUBAH" if (not ok_n and not ok_a) else "NAMA BERUBAH" if not ok_n else "ALAMAT BERUBAH")
            status, cat = "PERLU CEK", f"[{via}] {sebab}: periksa, bisa outlet berbeda"
        rows[ix] = {
            "STATUS": status, "JENIS_MATCH": via, "CATATAN": cat,
            "SARAN_MASTER_CUST_ID": idx.cust[mi] or id_m, "ID_STR_OUTLET_MASTER": id_m,
            "PNAMLANG_MASTER": idx.nama[mi], "ALAMAT_MASTER": idx.alamat[mi], "KOTA_MASTER": idx.kota[mi],
            "SKOR_NAMA": None if sn is None else round(sn, 2), "SKOR_ALAMAT": None if sa is None else round(sa, 2),
            "CUST_ID_DI_OUTLET": ", ".join(lain[:8]) + (" ..." if len(lain) > 8 else ""), "JML_KANDIDAT": len(cand),
        }
    return pd.DataFrame.from_dict(rows, orient="index").reindex(index=df_new.index, columns=kolom)


# ==============================================================================
# MODUL 5: TABEL REVIEW, EDIT, DAN RENCANA KEPUTUSAN
# ==============================================================================
STATUS_URUT = {"PERLU CEK": 0, "MIRIP KUAT": 1, "BARU": 2}
KOLOM_REVIEW = ["KEPUTUSAN", "STATUS", "CATATAN_CEK", "BARIS_EXCEL", "PNAMLANG_ASAL", "PNAMLANG_AKHIR", "ALAMAT_BARU",
                "KOTA_BARU", "SEGMENT_BARU", "CUST_ID_BARU", "DISTRIBUTOR_BARU", "SARAN_MASTER_CUST_ID",
                "PNAMLANG_MASTER", "ALAMAT_MASTER", "KOTA_MASTER", "ID_STR_OUTLET_MASTER", "SKOR_NAMA", "SKOR_ALAMAT"]


def susun_review(base, hasil, kol_baru, pedoman):
    """Tabel review (hanya kolom review; data mentah tetap di `base`). KEPUTUSAN awal: '0' untuk status BARU, kosong untuk
    baris yang punya kandidat di master (harus diputuskan user)."""
    kc, ka, kd = kol_baru.get("cust_id"), kol_baru.get("alamat"), kol_baru.get("distributor")
    h = hasil.reindex(base.index)
    r = pd.DataFrame(index=base.index)
    r["KEPUTUSAN"] = np.where(h["STATUS"] == "BARU", "0", "")
    r["STATUS"] = h["STATUS"]
    notes = []
    for ix in base.index:
        n = []
        if _t(h.at[ix, "CATATAN"]):
            n.append(h.at[ix, "CATATAN"])
        kotor = cek_nama_kotor(base.at[ix, "PNAMLANG_AKHIR"])
        if kotor:
            n.append("Nama masih kotor: " + "; ".join(kotor))
        if h.at[ix, "STATUS"] == "BARU":   # catatan pedoman hanya relevan bila akan dibuat ID baru
            n.extend(catatan_pedoman(base.at[ix, "KOTA_BARU"], base.at[ix, "SEGMENT_BARU"], pedoman))
        notes.append("; ".join(n))
    r["CATATAN_CEK"] = notes
    r["BARIS_EXCEL"] = base["BARIS_EXCEL"]
    r["PNAMLANG_ASAL"] = base["PNAMLANG_ASAL"]
    r["PNAMLANG_AKHIR"] = base["PNAMLANG_AKHIR"]
    r["ALAMAT_BARU"] = base[ka] if ka else None
    r["KOTA_BARU"] = base["KOTA_BARU"]
    r["SEGMENT_BARU"] = base["SEGMENT_BARU"]
    r["CUST_ID_BARU"] = base[kc] if kc else None
    r["DISTRIBUTOR_BARU"] = base[kd] if kd else None
    for c in ("SARAN_MASTER_CUST_ID", "PNAMLANG_MASTER", "ALAMAT_MASTER", "KOTA_MASTER", "ID_STR_OUTLET_MASTER",
              "SKOR_NAMA", "SKOR_ALAMAT"):
        r[c] = h[c]
    r["SKOR_NAMA"] = pd.to_numeric(r["SKOR_NAMA"], errors="coerce")
    r["SKOR_ALAMAT"] = pd.to_numeric(r["SKOR_ALAMAT"], errors="coerce")
    r["_NAMA_DASAR"] = base["_NAMA_DASAR"]
    r["_SUFIKS"] = base["_SUFIKS"]
    for c in r.columns:
        if c not in ("SKOR_NAMA", "SKOR_ALAMAT"):
            r[c] = r[c].astype(object)
    urut = r["STATUS"].map(STATUS_URUT).fillna(3).values
    return r.iloc[np.argsort(urut, kind="stable")]


def terapkan_edit(rv, ed):
    """Gabungkan hasil edit user (KEPUTUSAN, PNAMLANG_AKHIR, KOTA_BARU, SEGMENT_BARU) ke tabel review.
    Bila kota/segmen diubah dan nama tidak diedit langsung, nama dibangun ulang mengikuti kota/segmen."""
    d = rv.copy()
    e = ed.reindex(d.index)
    d["KEPUTUSAN"] = e["KEPUTUSAN"].map(_t).str.strip()
    for i in d.index:
        nama_e = _t(e.at[i, "PNAMLANG_AKHIR"]).strip()
        kota_e = _t(e.at[i, "KOTA_BARU"]).strip()
        seg_e = _t(e.at[i, "SEGMENT_BARU"]).strip()
        if nama_e != _t(rv.at[i, "PNAMLANG_AKHIR"]).strip():
            d.at[i, "PNAMLANG_AKHIR"] = nama_e
        elif _s(kota_e) != _s(rv.at[i, "KOTA_BARU"]) or _s(seg_e) != _s(rv.at[i, "SEGMENT_BARU"]):
            d.at[i, "PNAMLANG_AKHIR"] = bangun_nama(rv.at[i, "_NAMA_DASAR"], kota_e or None, seg_e, rv.at[i, "_SUFIKS"])
        d.at[i, "KOTA_BARU"] = kota_e or None
        d.at[i, "SEGMENT_BARU"] = seg_e or None
    return d


def parse_keputusan(v):
    """('BELUM'|'BARU'|'SKIP'|'MERGE', token). '0' = ID baru; 'SKIP' = lewati; lainnya = Master CUST_ID untuk MERGE."""
    t = _t(v).strip()
    u = t.upper()
    if u == "":
        return "BELUM", None
    if re.fullmatch(r"0+(\.0+)?", u):
        return "BARU", None
    if u in ("SKIP", "BUANG", "ELIMINASI"):
        return "SKIP", None
    return "MERGE", t


def resolve_master(idx, token):
    """Cari baris master dari token: CUST_ID master, atau ID_STR_OUTLET. Kembalikan (indeks, pesan_error)."""
    c = _norm_id(token)
    if c is None:
        return None, "Master CUST_ID kosong"
    cand = idx.by_cust_any.get(c, [])
    if cand:
        ids = sorted({idx.id_str[i] for i in cand})
        if len(ids) > 1:
            return None, f"CUST_ID {token} dipakai beberapa outlet ({', '.join(ids[:5])}); isi ID_STR_OUTLET master langsung"
        return cand[0], None
    cand = idx.by_id.get(str(token).strip(), [])
    if cand:
        return cand[0], None
    return None, f"'{token}' tidak ditemukan di master (CUST_ID maupun ID_STR_OUTLET)"


def susun_rencana(d, idx, pedoman):
    """Rencana eksekusi dari keputusan user. AKSI: ID BARU | GABUNG ROW | SUDAH ADA | SKIP | BELUM | ERROR.
    ID_STR_OUTLET pada ID BARU hanya pratinjau (nomor final ditetapkan di database saat simpan)."""
    out = pd.DataFrame(index=d.index, columns=["AKSI", "ID_STR_OUTLET", "NAMA_FINAL", "KOTA_FINAL", "SEGMENT_FINAL",
                                               "ERROR", "PERINGATAN"], dtype=object)
    out[["ID_STR_OUTLET", "ERROR", "PERINGATAN"]] = ""
    baru = []
    for ix in d.index:
        jenis, token = parse_keputusan(d.at[ix, "KEPUTUSAN"])
        out.at[ix, "NAMA_FINAL"] = d.at[ix, "PNAMLANG_AKHIR"]
        out.at[ix, "KOTA_FINAL"] = d.at[ix, "KOTA_BARU"]
        out.at[ix, "SEGMENT_FINAL"] = d.at[ix, "SEGMENT_BARU"]
        if jenis == "BELUM":
            out.at[ix, "AKSI"] = "BELUM"
        elif jenis == "SKIP":
            out.at[ix, "AKSI"] = "SKIP"
        elif jenis == "BARU":
            out.at[ix, "AKSI"] = "ID BARU"
            baru.append(ix)
            if not _t(d.at[ix, "PNAMLANG_AKHIR"]).strip():
                out.at[ix, "ERROR"] = "Nama kosong"
        else:
            mi, err = resolve_master(idx, token)
            if err:
                out.at[ix, "AKSI"], out.at[ix, "ERROR"] = "ERROR", err
                continue
            id_m = idx.id_str[mi]
            cust, dist = _norm_id(d.at[ix, "CUST_ID_BARU"]), _norm_dist(d.at[ix, "DISTRIBUTOR_BARU"])
            sudah = any(idx.cust[j] == cust and (not dist or not idx.dist[j] or idx.dist[j] == dist)
                        for j in idx.by_id.get(id_m, [mi])) if cust else False
            out.at[ix, "AKSI"] = "SUDAH ADA" if sudah else "GABUNG ROW"
            out.at[ix, "ID_STR_OUTLET"] = id_m
            out.at[ix, "NAMA_FINAL"], out.at[ix, "KOTA_FINAL"], out.at[ix, "SEGMENT_FINAL"] = idx.nama[mi], idx.kota[mi], idx.seg[mi]
            if sudah:
                out.at[ix, "PERINGATAN"] = "CUST_ID ini sudah ada di outlet master: baris dilewati (tidak dobel)"
    if baru:
        ids, notes = beri_id_baru(d.loc[baru], idx.max_seq, idx.prefix_map, pedoman)
        for ix in baru:
            out.at[ix, "ID_STR_OUTLET"] = ids[ix]
            if not ids[ix] and not out.at[ix, "ERROR"]:
                out.at[ix, "ERROR"] = notes[ix]
            elif notes[ix]:
                out.at[ix, "PERINGATAN"] = notes[ix]
        kunci = d.loc[baru, "PNAMLANG_AKHIR"].map(_s) + "|" + d.loc[baru, "KOTA_BARU"].map(_s) + "|" + d.loc[baru, "SEGMENT_BARU"].map(_s)
        kembar = kunci[kunci.duplicated(keep=False) & (kunci.str.split("|").str[0] != "")].index
        for ix in kembar:
            out.at[ix, "PERINGATAN"] = (out.at[ix, "PERINGATAN"] + "; " if out.at[ix, "PERINGATAN"] else "") + \
                "Nama+kota+segmen kembar dengan baris ID BARU lain di file ini"
    return out


def siapkan_insert(base, final, rencana, kol_baru, colmap):
    """Susun DataFrame semua baris (termasuk yang dilewati) untuk disimpan: data mentah + hasil cleansing + keputusan.
    Kolom cust_id/alamat/distributor data baru disalin ke nama kolom master bila namanya berbeda."""
    ins = base.loc[final.index].copy()
    for c in ("PNAMLANG_AKHIR", "KOTA_BARU", "SEGMENT_BARU"):
        ins[c] = rencana["NAMA_FINAL" if c == "PNAMLANG_AKHIR" else "KOTA_FINAL" if c == "KOTA_BARU" else "SEGMENT_FINAL"]
    ins["ID_STR_OUTLET"] = rencana["ID_STR_OUTLET"]
    ins["_AKSI"] = rencana["AKSI"]
    for jenis in ("cust_id", "alamat", "distributor"):
        kb, km = kol_baru.get(jenis), colmap.get(jenis)
        if kb and km and kb != km:
            ins[km] = ins[kb]
    return ins


def validasi_rencana(rencana):
    """Daftar pesan yang menghalangi penyimpanan."""
    msg = []
    n_belum = int((rencana["AKSI"] == "BELUM").sum())
    if n_belum:
        msg.append(f"{n_belum} baris belum diputuskan (isi 0 = ID baru, Master CUST_ID = gabung, atau SKIP).")
    err = rencana[rencana["ERROR"].astype(str).str.strip() != ""]
    if len(err):
        msg.append(f"{len(err)} baris bermasalah (lihat kolom ERROR di pratinjau).")
    if int(rencana["AKSI"].isin(["ID BARU", "GABUNG ROW"]).sum()) == 0 and not msg:
        msg.append("Tidak ada baris yang akan disimpan (semua SKIP / SUDAH ADA).")
    return msg
