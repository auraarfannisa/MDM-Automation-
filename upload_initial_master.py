"""
upload_initial_master.py
Jalankan SEKALI untuk mengunggah master awal (mis. master_86k.xlsx) ke tabel `master_outlet` di Neon.
Memakai fungsi yang sama dengan app.py (tidak ada logika ganda).

  PowerShell:  $env:DATABASE_URL="postgresql://USER:PASS@ep-xxx-pooler.../neondb?sslmode=require"
  Mac/Linux :  export DATABASE_URL="postgresql://..."
  lalu       :  python upload_initial_master.py master_86k.xlsx --sheet "Hasil ID"
"""
import argparse
import hashlib
import sys

import pandas as pd

import app  # modul yang sama dengan aplikasi (main() tidak dijalankan saat di-import)


def main():
    ap = argparse.ArgumentParser(description="Unggah master awal ke Neon PostgreSQL (sekali jalan).")
    ap.add_argument("file", nargs="?", default="master_86k.xlsx", help="file Excel master (default: master_86k.xlsx)")
    ap.add_argument("--sheet", default=None, help="nama sheet (default: 'Hasil ID' bila ada, jika tidak sheet pertama)")
    ap.add_argument("--wilayah", default=None, help="master_wilayah.csv (opsional)")
    ap.add_argument("--batch-week", default="INITIAL", help="nilai kolom batch_week untuk data awal")
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
    df, info = app.siapkan_master_std(df)
    for i in info:
        print("INFO:", i)
    print(f"Sheet '{sheet}': {len(df):,} baris, {len(df.columns)} kolom.")

    app.engine().connect().close()   # uji koneksi
    app.ensure_meta_tables()
    if app.db_ready() and not a.force:
        n = app.master_info()[0]
        if input(f"Tabel master_outlet sudah berisi {n:,} baris. TIMPA? ketik YA untuk lanjut: ").strip() != "YA":
            sys.exit("Dibatalkan.")
    dwil = pd.read_csv(a.wilayah) if a.wilayah else None
    print("Mengunggah ke Neon (satu transaksi, mohon tunggu) ...")
    with open(a.file, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    app.simpan_master_awal(df, a.file, h, f"{len(df)} baris", dwil, a.batch_week)
    print(f"SELESAI. master_outlet berisi {app.master_info()[0]:,} baris.")


if __name__ == "__main__":
    main()
