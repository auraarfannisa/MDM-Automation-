"""
app.py - MDM Automation (Streamlit Community Cloud + Neon PostgreSQL)
Alur: upload Excel mingguan -> cleansing -> pencocokan ke master (86k baris) -> review user -> simpan ke Neon.
"""
import hashlib
import hmac
import io

import pandas as pd
import streamlit as st

import db
import mdm_core as core

st.set_page_config(page_title="MDM Automation", layout="wide")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ==============================================================================
# KEAMANAN & KONEKSI
# ==============================================================================
def gerbang_password():
    """Opsional: jika APP_PASSWORD diisi di Secrets, user harus memasukkannya dulu."""
    try:
        pw = st.secrets.get("APP_PASSWORD")
    except Exception:
        pw = None
    if not pw or st.session_state.get("auth_ok"):
        return
    st.title("Master Data Management (MDM) Automation")
    x = st.text_input("Password", type="password")
    if x:
        if hmac.compare_digest(x, str(pw)):
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Password salah.")
    st.stop()


@st.cache_resource
def get_engine():
    return db.make_engine()


@st.cache_resource
def siapkan_db():
    db.ensure_meta_tables(get_engine())
    return True


# ==============================================================================
# CACHE DATA (master 86 ribu baris ditarik sekali per versi master)
# ==============================================================================
@st.cache_data(ttl=3600, show_spinner="Mengambil data master dari Neon...")
def ambil_master(ver, colmap_items):
    """Master (kolom yang dipakai pencocokan). `ver` berubah tiap master berubah -> cache otomatis diperbarui."""
    return db.load_master_slim(get_engine(), dict(colmap_items))


@st.cache_resource(max_entries=1, show_spinner="Membangun indeks pencocokan...")
def ambil_index(ver, khusus, _master):
    return core.MasterIndex(_master, khusus=khusus)


@st.cache_data(ttl=3600)
def ambil_pedoman():
    return db.load_pedoman(get_engine())


def df_to_excel_bytes(sheets):
    buf = io.BytesIO()
    try:
        import xlsxwriter  # noqa: F401
        engine = "xlsxwriter"
    except ImportError:
        engine = "openpyxl"
    with pd.ExcelWriter(buf, engine=engine) as xw:
        for name, d in sheets.items():
            d.to_excel(xw, sheet_name=name[:31], index=False)
    return buf.getvalue()


def minggu_default():
    iso = db.now_wib().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ==============================================================================
# HALAMAN: UPDATE MINGGUAN
# ==============================================================================
def halaman_update(eng):
    st.subheader("Update mingguan")
    if not db.master_exists(eng):
        st.warning("Tabel master_outlet belum ada di Neon. Jalankan `python upload_initial_master.py` dulu (lihat DEPLOY.md).")
        return
    ver = db.master_version(eng)
    colmap = db.master_colmap(eng)
    pedoman = ambil_pedoman()
    c1, c2 = st.columns(2)
    c1.metric("Baris master", f"{ver[0]:,}")
    c2.metric("Batch tersimpan", ver[1])
    if not pedoman:
        st.warning("Pedoman ID belum diunggah (menu 'Pedoman ID'). Tanpa pedoman, ID hanya bisa dibuat dari prefix master.")

    hs = st.session_state.get("hasil_simpan")
    if hs:
        st.success(f"Batch #{hs['batch_id']} tersimpan ke master. {hs['ringkasan']}")
        if hs["kolom_dibuang"]:
            st.caption("Kolom data baru yang tidak ada di tabel master (tidak disimpan): " + ", ".join(map(str, hs["kolom_dibuang"])))
        st.download_button("Unduh baris yang baru disimpan (.xlsx)", df_to_excel_bytes({"BARIS_BARU": hs["rows"]}),
                           file_name=f"MASTER_BATCH_{hs['batch_id']}.xlsx", mime=XLSX_MIME)
        st.divider()

    f = st.file_uploader("Upload data baru mingguan (.xlsx)", type=["xlsx"])
    if f:
        data = f.getvalue()
        h = hashlib.sha256(data).hexdigest()
        if st.session_state.get("up_hash") != h:
            st.session_state["up_sheets"] = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str)
            st.session_state["up_hash"] = h
        sheets = st.session_state["up_sheets"]
        daftar = list(sheets)
        st.caption("Sheet di file: " + ", ".join(f"{k} ({len(v):,} baris)" for k, v in sheets.items()))
        sheet = st.selectbox("Sheet data baru", daftar, index=daftar.index("Data_Baru") if "Data_Baru" in daftar else 0)
        df_raw = sheets[sheet]
        batch_week = st.text_input("Batch week", value=minggu_default(), help="Label batch, disimpan di kolom batch_week.")

        with st.expander("Kolom & pengaturan pencocokan", expanded=False):
            opsi = ["(tidak ada)"] + list(df_raw.columns)
            pilih = {}
            cols = st.columns(3)
            for col, (k, label) in zip(cols, (("cust_id", "cust_id"), ("alamat", "alamat"), ("distributor", "distributor"))):
                d = core.deteksi_kolom(df_raw, k)
                pilih[k] = col.selectbox(f"Kolom {label} (data baru)", opsi, index=opsi.index(d) if d in opsi else 0, key=f"kb_{k}")
            khusus = st.text_input("Distributor yang tail cust_id-nya (setelah tanda '-') ikut dicocokkan", "KFTD, AAM")
            per_dist = st.checkbox("Cocokkan cust_id hanya di distributor yang sama", value=True)
        kol_baru = {k: (None if v == "(tidak ada)" else v) for k, v in pilih.items()}
        khusus_t = tuple(x.strip().upper() for x in khusus.split(",") if x.strip())

        if db.hash_sudah_disimpan(eng, h):
            st.warning("File ini identik dengan file yang pernah disimpan ke master.")
        if st.button("Jalankan cleansing & pencocokan", type="primary"):
            try:
                with st.spinner("Memproses..."):
                    run = jalankan(df_raw, f.name, h, batch_week, kol_baru, khusus_t, per_dist, ver, colmap, pedoman)
            except Exception as e:
                st.error(f"Gagal: {e}")
            else:
                st.session_state["run"] = run
                st.session_state.pop("hasil_simpan", None)
                st.rerun()

    if st.session_state.get("run"):
        tampil_review(eng, st.session_state["run"], pedoman, ver)


