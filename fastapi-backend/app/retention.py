"""Retensi data: buang baris lama supaya tabel tidak tumbuh tanpa batas.

Kenapa perlu
------------
`POST /api/incubator/status` memakai mode **append-only** dan dipanggil
maksimal sekali per 60 detik oleh tiap tab browser yang terbuka. Sementara
alert dibuat tiap kali suhu/kelembapan melewati ambang tanpa dedupe. Hasilnya
di database produksi (Nov 2026): `incubator_status` 8.602 baris,
`alerts` 7.116 baris — padahal keduanya "data hidup" yang isinya sudah
tergambar di baris-baris terbaru.

Nilai default diambil dari env (bisa ditimpa tanpa ubah kode):

* ``RETENTION_STATUS_DAYS`` / ``RETENTION_STATUS_MAX_ROWS`` — status inkubator
* ``RETENTION_ALERT_DAYS`` — alert (juga membatasi payload `GET /api/alerts`)
* ``RETENTION_CCTV_DAYS`` — snapshot MinIO (baris DB + objek penyimpanan)
* ``RETENTION_DISABLED=1`` — matikan seluruhnya

Log telemetri TIDAK ikut dipretensi: kolom ``timestamp``-nya VARCHAR(50)
sehingga tidak bisa dibandingkan dengan datetime, dan tabelnya masih kosong.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger("merak.retention")

# Status inkubator: 30 hari ATAU 2000 baris terbaru, mana yang lebih kecil.
STATUS_DAYS = int(os.getenv("RETENTION_STATUS_DAYS", "30"))
STATUS_MAX_ROWS = int(os.getenv("RETENTION_STATUS_MAX_ROWS", "2000"))
ALERT_DAYS = int(os.getenv("RETENTION_ALERT_DAYS", "90"))
CCTV_DAYS = int(os.getenv("RETENTION_CCTV_DAYS", "90"))
DISABLED = os.getenv("RETENTION_DISABLED", "").lower() in ("1", "true", "yes")

_CHUNK = 500


def _prune_old(db, model, column, days: int) -> int:
    if days <= 0:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=days)
    count = db.query(model).filter(column < cutoff).delete(synchronize_session=False)
    return count


def _prune_excess(db, model, max_rows: int) -> int:
    """Sisakan hanya `max_rows` baris terbaru (diurutkan PK)."""
    if max_rows <= 0:
        return 0
    rows = db.query(model.id).order_by(model.id.desc()).offset(max_rows).all()
    ids = [r[0] for r in rows]
    if not ids:
        return 0
    total = 0
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        total += db.query(model).filter(model.id.in_(chunk)).delete(synchronize_session=False)
    return total


def prune(db) -> dict:
    """Jalankan semua aturan retensi. Kembalikan {nama_tabel: jumlah_dihapus}."""
    if DISABLED:
        logger.info("Retention dimatikan lewat RETENTION_DISABLED")
        return {}

    from .models import Alert, CctvSnapshot, IncubatorStatus

    removed: dict[str, int] = {}

    n = _prune_old(db, IncubatorStatus, IncubatorStatus.updated_at, STATUS_DAYS)
    if n:
        removed["incubator_status"] = removed.get("incubator_status", 0) + n
    n = _prune_excess(db, IncubatorStatus, STATUS_MAX_ROWS)
    if n:
        removed["incubator_status"] = removed.get("incubator_status", 0) + n

    n = _prune_old(db, Alert, Alert.created_at, ALERT_DAYS)
    if n:
        removed["alerts"] = n

    # telemetry_logs TIDAK dipretensi di sini: kolom `timestamp` bertipe
    # VARCHAR(50) sehingga tidak bisa dibandingkan dengan datetime. Tabelnya
    # juga belum pernah terisi (hanya diisi lewat endpoint yang belum dipakai).

    # Snapshot CCTV: hapus objek MinIO lebih dulu, lalu barisnya.
    if CCTV_DAYS > 0:
        cutoff = datetime.utcnow() - timedelta(days=CCTV_DAYS)
        rows = db.query(CctvSnapshot).filter(CctvSnapshot.captured_at < cutoff).all()
        if rows:
            try:
                from .storage import delete_object

                for row in rows:
                    try:
                        delete_object(row.object_key)
                    except Exception:
                        logger.warning("Gagal hapus objek MinIO %s (baris tetap dihapus)",
                                       row.object_key)
            except Exception:
                logger.exception("Modul storage tidak tersedia, objek snapshot dibiarkan")
            for row in rows:
                db.delete(row)
            removed["cctv_snapshots"] = len(rows)

    db.commit()

    if removed:
        logger.info("Retention selesai: %s", ", ".join(
            f"{table} -{count}" for table, count in removed.items()))
    return removed


def run_retention_job() -> None:
    """Entry point scheduler (dan saat startup) — gagal tidak boleh merusak app."""
    from .database import SessionLocal

    db = SessionLocal()
    try:
        prune(db)
    except Exception:
        logger.exception("Retention job gagal")
        db.rollback()
    finally:
        db.close()
