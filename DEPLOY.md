# Panduan Deploy: MDM Automation → Streamlit Community Cloud + Neon PostgreSQL

## Struktur proyek
```
mdm-app/
├── app.py                      # UI Streamlit
├── mdm_core.py                 # logika cleansing, pencocokan, pedoman ID
├── db.py                       # koneksi & query Neon (SQLAlchemy)
├── upload_initial_master.py    # dijalankan SEKALI untuk unggah master awal
├── requirements.txt
├── .gitignore
└── .streamlit/
    └── config.toml
```
`secrets.toml.example` hanya contoh format; **jangan** commit secrets asli. File `.xlsx` juga sudah di-`.gitignore` (data master tidak boleh masuk GitHub).

## 1. Siapkan database di Neon
1. Daftar/masuk di https://neon.tech → **Create project** (region terdekat, mis. Singapore).
2. Di Dashboard klik **Connect** → pilih **Pooled connection** → salin connection string:
   `postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require`
3. Simpan string itu; dipakai di langkah 2 dan 5.

## 2. Unggah master awal (sekali saja, dari laptop)
```bash
cd mdm-app
pip install -r requirements.txt

# Windows PowerShell:
$env:DATABASE_URL="postgresql://USER:PASSWORD@ep-xxxx-pooler.../neondb?sslmode=require"
# Mac/Linux:
# export DATABASE_URL="postgresql://..."

python upload_initial_master.py master_86k.xlsx --sheet "Hasil ID"
```
Hasil: tabel `master_outlet` (86 ribu baris) + kolom `created_at` dan `batch_week` (= `INITIAL`) + indeks.
Kolom `KOTA_BARU`, `SEGMENT_BARU`, `PNAMLANG_AKHIR` dibuat otomatis bila belum ada di Excel.
Skrip meminta konfirmasi `YA` jika tabel sudah berisi data (atau pakai `--force`).

## 3. Upload ke GitHub
```bash
cd mdm-app
git init
git add .
git status            # pastikan TIDAK ada secrets.toml atau .xlsx
git commit -m "MDM app: Streamlit + Neon"
git branch -M main
# Buat repo kosong (Private) di github.com, lalu:
git remote add origin https://github.com/<username>/<nama-repo>.git
git push -u origin main
```

## 4. Deploy di Streamlit Community Cloud
1. Buka https://share.streamlit.io → login dengan GitHub → **Create app** → *Deploy a public app from GitHub* (repo private tetap bisa dipakai setelah Streamlit diberi akses).
2. Isi: Repository = repo Anda, Branch = `main`, Main file path = `app.py`.
3. **Advanced settings** → pilih Python **3.11** atau **3.12** → tempel Secrets (langkah 5).
4. Klik **Deploy**.

## 5. Isi Secrets
Di Advanced settings (atau nanti: App → Settings → Secrets), tempel:
```toml
DATABASE_URL = "postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require"

# Opsional tapi disarankan: password buka aplikasi
APP_PASSWORD = "ganti-dengan-password-tim"
```

## 6. Pemakaian pertama di aplikasi
1. Menu **Pedoman ID** → unggah file Pedoman Penamaan Outlet → **Simpan pedoman** (tersimpan di Neon, cukup sekali; ulangi bila pedoman berubah).
2. Menu **Update mingguan** → upload Excel (~100 baris) → isi *Batch week* → **Jalankan cleansing & pencocokan**.
3. Di tabel review, isi kolom **KEPUTUSAN**:
   - `0` → buat ID baru (otomatis berurutan per prefix Segmen.Provinsi.KabKota)
   - **Master CUST_ID** (atau ID_STR_OUTLET master) → MERGE: baris baru ditambahkan dengan ID_STR_OUTLET outlet master tersebut
   - `SKIP` → lewati baris
4. Periksa **Pratinjau hasil** → centang konfirmasi → **Simpan ke master (Neon)**.

## Keamanan & operasional
- Aplikasi bisa menulis ke database; batasi aksesnya: isi `APP_PASSWORD` dan/atau atur app ke *Private* (Share → undang email tim).
- Streamlit Community Cloud menidurkan app yang lama tidak dipakai (klik "Wake up"); Neon juga menidurkan compute saat idle, jadi akses pertama bisa lambat beberapa detik.
- Backup: Neon menyediakan *history/restore* sesuai plan Anda (cek jendela waktunya di Dashboard → Restore). Disarankan tambahan `pg_dump` berkala.
- Nomor urut ID dihitung dari database di dalam satu transaksi dengan advisory lock, sehingga dua orang menyimpan bersamaan tidak menghasilkan ID kembar. Jika penyimpanan gagal, tidak ada data yang berubah (rollback otomatis).

## Pemecahan masalah
| Gejala | Penyebab / solusi |
|---|---|
| `Tidak dapat terhubung ke database` | `DATABASE_URL` salah/belum diisi di Secrets; pastikan ada `?sslmode=require` |
| `master_outlet belum ada` | skrip `upload_initial_master.py` belum dijalankan |
| ID tidak bisa dibuat (ERROR di pratinjau) | kota/segmen belum ada di pedoman → ubah KOTA_BARU/SEGMENT_BARU di tabel atau perbarui pedoman |
| Deploy gagal saat install | pastikan `requirements.txt` ada di root repo dan Python 3.11/3.12 |
| Perubahan kode tidak muncul | push ke GitHub; app auto-redeploy (atau *Reboot app*) |
