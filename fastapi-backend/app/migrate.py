"""Runner migrasi skema database (MySQL).

Kenapa bukan Alembic
--------------------
Aplikasi selalu memanggil ``Base.metadata.create_all()`` saat startup, dan
fungsi itu hanya MENAMBAH tabel yang belum ada — tidak pernah mengubah tabel
yang sudah ada. Di dunia nyata skema lama (dari `migrasi_*.sql` manual) sering
tidak sinkron dengan model, sehingga autogenerate Alembic justru menawarkan
perubahan yang salah. Setiap langkah di runner ini mengecek sendiri kondisi
tabel lewat ``information_schema``, jadi aman untuk DB lama (kolomnya belum
ada) sekaligus DB baru (sudah dibuat utuh oleh ``create_all``).

Aman diulang
------------
Versi yang sudah jalan dicatat di tabel ``schema_migrations`` dan tidak
diulang. Langkah yang ternyata tidak butuh apa-apa juga dicatat (no-op), jadi
``--status`` tidak menampilkan baris yang menyesatkan.

Pemakaian::

    python -m app.migrate --status     # lihat yang sudah/belum
    python -m app.migrate --dry-run    # lihat DDL yang akan dijalankan
    python -m app.migrate              # terapkan semua
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger("merak.migrate")

# Satu perintah DDL/DML: (sql, parameter).
Statement = Tuple[str, Dict[str, object]]
Needs = Callable[[Connection], List[Statement]]


class MigrationError(RuntimeError):
    """Migrasi gagal — biasanya menandakan skema DB menyimpang dari skema kode."""


# ---------------------------------------------------------------------------
# Helper information_schema
# ---------------------------------------------------------------------------
def _one(conn: Connection, sql: str, **params):
    return conn.execute(text(sql), params).first()


def column_exists(conn: Connection, table: str, column: str) -> bool:
    return _one(
        conn,
        "SELECT 1 FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c",
        t=table,
        c=column,
    ) is not None


def column_type(conn: Connection, table: str, column: str) -> str | None:
    row = _one(
        conn,
        "SELECT COLUMN_TYPE, COLUMN_DEFAULT FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c",
        t=table,
        c=column,
    )
    if row is None:
        return None
    return f"{row[0]}|{row[1]}"


def index_exists(conn: Connection, name: str) -> bool:
    return _one(
        conn,
        "SELECT 1 FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND INDEX_NAME = :n LIMIT 1",
        n=name,
    ) is not None


def constraint_exists(conn: Connection, name: str) -> bool:
    return _one(
        conn,
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_NAME = :n LIMIT 1",
        n=name,
    ) is not None


def fk_exists(conn: Connection, table: str, column: str) -> bool:
    return _one(
        conn,
        "SELECT 1 FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c "
        "AND REFERENCED_TABLE_NAME IS NOT NULL",
        t=table,
        c=column,
    ) is not None


def enum_has_member(conn: Connection, table: str, column: str, member: str) -> bool:
    row = _one(
        conn,
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c",
        t=table,
        c=column,
    )
    if row is None or row[0] is None:
        return False
    # COLUMN_TYPE contoh: enum('SUHU','KELEMBAPAN','LAIN')
    return member in [p.strip().strip("'") for p in str(row[0]).removeprefix("enum(").removesuffix(")").split(",")]


def count(conn: Connection, sql: str, **params) -> int:
    row = _one(conn, sql, **params)
    return int(row[0]) if row and row[0] is not None else 0


def exists_value(conn: Connection, table: str, column: str, value: str) -> bool:
    return _one(
        conn,
        f"SELECT 1 FROM `{table}` WHERE BINARY `{column}` = :v LIMIT 1",
        v=value,
    ) is not None


# ---------------------------------------------------------------------------
# Normalisasi nilai data lama (varchar) ke kanonik.
# ---------------------------------------------------------------------------
# Definisinya di app/kanonik.py supaya satu sumber kebenaran dipakai bersama
# oleh runner migrasi dan router API (lihat kanonik.canonical()).
from .kanonik import FIELD_RULES as NORMALIZATIONS  # noqa: E402


# ---------------------------------------------------------------------------
# Langkah-langkah
# ---------------------------------------------------------------------------
def needs_legacy_schema(conn: Connection) -> List[Statement]:
    """Versi idempoten dari migrasi_silsilah.sql, migrasi_storage_cctv.sql,
    dan migrasi_incubator_terakhir_rotasi.sql (ketiganya tidak bisa diulang)."""
    stmts: List[Statement] = []

    def add_col(table: str, column: str, ddl: str) -> None:
        if not column_exists(conn, table, column):
            stmts.append((ddl, {}))

    add_col("eggs", "induk_jantan_id", "ALTER TABLE eggs ADD COLUMN induk_jantan_id VARCHAR(50) NULL")
    add_col("eggs", "induk_betina_id", "ALTER TABLE eggs ADD COLUMN induk_betina_id VARCHAR(50) NULL")
    add_col("breeders", "generasi", "ALTER TABLE breeders ADD COLUMN generasi VARCHAR(50) NULL AFTER tanggal_lahir")
    add_col("breeders", "varian_warna", "ALTER TABLE breeders ADD COLUMN varian_warna VARCHAR(100) NULL AFTER generasi")
    add_col("breeders", "status", "ALTER TABLE breeders ADD COLUMN status VARCHAR(50) NULL AFTER varian_warna")
    add_col("breeders", "foto_url", "ALTER TABLE breeders ADD COLUMN foto_url VARCHAR(500) NULL AFTER status")
    add_col("chicks", "induk_jantan_id", "ALTER TABLE chicks ADD COLUMN induk_jantan_id VARCHAR(50) NULL")
    add_col("chicks", "induk_betina_id", "ALTER TABLE chicks ADD COLUMN induk_betina_id VARCHAR(50) NULL")
    add_col("users", "avatar_url", "ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500) NULL")
    add_col("incubator_status", "terakhir_rotasi",
            "ALTER TABLE incubator_status ADD COLUMN terakhir_rotasi DATETIME NULL AFTER lampu_status")

    if _one(conn, "SELECT 1 FROM information_schema.TABLES "
                  "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cctv_snapshots'") is None:
        stmts.append((
            "CREATE TABLE IF NOT EXISTS cctv_snapshots ("
            " id INT AUTO_INCREMENT PRIMARY KEY,"
            " captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " object_key VARCHAR(500) NOT NULL,"
            " url VARCHAR(500) NOT NULL,"
            " source VARCHAR(100) NOT NULL DEFAULT 'incubator',"
            " INDEX ix_cctv_snapshots_id (id)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci",
            {},
        ))
    return stmts


def needs_alert_rotasi(conn: Connection) -> List[Statement]:
    """Bug produksi: model punya AlertTipe.ROTASI_GAGAL tapi kolom enum
    ('SUHU','KELEMBAPAN','LAIN') — INSERT gagal ERROR 1265 di mode STRICT,
    jadi `POST /api/incubator/rotation-logs` status 'gagal' memunculkan 500
    dan alert kehilangan rekaman. Migrasi menambahkan member enum itu."""
    if enum_has_member(conn, "alerts", "tipe", "ROTASI_GAGAL"):
        return []
    return [("ALTER TABLE alerts MODIFY COLUMN tipe "
             "ENUM('SUHU','KELEMBAPAN','ROTASI_GAGAL','LAIN') NOT NULL", {})]


def needs_breeder_status_default(conn: Connection) -> List[Statement]:
    current = column_type(conn, "breeders", "status")
    if current is None:
        return []
    _type_name, default = current.split("|", 1)
    # CASE SENSITIVE: 'BREEDING' (dipakai sekarang) memang beda dari 'breeding'
    # (nilai kanonik yang dipakai frontend), jadi harus diperbaiki.
    if str(default).strip("'\"") == "breeding":
        return []
    return [("ALTER TABLE breeders MODIFY COLUMN status VARCHAR(50) NOT NULL DEFAULT 'breeding'", {})]


def needs_indexes(conn: Connection) -> List[Statement]:
    """Kolom yang selalu dipakai ORDER BY / filter tapi tidak punya index."""
    wanted: List[Tuple[str, str, str]] = [
        ("ix_alerts_created_at", "alerts", "`created_at`"),
        ("ix_alerts_tipe_isread_created", "alerts", "`tipe`, `is_read`, `created_at`"),
        ("ix_telemetry_logs_timestamp", "telemetry_logs", "`timestamp`"),
        ("ix_finance_entries_tanggal", "finance_entries", "`tanggal`"),
        ("ix_sales_tanggal", "sales", "`tanggal`"),
        ("ix_chicks_tanggal_menetas", "chicks", "`tanggal_menetas`"),
        ("ix_cctv_snapshots_captured_at", "cctv_snapshots", "`captured_at`"),
    ]
    stmts: List[Statement] = []
    for name, table, cols in wanted:
        if not index_exists(conn, name):
            stmts.append((f"CREATE INDEX `{name}` ON `{table}` ({cols})", {}))
    return stmts


def needs_normalize_data(conn: Connection) -> List[Statement]:
    """Samakan nilai varchar lama ke kanonik (BELI->Pembelian, FERTIL->Fertil,
    BREEDING->breeding, NEWBORN->newborn, dst) supaya <option> di frontend dan
    perhitungan dashboard punya satu himpunan nilai."""
    stmts: List[Statement] = []
    for table, column, mapping in NORMALIZATIONS:
        rows = conn.execute(
            # BINARY: collation utf8mb4_0900_ai_ci membuat 'BELI' dan 'beli' satu
            # kelompok, sehingga DISTINCT hanya mengembalikan satu varian dan
            # varian lain tidak tersentuh UPDATE.
            text(f"SELECT DISTINCT BINARY `{column}` AS v FROM `{table}` WHERE `{column}` IS NOT NULL")
        ).fetchall()
        for (value,) in rows:
            if value is None:
                continue
            # BINARY mengembalikan bytes di sisi Python (dialect mysql).
            raw = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value)
            target = mapping.get(raw.strip().lower())
            if target is None:
                logger.warning("Normalisasi: %s.%s = %r tidak dikenal, dibiarkan apa adanya",
                                table, column, raw)
                continue
            if target == raw:
                continue
            stmts.append((
                f"UPDATE `{table}` SET `{column}` = :new WHERE BINARY `{column}` = :old",
                {"new": target, "old": raw},
            ))
    return stmts


def needs_chicks_induk_fk(conn: Connection) -> List[Statement]:
    """FK induk pada chicks — sebelumnya relasi ini bebas, jadi bisa menunjuk
    ID yang sudah tidak ada (induk_anak tidak pernah divalidasi)."""
    stmts: List[Statement] = []
    # Bersihkan dulu kalau ada yang hantu (FK RESTRICT akan menolak).
    orphans = count(
        conn,
        "SELECT COUNT(*) FROM chicks WHERE "
        "(induk_jantan_id IS NOT NULL AND induk_jantan_id NOT IN (SELECT id FROM breeders)) OR "
        "(induk_betina_id IS NOT NULL AND induk_betina_id NOT IN (SELECT id FROM breeders))",
    )
    if orphans:
        stmts.append((
            "UPDATE chicks SET induk_jantan_id = NULL "
            "WHERE induk_jantan_id IS NOT NULL AND induk_jantan_id NOT IN (SELECT id FROM breeders)", {}
        ))
        stmts.append((
            "UPDATE chicks SET induk_betina_id = NULL "
            "WHERE induk_betina_id IS NOT NULL AND induk_betina_id NOT IN (SELECT id FROM breeders)", {}
        ))
    if not fk_exists(conn, "chicks", "induk_jantan_id"):
        stmts.append((
            "ALTER TABLE chicks ADD CONSTRAINT chicks_ibfk_induk_jantan "
            "FOREIGN KEY (induk_jantan_id) REFERENCES breeders (id)", {}))
    if not fk_exists(conn, "chicks", "induk_betina_id"):
        stmts.append((
            "ALTER TABLE chicks ADD CONSTRAINT chicks_ibfk_induk_betina "
            "FOREIGN KEY (induk_betina_id) REFERENCES breeders (id)", {}))
    return stmts


def needs_self_parent_check(conn: Connection) -> List[Statement]:
    """Jaring pengaman terakhir di level DB (API sudah menolak self-parent)."""
    if constraint_exists(conn, "chk_breeders_no_self_parent"):
        return []
    violations = count(
        conn,
        "SELECT COUNT(*) FROM breeders WHERE parent_jantan_id = id OR parent_betina_id = id",
    )
    if violations:
        logger.error("CHECK self-parent tidak dipasang: %d baris breeder sudah menunjuk diri sendiri", violations)
        return []
    return [("ALTER TABLE breeders ADD CONSTRAINT chk_breeders_no_self_parent "
             "CHECK (parent_jantan_id <> id AND parent_betina_id <> id)", {})]


def needs_repair_relations(conn: Connection) -> List[Statement]:
    """Perbaiki data relasi yang sudah tidak konsisten."""
    stmts: List[Statement] = []
    egg_orphans = count(
        conn,
        "SELECT COUNT(*) FROM eggs WHERE "
        "(induk_jantan_id IS NOT NULL AND induk_jantan_id NOT IN (SELECT id FROM breeders)) OR "
        "(induk_betina_id IS NOT NULL AND induk_betina_id NOT IN (SELECT id FROM breeders))",
    )
    if egg_orphans:
        stmts.append((
            "UPDATE eggs SET induk_jantan_id = NULL "
            "WHERE induk_jantan_id IS NOT NULL AND induk_jantan_id NOT IN (SELECT id FROM breeders)", {}))
        stmts.append((
            "UPDATE eggs SET induk_betina_id = NULL "
            "WHERE induk_betina_id IS NOT NULL AND induk_betina_id NOT IN (SELECT id FROM breeders)", {}))

    # Telur adalah sumber kebenaran induk anak (chick menyalin induk saat create).
    mismatch = count(
        conn,
        "SELECT COUNT(*) FROM chicks c JOIN eggs e ON e.id = c.egg_id WHERE "
        "COALESCE(c.induk_jantan_id, '') <> COALESCE(e.induk_jantan_id, '') OR "
        "COALESCE(c.induk_betina_id, '') <> COALESCE(e.induk_betina_id, '')",
    )
    if mismatch:
        stmts.append((
            "UPDATE chicks c JOIN eggs e ON e.id = c.egg_id SET "
            "c.induk_jantan_id = e.induk_jantan_id, c.induk_betina_id = e.induk_betina_id", {}))

    # Gender tidak cocok dengan perannya: TIDAK diubah otomatis (tidak tahu
    # mana yang benar, data atau relasinya) — hanya dilaporkan.
    bad = count(
        conn,
        "SELECT (SELECT COUNT(*) FROM eggs e JOIN breeders b ON b.id = e.induk_jantan_id "
        "  WHERE b.jenis_kelamin <> 'Jantan')"
        " + (SELECT COUNT(*) FROM eggs e JOIN breeders b ON b.id = e.induk_betina_id "
        "  WHERE b.jenis_kelamin <> 'Betina')"
        " + (SELECT COUNT(*) FROM breeders c JOIN breeders b ON b.id = c.parent_jantan_id "
        "  WHERE b.jenis_kelamin <> 'Jantan')"
        " + (SELECT COUNT(*) FROM breeders c JOIN breeders b ON b.id = c.parent_betina_id "
        "  WHERE b.jenis_kelamin <> 'Betina')",
    )
    if bad:
        logger.warning("%d relasi induk memiliki gender tidak cocok — dibiarkan, "
                       "perbaiki manual (API menolak nilai baru yang tidak konsisten)", bad)
    return stmts


@dataclass(frozen=True)
class Step:
    version: int
    name: str
    describe: str
    needs: Needs


STEPS: Sequence[Step] = (
    Step(1, "legacy_schema", "tambah kolom hasil migrasi SQL manual lama", needs_legacy_schema),
    Step(2, "alerts_tipe_rotasi_gagal", "enum alerts.tipe: tambah ROTASI_GAGAL (fix 500 rotasi gagal)", needs_alert_rotasi),
    Step(3, "breeders_status_default", "default breeders.status -> 'breeding'", needs_breeder_status_default),
    Step(4, "indexes", "index untuk ORDER BY/filter yang sering dipakai", needs_indexes),
    Step(5, "normalize_data", "normalisasi nilai lama (BELI, FERTIL, NEWBORN, ...)", needs_normalize_data),
    Step(6, "chicks_induk_fk", "FK induk pada chicks + bersihkan referensi hantu", needs_chicks_induk_fk),
    Step(7, "self_parent_check", "CHECK constraint anti self-parent pada breeders", needs_self_parent_check),
    Step(8, "repair_relations", "sinkronkan induk anak dengan telur + bersihkan induk hantu", needs_repair_relations),
)

_versions = [s.version for s in STEPS]
if len(_versions) != len(set(_versions)):
    raise MigrationError(f"Nomor versi migrasi duplikat: {_versions}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def _ensure_table(conn: Connection) -> None:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INT NOT NULL PRIMARY KEY,"
        "  name VARCHAR(128) NOT NULL,"
        "  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    ))


def applied_versions(conn: Connection) -> set[int]:
    _ensure_table(conn)
    return {int(r[0]) for r in conn.execute(text("SELECT version FROM schema_migrations")).fetchall()}


def migration_status(engine: Engine) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with engine.connect() as conn:
        done = applied_versions(conn)
        for step in sorted(STEPS, key=lambda s: s.version):
            pending = step.version not in done
            planned: List[Statement] = []
            if pending:
                try:
                    planned = step.needs(conn)
                except Exception as exc:  # skema menyimpang, jangan hentikan --status
                    rows.append({"version": step.version, "name": step.name,
                                 "state": "ERROR", "detail": str(exc)})
                    continue
            if not pending:
                state = "applied"
            elif planned:
                state = "pending"
            else:
                state = "clean"  # tidak perlu dijalankan (skema sudah sesuai)
            rows.append({"version": step.version, "name": step.name, "state": state,
                         "detail": "; ".join(sql for sql, _ in planned)[:400]})
    return rows


def run_migrations(engine: Engine, dry_run: bool = False) -> List[Dict[str, object]]:
    """Terapkan semua langkah yang belum jalan. Idempoten dan aman diulang."""
    results: List[Dict[str, object]] = []
    with engine.connect() as conn:
        done = applied_versions(conn)

    for step in sorted(STEPS, key=lambda s: s.version):
        record = {"version": step.version, "name": step.name, "state": "", "detail": ""}
        with engine.begin() as conn:
            if step.version in done:
                record["state"] = "applied"
                results.append(record)
                continue
            try:
                statements = step.needs(conn)
            except Exception as exc:
                raise MigrationError(
                    f"Migrasi {step.version:03d}_{step.name} gagal dicek: {exc}"
                ) from exc

            if not statements:
                # Skema sudah sesuai (umumnya DB baru yang dibuat create_all)
                if not dry_run:
                    conn.execute(text("INSERT INTO schema_migrations (version, name) "
                                      "VALUES (:v, :n)"), {"v": step.version, "n": step.name})
                record["state"] = "clean"
                results.append(record)
                continue

            if dry_run:
                record["state"] = "pending"
                record["detail"] = "\n".join(sql for sql, _ in statements)
                results.append(record)
                continue

            for sql, params in statements:
                try:
                    conn.execute(text(sql), params)
                except Exception as exc:
                    raise MigrationError(
                        f"Migrasi {step.version:03d}_{step.name} gagal: {exc}\nSQL: {sql}"
                    ) from exc
            conn.execute(text("INSERT INTO schema_migrations (version, name) "
                              "VALUES (:v, :n)"), {"v": step.version, "n": step.name})
            record["state"] = "applied"
            record["detail"] = f"{len(statements)} perintah"
            logger.info("Migrasi %03d_%s diterapkan (%s)", step.version, step.name, record["detail"])
        results.append(record)
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Runner migrasi skema MySQL")
    parser.add_argument("--status", action="store_true", help="tampilkan status tiap langkah")
    parser.add_argument("--dry-run", action="store_true", help="tampilkan DDL tanpa menjalankan")
    parser.add_argument("--engine-url", default=None, help="override DATABASE_URL (testing)")
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine
    from .database import DATABASE_URL

    url = args.engine_url or DATABASE_URL
    # Migrasi butuh DDL, jadi jangan pakai connection pool yang menahan koneksi.
    engine = create_engine(url, pool_pre_ping=True)

    # Pastikan tabel sudah ada dulu (sama seperti saat app start) supaya CLI
    # bisa dijalankan sendirian terhadap DB kosong tanpa error "table not found".
    from .models import Base
    Base.metadata.create_all(bind=engine)

    if args.status:
        print(f"{'VER':<4} {'STATUS':<9} NAMA")
        for row in migration_status(engine):
            print(f"{row['version']:<4} {row['state']:<9} {row['name']}"
                  + (f" — {row['detail']}" if row["state"] == "ERROR" and row["detail"] else ""))
        return 0

    try:
        results = run_migrations(engine, dry_run=args.dry_run)
    except MigrationError as exc:
        logger.error("%s", exc)
        print(f"GAGAL: {exc}")
        return 1
    for row in results:
        if row["state"] in ("pending", "clean", "applied"):
            if args.dry_run and row["state"] == "pending":
                print(f"[Akan dijalankan] {row['version']:03d}_{row['name']}")
                print(row["detail"])
            elif not args.dry_run and row["state"] == "applied" and row["detail"]:
                print(f"[Diterapkan] {row['version']:03d}_{row['name']}: {row['detail']}")
    print("Selesai (dry-run)" if args.dry_run else "Semua migrasi selesai")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
