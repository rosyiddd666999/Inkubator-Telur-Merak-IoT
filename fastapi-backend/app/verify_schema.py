"""Cek drift skema: informasi schema MySQL vs model SQLAlchemy.

Dijalankan sebagai smoke test setelah deploy / migrasi::

    python -m app.verify_schema

Exit code 1 kalau ada MASALAH (skema DB tidak mendukung kode), 0 kalau bersih
(pinggirannya hanya PERINGATAN).

Kenapa perlu: `Base.metadata.create_all()` tidak pernah mengubah tabel yang
sudah ada, jadi perubahan model yang lupa dimigrasikan tetap "jalan" sampai
endpoint itu dipakai user dan meledak 1054/1265. Kasus nyata dari proyek ini:
kolom `alerts.tipe` di database adalah `enum('SUHU','KELEMBAPAN','LAIN')`
sementara model memakai `AlertTipe.ROTASI_GAGAL` — semua INSERT gagal
ERROR 1265 dan endpoint rotasi gagal membalas 500.
"""

from __future__ import annotations

import sys
from typing import List

from sqlalchemy import Boolean, Date, DateTime, Enum, Integer, Numeric, String, Text, text
from sqlalchemy.engine import Connection, Engine


def expected_type(column) -> str:
    t = column.type
    # Enum dulu: Enum juga membawa atribut length sehingga is_instance(String)
    # ikut cocok dan menutupi pemeriksaan member-nya.
    if isinstance(t, Enum):
        return "enum"
    # Text dan Enum sama-sama turunan String — cek sebelum String.
    if isinstance(t, Text):
        return "text"
    if isinstance(t, String):
        return f"varchar({t.length or 255})"
    if isinstance(t, Integer):
        return "int"
    if isinstance(t, Boolean):
        return "tinyint(1)"
    if isinstance(t, Date):
        return "date"
    if isinstance(t, DateTime):
        return "datetime"
    if isinstance(t, Numeric):
        return f"decimal({t.precision or 10},{t.scale or 2})"
    return type(t).__name__.lower()


def normalize_db_type(raw: str) -> str:
    raw = raw.lower().strip()
    if raw.startswith("enum("):
        return "enum"
    return raw


def db_enum_members(conn: Connection, table: str, column: str) -> List[str] | None:
    row = conn.execute(text(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
    ), {"t": table, "c": column}).first()
    if row is None or not str(row[0]).startswith("enum"):
        return None
    inner = str(row[0])[len("enum("):].rstrip(")")
    return [m.strip().strip("'") for m in inner.split(",") if m.strip()]


def has_index(conn: Connection, table: str, columns: List[str]) -> bool:
    """Apakah ada satu index yang kolomnya persis sama (urutan sama)."""
    want = tuple(columns)
    rows = conn.execute(text(
        "SELECT INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t "
        "ORDER BY INDEX_NAME, SEQ_IN_INDEX"
    ), {"t": table}).fetchall()
    grouped: dict[str, List[str]] = {}
    for _idx, _seq, col in rows:
        grouped.setdefault(_idx, []).append(col)
    return any(tuple(cols) == want for cols in grouped.values())


def has_fk(conn: Connection, table: str, column: str, ref_table: str, ref_col: str) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c "
        "AND REFERENCED_TABLE_NAME = :rt AND REFERENCED_COLUMN_NAME = :rc LIMIT 1"
    ), {"t": table, "c": column, "rt": ref_table, "rc": ref_col}).first() is not None


def verify(engine: Engine) -> tuple[List[str], List[str]]:
    from .models import Base

    problems: List[str] = []
    warnings: List[str] = []

    with engine.connect() as conn:
        db_tables = {
            r[0] for r in conn.execute(text(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE()"
            )).fetchall()
        }
        db_columns: dict[str, set] = {}
        for t in sorted(db_tables):
            db_columns[t] = {r[0] for r in conn.execute(text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
            ), {"t": t}).fetchall()}

        for table_name, table in Base.metadata.tables.items():
            if table_name not in db_tables:
                problems.append(f"{table_name}: tabel hilang di database")
                continue

            for column in table.columns:
                col_name = column.name
                if col_name not in db_columns[table_name]:
                    problems.append(f"{table_name}.{col_name}: kolom hilang di database")
                    continue

                # COLUMN_TYPE, bukan DATA_TYPE: yang terakhir tidak membawa
                # panjang ('varchar') sehingga varchar(50) dan varchar(500)
                # dianggap sama.
                db_type = conn.execute(text(
                    "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
                ), {"t": table_name, "c": col_name}).scalar()
                want, got = expected_type(column), normalize_db_type(str(db_type or ""))
                if want != got:
                    problems.append(
                        f"{table_name}.{col_name}: tipe DB '{got}' != model '{want}'")

                db_nullable = conn.execute(text(
                    "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
                ), {"t": table_name, "c": col_name}).scalar() == "YES"
                if db_nullable != bool(column.nullable):
                    # DB menolak NULL tapi model mengizinkan = INSERT bisa gagal
                    # -> masalah. Sebaliknya hanya berbeda rapat, model tidak
                    # pernah menulis NULL ke kolom itu -> peringatan.
                    msg = (f"{table_name}.{col_name}: nullable DB={db_nullable} "
                           f"model={bool(column.nullable)}")
                    if db_nullable and not column.nullable:
                        problems.append(msg)
                    else:
                        warnings.append(msg)

                # Enum: semua nama member model harus ada di DB.
                if isinstance(column.type, Enum):
                    members = db_enum_members(conn, table_name, col_name)
                    if members is None:
                        problems.append(
                            f"{table_name}.{col_name}: model ENUM, bukan ENUM di database")
                    else:
                        missing = [m.name for m in column.type.enums if m not in members]
                        if missing:
                            problems.append(
                                f"{table_name}.{col_name}: enum DB {members} "
                                f"tidak punya {missing} — INSERT akan gagal 1265")

            for fk in table.foreign_keys:
                if not has_fk(conn, table_name, fk.parent.name,
                              fk.column.table.name, fk.column.name):
                    problems.append(
                        f"{table_name}.{fk.parent.name} -> "
                        f"{fk.column.table.name}.{fk.column.name}: FK tidak ada di database")

            # Index yang dideklarasikan model harus ada (unik & index=True).
            for column in table.columns:
                if column.unique or column.index:
                    if not has_index(conn, table_name, [column.name]):
                        warnings.append(
                            f"{table_name}.{column.name}: index model tidak ada di database")

        extra = db_tables - set(Base.metadata.tables)
        for name in sorted(extra):
            if name == "schema_migrations":
                continue
            warnings.append(f"tabel '{name}' ada di database tapi tidak ada di model")

    return problems, warnings


def main(argv=None) -> int:
    from sqlalchemy import create_engine
    from .database import DATABASE_URL
    from .models import Base

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    problems, warnings = verify(engine)

    for msg in warnings:
        print(f"PERINGATAN: {msg}")
    for msg in problems:
        print(f"MASALAH   : {msg}")

    tables = len(Base.metadata.tables)
    status = "SKEMA TIDAK SINKRON" if problems else "SKEMA SINKRON"
    print(f"{status}: {tables} tabel model, {len(problems)} masalah, {len(warnings)} peringatan")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