def jalankan(df_raw, nama_file, h, batch_week, kol_baru, khusus, per_dist, ver, colmap, pedoman):
    if len(df_raw) == 0:
        raise ValueError("Sheet tidak berisi baris data.")
    for kolom, kand in (("nama", ("PNAMLANG_CLEAN", "PNAMLANG")), ("kota", ("KOTA_CLEAN", "KOTA"))):
        if not any(c in df_raw.columns for c in kand):
            raise ValueError(f"Sheet tidak punya kolom {kolom} ({' / '.join(kand)}). Kolom yang ada: {list(df_raw.columns)}")
    raw = df_raw.reset_index(drop=True).copy()
    raw["BARIS_EXCEL"] = raw.index + 2
    master = ambil_master(ver, tuple(sorted(colmap.items())))
    idx = ambil_index(ver, khusus, master)
    base = core.clean_dataframe_baru(raw, pedoman)
    hasil = core.cocokkan(base, idx, kol_baru, per_dist)
    review = core.susun_review(base, hasil, kol_baru, pedoman)
    return {"id": st.session_state.get("run_id", 0) + 1, "base": base, "review": review, "idx": idx, "kol_baru": kol_baru,
            "colmap": colmap, "nama_file": nama_file, "hash": h, "batch_week": batch_week, "ver": ver}


