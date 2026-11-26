# Migrasi database

Migrasi skema **tidak lagi dijalankan manual**. Semua langkah idempoten ada di
`app/migrate.py` dan dijalankan otomatis saat API start (`AUTO_MIGRATE=true`,
default), atau manual:

```bash
# lewat container (pakai env asli)
docker run --rm --network merak-stack_merak_net --env-file merak/fastapi-backend/.env \
  backend-api python -m app.migrate --status     # lihat yang sudah/belum
docker run --rm --network merak-stack_merak_net --env-file merak/fastapi-backend/.env \
  backend-api python -m app.migrate --dry-run    # lihat DDL tanpa menjalankan
docker run --rm --network merak-stack_merak_net --env-file merak/fastapi-backend/.env \
  backend-api python -m app.migrate              # terapkan

# verifikasi skema model vs information_schema (exit 1 kalau ada masalah)
docker run --rm --network merak-stack_merak_net --env-file merak/fastapi-backend/.env \
  backend-api python -m app.verify_schema

# backup sebelum migrasi apapun
./scripts/db-backup.sh
```

Versi yang sudah jalan dicatat di tabel `schema_migrations`.

Aturan menambah migrasi: tambahkan `Step` baru di `STEPS` (`app/migrate.py`)
dengan nomor versi berikutnya, dan fungsi `needs_*` yang **cek dulu kondisinya
lewat `information_schema`** sebelum mengeluarkan DDL — supaya aman diulang
pada DB lama maupun DB baru.

Nilai kanonik kolom VARCHAR "enum" (`asal`, `status`, `akhir`, ...) didefinisikan
di `app/kanonik.py` dan dipakai bersama oleh migrasi data dan router API.

## legacy/

`legacy/*.sql` adalah migrasi **manual lama** yang sudah dijalankan sekali pada
database produksi dan kini **dilapisi** (superseded) oleh langkah
`legacy_schema` di `app/migrate.py`. File dipertahankan hanya sebagai arsip
riwayat — jangan dijalankan ulang.
