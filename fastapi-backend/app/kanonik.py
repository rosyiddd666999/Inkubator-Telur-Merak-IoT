"""Kanonisasi nilai data — satu sumber kebenaran untuk kolom VARCHAR "enum".

Masalah
-------
Kolom seperti ``breeders.asal`` / ``eggs.akhir`` bertipe VARCHAR, jadi nilai
apa pun lolos dari web, aplikasi Android, dan data lama tanpa pengaman.
Di database nyata ditemukan campuran: ``BELI`` vs ``Pembelian``,
``FERTIL`` vs ``Fertil``, ``MENETAS`` vs ``Menetas``, ``NEWBORN`` vs
``newborn``. Akibatnya:

* ``<option>`` di frontend tidak pernah cocok (nilai disembunyikan/di-hardcode)
* dashboard salah hitung: ``Egg.akhir != 'Gagal'`` tidak menangkap
  ``'Gagal Tetas'``, sehingga telur gagal tetap dihitung "aktif"

Modul ini dipakai dua arah:

* ``app.migrate`` — menormalkan data lama (sekali jalan, idempoten)
* router API — saat create/update, nilai baru selalu diubah jadi kanonik
  sebelum masuk database (jadi tidak perlu mengandalkan UI saja)

Kunci pemetaan selalu huruf kecil tanpa spasi tepi; nilai yang tidak dikenal
DIKEMBALIKAN APA ADANYA (tidak ditolak), lalu ditandai di frontend dengan
opsi "(nilai lama)" — jadi data lama tidak pernah memblokir save.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# (tabel, kolom, {nilai_lama_lowercase -> nilai_kanonik})
# Kolom bertipe ENUM tidak masuk daftar: MySQL sudah menyimpan nilai kanonik
# sesuai definisi ENUM.
FIELD_RULES: List[Tuple[str, str, Dict[str, str]]] = [
    ("breeders", "jenis_kelamin", {
        "jantan": "Jantan", "male": "Jantan", "laki": "Jantan", "l": "Jantan",
        "betina": "Betina", "female": "Betina", "bet": "Betina", "b": "Betina",
    }),
    ("breeders", "generasi", {
        "f0": "F0", "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4",
    }),
    ("breeders", "asal", {
        "beli": "Pembelian", "pembelian": "Pembelian",
        "ternak_sendiri": "Tangkaran sendiri", "tangkaran sendiri": "Tangkaran sendiri",
        "hibah": "Hibah", "hadiah": "Hibah",
    }),
    # Himpunan yang dipahami frontend: breeding/retired/sold/deceased.
    ("breeders", "status", {
        "breeding": "breeding", "aktif": "breeding",
        "resting": "retired", "retired": "retired",
        "sold": "sold", "terjual": "sold",
        "deceased": "deceased", "mati": "deceased",
    }),
    ("breeders", "varian_warna", {
        "biru": "Biru", "blue": "Biru", "biru / blue": "Biru",
        "hijau": "Hijau", "green": "Hijau",
        "putih": "Putih", "white": "Putih",
    }),
    ("eggs", "fertilitas", {
        "belum dicek": "Belum dicek", "belum_dicek": "Belum dicek",
        "fertil": "Fertil", "infertil": "Infertil",
    }),
    # Himpunan frontend: Proses/Menetas/Gagal Tetas/Dibuang.
    ("eggs", "akhir", {
        "proses": "Proses", "menetas": "Menetas",
        "gagal": "Gagal Tetas", "gagal tetas": "Gagal Tetas",
        "dibuang": "Dibuang",
    }),
    ("chicks", "status", {
        "newborn": "newborn", "growing": "growing",
        "ready_for_sale": "ready_for_sale", "sold": "sold",
    }),
    ("users", "role", {"pemilik": "pemilik", "staff": "staff"}),
    ("sales", "status", {"booking": "Booking", "dibayar": "Dibayar", "lunas": "Lunas"}),
]

RULE_INDEX: Dict[Tuple[str, str], Dict[str, str]] = {(t, c): m for t, c, m in FIELD_RULES}

# Nilai `eggs.akhir` yang berarti SUDAH SELESAI — dipakai dashboard untuk
# "telur aktif". 'Gagal' disertakan untuk jaga-jaga data pramigrasi.
AKHIR_SELESAI: Tuple[str, ...] = ("Menetas", "Gagal Tetas", "Gagal", "Dibuang")


def canonical(table: str, column: str, value):
    """Ubah `value` ke kanonik; nilai tak dikenal dikembalikan apa adanya."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    mapping = RULE_INDEX.get((table, column))
    if not mapping:
        return text
    return mapping.get(text.strip().lower(), text)


def canonical_pairs(table: str, payload: dict, columns: List[str]) -> dict:
    """Terapkan `canonical` untuk kolom tertentu yang ada di `payload`."""
    for column in columns:
        if column in payload:
            payload[column] = canonical(table, column, payload[column])
    return payload