def tampil_review(eng, run, pedoman, ver_now):
    st.divider()
    st.write(f"Hasil untuk file: **{run['nama_file']}** (batch week: **{run['batch_week']}**)")
    if run["ver"] != ver_now:
        st.warning("Master berubah (disimpan pengguna lain) sejak proses dijalankan. Nomor ID tetap aman, tetapi duplikat "
                   "terhadap data baru tersebut tidak terdeteksi; disarankan jalankan ulang.")
    rv0, idx = run["review"], run["idx"]
    vc = rv0["STATUS"].value_counts()
    m = st.columns(4)
    m[0].metric("Total baris", len(rv0))
    m[1].metric("Baru (tanpa kandidat)", int(vc.get("BARU", 0)))
    m[2].metric("Mirip kuat", int(vc.get("MIRIP KUAT", 0)))
    m[3].metric("Perlu cek", int(vc.get("PERLU CEK", 0)))

    st.markdown("**Keputusan** (kolom KEPUTUSAN): `0` = buat ID baru · isi **Master CUST_ID** = gabung (MERGE) ke outlet master tersebut · "
                "`SKIP` = lewati baris ini. Baris yang punya kandidat di master dikosongkan agar Anda putuskan sendiri. "
                "KOTA_BARU, PNAMLANG_AKHIR, dan SEGMENT_BARU juga bisa diedit.")
    if st.button("Isi otomatis saran Master CUST_ID untuk baris MIRIP KUAT"):
        mk = rv0["STATUS"] == "MIRIP KUAT"
        run["review"].loc[mk, "KEPUTUSAN"] = rv0.loc[mk, "SARAN_MASTER_CUST_ID"].astype(str)
        run["id"] += 1
        st.session_state["run_id"] = run["id"]
        st.rerun()
        return

    opsi_kota = None
    if pedoman:
        opsi_kota = sorted(set(pedoman["wil"]) | {v for v in rv0["KOTA_BARU"].dropna().astype(str) if v})
    cfg = {
        "KEPUTUSAN": st.column_config.TextColumn("KEPUTUSAN (0 / Master CUST_ID / SKIP)", pinned=True, width="medium"),
        "STATUS": st.column_config.TextColumn("STATUS"),
        "KOTA_BARU": (st.column_config.SelectboxColumn("KOTA_BARU (pilih)", options=opsi_kota) if opsi_kota
                      else st.column_config.TextColumn("KOTA_BARU (edit)")),
        "PNAMLANG_AKHIR": st.column_config.TextColumn("PNAMLANG_AKHIR (edit)"),
        "SEGMENT_BARU": st.column_config.TextColumn("SEGMENT_BARU (edit)"),
    }
    tampil = ["KEPUTUSAN", "STATUS", "CATATAN_CEK", "BARIS_EXCEL", "PNAMLANG_ASAL", "PNAMLANG_AKHIR", "ALAMAT_BARU", "KOTA_BARU",
              "SEGMENT_BARU", "CUST_ID_BARU", "DISTRIBUTOR_BARU", "SARAN_MASTER_CUST_ID", "PNAMLANG_MASTER", "ALAMAT_MASTER",
              "KOTA_MASTER", "ID_STR_OUTLET_MASTER", "SKOR_NAMA", "SKOR_ALAMAT"]
    editable = {"KEPUTUSAN", "PNAMLANG_AKHIR", "KOTA_BARU", "SEGMENT_BARU"}
    ed = st.data_editor(rv0, column_order=tampil, column_config=cfg, hide_index=True, width="stretch", height=520,
                        disabled=[c for c in rv0.columns if c not in editable], key=f"editor_{run['id']}")

    final = core.terapkan_edit(rv0, ed)
    rencana = core.susun_rencana(final, idx, pedoman)
    n = rencana["AKSI"].value_counts()
    n_err = int((rencana["ERROR"].astype(str).str.strip() != "").sum())
    st.markdown("#### Pratinjau hasil")
    m = st.columns(5)
    m[0].metric("ID baru", int(n.get("ID BARU", 0)))
    m[1].metric("Gabung (MERGE)", int(n.get("GABUNG ROW", 0)))
    m[2].metric("Dilewati", int(n.get("SKIP", 0) + n.get("SUDAH ADA", 0)))
    m[3].metric("Belum diputuskan", int(n.get("BELUM", 0)))
    m[4].metric("Bermasalah", n_err)
    prev = rencana.copy()
    prev.insert(0, "BARIS_EXCEL", final["BARIS_EXCEL"])
    prev["CUST_ID_BARU"] = final["CUST_ID_BARU"]
    with st.expander("Rincian rencana per baris", expanded=n_err > 0):
        st.dataframe(prev, hide_index=True, width="stretch")
    st.caption("Nomor urut ID_STR_OUTLET di pratinjau bersifat sementara; nomor final ditetapkan di database saat tombol simpan ditekan.")

    blok = core.validasi_rencana(rencana)
    for b in blok:
        st.error(b)
    ok = st.checkbox("Saya sudah memeriksa hasil di atas dan siap menyimpan ke master", key=f"ok_{run['id']}")
    ok_ulang = True
    if db.hash_sudah_disimpan(eng, run["hash"]):
        ok_ulang = st.checkbox("File ini pernah disimpan sebelumnya; saya sengaja menyimpannya lagi", key=f"ul_{run['id']}")
    if st.button("Simpan ke master (Neon)", type="primary", disabled=bool(blok) or not (ok and ok_ulang)):
        try:
            with st.spinner("Menyimpan ke Neon..."):
                ins = core.siapkan_insert(run["base"], final, rencana, run["kol_baru"], run["colmap"])
                hasil = db.save_batch(eng, ins, pedoman, idx.prefix_map, run["batch_week"], run["nama_file"], run["hash"])
        except Exception as e:
            st.error(f"Gagal menyimpan (tidak ada data yang berubah): {e}")
            return
        st.cache_data.clear()
        st.session_state["hasil_simpan"] = hasil
        st.session_state.pop("run", None)
        st.rerun()


