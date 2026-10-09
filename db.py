"""
db.py
Akses database Neon PostgreSQL lewat SQLAlchemy + psycopg2.
Kredensial dibaca dari st.secrets["DATABASE_URL"] (Streamlit Cloud) atau variabel lingkungan DATABASE_URL (skrip lokal).
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy import types as T

import mdm_core as core

TABLE_MASTER = "master_outlet"
LOCK_KEY = 8600086  # kunci advisory lock agar dua penyimpanan bersamaan tidak membuat nomor urut ID kembar


def now_wib():
    return datetime.now(ZoneInfo("Asia/Jakarta"))


# ------------------------------------------------------------------------------
# KONEKSI
# ------------------------------------------------------------------------------
def get_database_url():
    url = None
    try:
        import streamlit as st
        url = st.secrets["DATABASE_URL"]
    except Exception:
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL tidak ditemukan. Isi di Streamlit Cloud Secrets (atau .streamlit/secrets.toml / "
                           "variabel lingkungan DATABASE_URL untuk pemakaian lokal).")
    url = str(url).strip()
    # Paksa driver psycopg2 (SQLAlchemy versi baru bisa memilih psycopg v3 untuk 'postgresql://').
    for awal in ("postgres://", "postgresql://"):
        if url.startswith(awal):
            url = "postgresql+psycopg2://" + url[len(awal):]
            break
    return url


def make_engine(url=None):
    # pool_pre_ping + pool_recycle: Neon menidurkan compute saat idle, koneksi lama harus dites ulang.
    return create_engine(url or get_database_url(), pool_pre_ping=True, pool_recycle=300, pool_size=3, max_overflow=2)


def ping(engine):
    with engine.connect() as c:
        c.execute(text("SELECT 1"))


def ensure_meta_tables(engine):
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE IF NOT EXISTS riwayat_batch (id SERIAL PRIMARY KEY, waktu TIMESTAMPTZ DEFAULT now(), "
            "batch_week TEXT, nama_file TEXT, hash_file TEXT, ringkasan TEXT)"))
        c.execute(text(
            "CREATE TABLE IF NOT EXISTS log_perubahan (id SERIAL PRIMARY KEY, batch_id INTEGER, jenis TEXT, "
            "id_str_outlet TEXT, detail TEXT)"))


def ensure_master_columns(conn):
    conn.execute(text(f"ALTER TABLE {TABLE_MASTER} ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()"))
    conn.execute(text(f"ALTER TABLE {TABLE_MASTER} ADD COLUMN IF NOT EXISTS batch_week TEXT"))


def create_indexes(engine, colmap):
    with engine.begin() as c:
        c.execute(text(f'CREATE INDEX IF NOT EXISTS idx_master_id ON {TABLE_MASTER} ("ID_STR_OUTLET")'))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS idx_master_batch ON {TABLE_MASTER} (batch_week)"))
        if colmap.get("cust_id"):
            col = colmap["cust_id"].replace('"', '""')
            c.execute(text(f'CREATE INDEX IF NOT EXISTS idx_master_cust ON {TABLE_MASTER} ("{col}")'))


# ------------------------------------------------------------------------------
# MASTER
# ------------------------------------------------------------------------------
def master_exists(engine):
    return inspect(engine).has_table(TABLE_MASTER)


def table_columns(engine, table=TABLE_MASTER):
    return [c["name"] for c in inspect(engine).get_columns(table)]


def master_colmap(engine):
    cols = table_columns(engine)
    return {k: core.deteksi_kolom(cols, k) for k in ("cust_id", "alamat", "distributor")}


def master_version(engine):
    """(jumlah baris, id batch terakhir). Berubah setiap kali master berubah -> kunci cache."""
    with engine.connect() as c:
        n = c.execute(text(f"SELECT COUNT(*) FROM {TABLE_MASTER}")).scalar()
        last = c.execute(text("SELECT COALESCE(MAX(id), 0) FROM riwayat_batch")).scalar()
    return int(n), int(last)


def load_master_slim(engine, colmap):
    """Hanya kolom yang dipakai pencocokan (hemat memori), dengan nama standar KOLOM_STD."""
    cols = set(table_columns(engine))
    q = lambda c: '"' + c.replace('"', '""') + '"'
    sumber = {"ID_STR_OUTLET": "ID_STR_OUTLET", "PNAMLANG_AKHIR": "PNAMLANG_AKHIR", "KOTA_BARU": "KOTA_BARU",
              "SEGMENT_BARU": "SEGMENT_BARU", "CUST_ID": colmap.get("cust_id"), "ALAMAT": colmap.get("alamat"),
              "DISTRIBUTOR": colmap.get("distributor")}
    sel = []
    for std in core.KOLOM_STD:
        src = sumber[std]
        sel.append(f"{q(src)} AS {q(std)}" if src and src in cols else f"NULL AS {q(std)}")
    return pd.read_sql(text(f"SELECT {', '.join(sel)} FROM {TABLE_MASTER}"), engine)


def search_master(engine, kata, colmap, limit=1000):
    cols = set(table_columns(engine))
    q = lambda c: '"' + c.replace('"', '""') + '"'
    kond = [f'{q("ID_STR_OUTLET")} ILIKE :q']
    for c in ("PNAMLANG_AKHIR", colmap.get("cust_id"), colmap.get("alamat")):
        if c and c in cols:
            kond.append(f"CAST({q(c)} AS TEXT) ILIKE :q")
    sql = f'SELECT * FROM {TABLE_MASTER} WHERE {" OR ".join(kond)} ORDER BY {q("ID_STR_OUTLET")} LIMIT :lim'
    return pd.read_sql(text(sql), engine, params={"q": f"%{kata}%", "lim": int(limit)})


def rows_by_batch_week(engine, batch_week):
    return pd.read_sql(text(f"SELECT * FROM {TABLE_MASTER} WHERE batch_week = :b ORDER BY \"ID_STR_OUTLET\""),
                       engine, params={"b": batch_week})


def batch_weeks(engine):
    return pd.read_sql(text(f"SELECT batch_week, COUNT(*) AS jumlah_baris, MAX(created_at) AS terakhir FROM {TABLE_MASTER} "
                            "WHERE batch_week IS NOT NULL GROUP BY batch_week ORDER BY MAX(created_at) DESC"), engine)


# ------------------------------------------------------------------------------
# PEDOMAN
# ------------------------------------------------------------------------------
def save_pedoman(engine, df_seg, df_wil):
    with engine.begin() as c:
        df_seg.to_sql("pedoman_segment", c, if_exists="replace", index=False)
        df_wil.to_sql("pedoman_wilayah", c, if_exists="replace", index=False)


def load_pedoman(engine):
    insp = inspect(engine)
    if not (insp.has_table("pedoman_segment") and insp.has_table("pedoman_wilayah")):
        return None
    seg = pd.read_sql(text("SELECT * FROM pedoman_segment"), engine)
    wil = pd.read_sql(text("SELECT * FROM pedoman_wilayah"), engine)
    if seg.empty or wil.empty:
        return None
    return core.bangun_pedoman(seg, wil)


# ------------------------------------------------------------------------------
# RIWAYAT
# ------------------------------------------------------------------------------
def load_riwayat(engine, limit=100):
    return pd.read_sql(text("SELECT * FROM riwayat_batch ORDER BY id DESC LIMIT :n"), engine, params={"n": int(limit)})


def load_log(engine, batch_id):
    return pd.read_sql(text("SELECT jenis, id_str_outlet, detail FROM log_perubahan WHERE batch_id = :b ORDER BY id"),
                       engine, params={"b": int(batch_id)})


def hash_sudah_disimpan(engine, h):
    with engine.connect() as c:
        return c.execute(text("SELECT 1 FROM riwayat_batch WHERE hash_file = :h LIMIT 1"), {"h": h}).first() is not None


# ------------------------------------------------------------------------------
# MENYIMPAN BATCH MINGGUAN (satu transaksi atomik)
# ------------------------------------------------------------------------------
_SQL_MAX_SEQ = text(
    r"""SELECT regexp_replace("ID_STR_OUTLET", '\.[0-9]+$', '') AS prefix,
               MAX(CAST(substring("ID_STR_OUTLET" from '\.([0-9]+)$') AS BIGINT)) AS mx
        FROM master_outlet
        WHERE "ID_STR_OUTLET" ~ '\.[0-9]+$'
        GROUP BY 1""")


def _str_val(v):
    if v is None or (not isinstance(v, (list, tuple, dict, set)) and pd.isna(v)):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _samakan_tipe(df, info):
    """Sesuaikan tipe data kolom dengan tipe kolom di tabel (teks -> str, angka -> numerik)."""
    for col in info:
        name, tp = col["name"], col["type"]
        if name not in df.columns:
            continue
        if isinstance(tp, (T.Integer, T.Numeric)):
            df[name] = pd.to_numeric(df[name], errors="coerce")
        elif isinstance(tp, T.String):
            df[name] = df[name].map(_str_val).astype(object)
    return df


def save_batch(engine, ins, pedoman, prefix_map, batch_week, nama_file, hash_file):
    """Simpan batch: ID BARU diberi nomor urut (dihitung dari max di database di dalam transaksi + advisory lock),
    GABUNG ROW memakai ID_STR_OUTLET master. Semua (INSERT master, riwayat, log) berhasil atau dibatalkan bersama.
    Mengembalikan dict(batch_id, rows, ringkasan, kolom_dibuang)."""
    ins = ins.copy()
    aksi = ins["_AKSI"]
    waktu = pd.Timestamp(now_wib())
    with engine.begin() as conn:
        ensure_master_columns(conn)
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        max_seq = {r.prefix: int(r.mx) for r in conn.execute(_SQL_MAX_SEQ)}
        baru = ins[aksi == "ID BARU"]
        if len(baru):
            ids = core.beri_id_baru(baru, max_seq, prefix_map, pedoman)[0]
            if (ids == "").any():
                raise ValueError("Ada baris ID BARU yang kodenya tidak ditemukan di pedoman (cek kota/segmen).")
            ins.loc[baru.index, "ID_STR_OUTLET"] = ids

        masuk = ins[aksi.isin(["ID BARU", "GABUNG ROW"])]
        out = masuk.drop(columns=[c for c in masuk.columns if str(c).startswith("_")]).copy()
        out["created_at"] = waktu
        out["batch_week"] = batch_week
        info = inspect(conn).get_columns(TABLE_MASTER)
        kolom_tbl = [c["name"] for c in info]
        dibuang = [c for c in out.columns if c not in kolom_tbl and c != "BARIS_EXCEL"]
        out = out.loc[:, ~out.columns.duplicated()]
        out = out[[c for c in out.columns if c in kolom_tbl]].copy()
        tampil = out.copy()
        out = _samakan_tipe(out, info)
        if len(out):
            out.to_sql(TABLE_MASTER, conn, if_exists="append", index=False, method="multi", chunksize=500)

        n = {k: int((aksi == k).sum()) for k in ("ID BARU", "GABUNG ROW", "SUDAH ADA", "SKIP")}
        ringkasan = "; ".join(f"{k}: {v}" for k, v in n.items())
        bid = conn.execute(
            text("INSERT INTO riwayat_batch (batch_week, nama_file, hash_file, ringkasan) VALUES (:b, :n, :h, :r) RETURNING id"),
            {"b": batch_week, "n": nama_file, "h": hash_file, "r": ringkasan}).scalar()
        log = pd.DataFrame({
            "batch_id": bid, "jenis": aksi.values, "id_str_outlet": ins["ID_STR_OUTLET"].map(_t).values,
            "detail": [f"baris {r.get('BARIS_EXCEL')}: {_t(r.get('PNAMLANG_AKHIR'))} | {_t(r.get('KOTA_BARU'))} | {_t(r.get('SEGMENT_BARU'))}"
                       for _, r in ins.iterrows()]})
        log.to_sql("log_perubahan", conn, if_exists="append", index=False, method="multi", chunksize=500)
    return {"batch_id": bid, "rows": tampil, "ringkasan": ringkasan, "kolom_dibuang": dibuang}


def _t(v):
    return core._t(v)
