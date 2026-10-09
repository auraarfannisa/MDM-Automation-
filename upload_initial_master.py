"""
upload_initial_master.py
Jalankan SEKALI untuk mengunggah master awal (mis. master_86k.xlsx) ke tabel `master_outlet` di Neon.

  Windows/Mac/Linux:
    set DATABASE_URL=postgresql://...      (PowerShell: $env:DATABASE_URL="postgresql://...")
    python upload_initial_master.py master_86k.xlsx --sheet "Hasil ID"

  Atau letakkan DATABASE_URL di .streamlit/secrets.toml lalu jalankan skrip dari folder proyek.
"""
import argparse
import sys

import pandas as pd
from sqlalchemy import text

import db
import mdm_core as core


def main():
    ap = argparse.ArgumentParser(description="Unggah master awal ke Neon PostgreSQL (sekali jalan).")
    ap.add_argument("file", nargs="?", default="master_86k.xlsx", help="file Excel master (default: master_86k.xlsx)")
    ap.add_argument("--sheet", default=None, help="nama sheet (default: 'Hasil ID' bila ada, jika tidak sheet pertama)")
    ap.add_argument("--batch-week", default="INITIAL", help="nilai kolom batch_week untuk data awal (default: INITIAL)")
    ap.add_argument("--force", action="store_true", help="timpa tabel master_outlet yang sudah ada tanpa bertanya")
    a = ap.parse_args()

    print(f"Membaca {a.file} ...")
    sheets = pd.ExcelFile(a.file).sheet_names
    sheet = a.sheet or ("Hasil ID" if "Hasil ID" in sheets else sheets[0])
    df = pd.read_excel(a.file, sheet_name=sheet, dtype=str)   # dtype=str: ID/cust_id tidak rusak (mis. 1.10 -> 1.1)
    df.columns = [str(c).strip() for c in df.columns]
    if "ID_STR_OUTLET" not in df.columns:
        sys.exit(f"Kolom ID_STR_OUTLET tidak ada di sheet '{sheet}'. Kolom: {list(df.columns)}")
    df = df.dropna(how="all")
    df["ID_STR_OUTLET"] = df["ID_STR_OUTLET"].str.strip()
    kosong = df["ID_STR_OUTLET"].isna() | (df["ID_STR_OUTLET"] == "")
    if kosong.any():
        print(f"PERINGATAN: {int(kosong.sum())} baris tanpa ID_STR_OUTLET dibuang.")
        df = df[~kosong]
    df, info = core.siapkan_master_std(df)
    for i in info:
        print("INFO:", i)
    df["created_at"] = pd.Timestamp(db.now_wib())
    df["batch_week"] = a.batch_week
    print(f"Sheet '{sheet}': {len(df):,} baris, {len(df.columns)} kolom.")

    eng = db.make_engine()
    db.ping(eng)
    db.ensure_meta_tables(eng)
    if db.master_exists(eng) and not a.force:
        n = db.master_version(eng)[0]
        if input(f"Tabel master_outlet sudah berisi {n:,} baris. TIMPA? ketik YA untuk lanjut: ").strip() != "YA":
            sys.exit("Dibatalkan.")

    chunk = 2000
    for i in range(0, len(df), chunk):
        df.iloc[i:i + chunk].to_sql(db.TABLE_MASTER, eng, if_exists="replace" if i == 0 else "append",
                                    index=False, method="multi")
        print(f"  terunggah {min(i + chunk, len(df)):,}/{len(df):,}")
    db.create_indexes(eng, {k: core.deteksi_kolom(df.columns, k) for k in ("cust_id",)})
    with eng.connect() as c:
        n = c.execute(text(f"SELECT COUNT(*) FROM {db.TABLE_MASTER}")).scalar()
    print(f"SELESAI. master_outlet berisi {n:,} baris.")


if __name__ == "__main__":
    main()