# ==============================================================================
# HALAMAN: PEDOMAN ID
# ==============================================================================
def halaman_pedoman(eng):
    st.subheader("Pedoman ID_STR_OUTLET")
    st.caption("Format ID: KodeSegmen.KodeProvinsi.KodeKab/Kota.NomorUrut. Unggah file Pedoman Penamaan Outlet (.xlsx); "
               "tabel segmen, provinsi, dan kab/kota dibaca otomatis lalu disimpan di Neon.")
    p = ambil_pedoman()
    if p:
        st.success(f"Pedoman tersimpan: {len(p['seg'])} segmen, {p['n_prov']} provinsi, {p['n_wil']} kab/kota.")
    else:
        st.warning("Belum ada pedoman tersimpan.")
    f = st.file_uploader("File pedoman (.xlsx)", type=["xlsx"], key="pedoman_up")
    if f:
        try:
            seg, wil = core.parse_pedoman(f.getvalue())
        except Exception as e:
            st.error(f"Gagal membaca pedoman: {e}")
            return
        st.write(f"Terbaca: {len(seg)} segmen, {wil['KODE_PROVINSI'].nunique()} provinsi, {len(wil)} kab/kota.")
        c1, c2 = st.columns(2)
        c1.dataframe(seg, width="stretch")
        c2.dataframe(wil, width="stretch", height=300)
        if st.button("Simpan pedoman", type="primary"):
            db.save_pedoman(eng, seg, wil)
            st.cache_data.clear()
            st.success("Pedoman tersimpan.")


# ==============================================================================
# HALAMAN: CARI MASTER
# ==============================================================================
def halaman_cari(eng):
    st.subheader("Cari master")
    if not db.master_exists(eng):
        st.info("Master belum ada.")
        return
    kata = st.text_input("Cari (nama, CUST_ID, alamat, atau ID_STR_OUTLET)")
    if len(kata.strip()) >= 3:
        d = db.search_master(eng, kata.strip(), db.master_colmap(eng))
        st.write(f"{len(d):,} baris (maksimum 1.000)")
        st.dataframe(d, width="stretch", hide_index=True)
        if len(d):
            st.download_button("Unduh hasil (.xlsx)", df_to_excel_bytes({"HASIL": d}), file_name="hasil_cari_master.xlsx", mime=XLSX_MIME)
    else:
        st.caption("Ketik minimal 3 karakter.")


# ==============================================================================
# HALAMAN: RIWAYAT
# ==============================================================================
def halaman_riwayat(eng):
    st.subheader("Riwayat batch")
    r = db.load_riwayat(eng)
    if r.empty:
        st.info("Belum ada batch tersimpan.")
    else:
        st.dataframe(r, width="stretch", hide_index=True)
        bid = st.selectbox("Lihat log perubahan batch", list(r["id"]),
                           format_func=lambda i: f"#{i} - {r.set_index('id').at[i, 'nama_file']}")
        st.dataframe(db.load_log(eng, bid), width="stretch", hide_index=True)
    if db.master_exists(eng):
        st.markdown("**Unduh baris per batch_week**")
        bw = db.batch_weeks(eng)
        if bw.empty:
            st.caption("Belum ada baris dengan batch_week.")
        else:
            st.dataframe(bw, width="stretch", hide_index=True)
            pilih = st.selectbox("batch_week", list(bw["batch_week"]))
            if st.button("Siapkan file"):
                d = db.rows_by_batch_week(eng, pilih)
                st.session_state["dl_bw"] = (pilih, df_to_excel_bytes({"MASTER": d}), len(d))
            dl = st.session_state.get("dl_bw")
            if dl and dl[0] == pilih:
                st.download_button(f"Unduh {dl[0]} ({dl[2]:,} baris)", dl[1], file_name=f"MASTER_{dl[0]}.xlsx", mime=XLSX_MIME)


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    gerbang_password()
    st.title("Master Data Management (MDM) Automation")
    try:
        eng = get_engine()
        db.ping(eng)
        siapkan_db()
    except Exception as e:
        st.error(f"Tidak dapat terhubung ke database Neon: {e}")
        st.info("Periksa DATABASE_URL di Settings > Secrets (harus memuat ?sslmode=require).")
        st.stop()
    menu = st.sidebar.radio("Menu", ["Update mingguan", "Pedoman ID", "Cari master", "Riwayat"])
    {"Update mingguan": halaman_update, "Pedoman ID": halaman_pedoman,
     "Cari master": halaman_cari, "Riwayat": halaman_riwayat}[menu](eng)


main()
