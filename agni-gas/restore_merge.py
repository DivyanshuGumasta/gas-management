"""Safe, additive merge of an Agni SQLite snapshot into the live database.

Restore accepts a complete later snapshot from the same database lineage. It
never deletes records. When the uploaded snapshot is newer (a superset by
primary-key identity), it fills missing rows and updates overlapping rows to
the snapshot's values. Older snapshots are harmless no-ops. Diverged copies
are rejected because merging their stock and ledger snapshots would be unsafe.
"""
from __future__ import annotations

import os
import sqlite3


class RestoreMergeError(ValueError):
    """Raised when a backup cannot be merged without risking data integrity."""


REQUIRED_TABLES = {
    "settings", "counters", "customers", "sales", "payments",
    "purchases", "suppliers", "cylinder_types",
}
NON_BUSINESS_TABLES = {"settings", "counters"}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _tables(conn: sqlite3.Connection, schema: str) -> set[str]:
    rows = conn.execute(
        f"SELECT name FROM {_quote(schema)}.sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[tuple]:
    return conn.execute(
        f"PRAGMA {_quote(schema)}.table_info({_quote(table)})"
    ).fetchall()


def _pk_columns(info: list[tuple]) -> list[str]:
    # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
    return [str(row[1]) for row in sorted(info, key=lambda r: int(r[5]) if r[5] else 10**9) if row[5]]


def _key_set(conn: sqlite3.Connection, schema: str, table: str, pk: list[str]) -> set[tuple]:
    fields = ",".join(_quote(c) for c in pk)
    return {tuple(row) for row in conn.execute(
        f"SELECT {fields} FROM {_quote(schema)}.{_quote(table)}"
    ).fetchall()}


def _table_count(conn: sqlite3.Connection, schema: str, table: str) -> int:
    return int(conn.execute(
        f"SELECT COUNT(*) FROM {_quote(schema)}.{_quote(table)}"
    ).fetchone()[0])


def _merge_table(
    conn: sqlite3.Connection,
    table: str,
    source_info: list[tuple],
    target_info: list[tuple],
) -> tuple[int, int]:
    """Merge one table; return (inserted, updated) row counts."""
    source_columns = {str(row[1]) for row in source_info}
    target_columns = {str(row[1]) for row in target_info}
    shared = [str(row[1]) for row in target_info if str(row[1]) in source_columns]
    if not shared:
        return 0, 0

    # Do not silently create malformed rows when a required target column did
    # not exist in an older backup and has no DEFAULT value.
    for col in target_info:
        name, not_null, default, is_pk = str(col[1]), bool(col[3]), col[4], bool(col[5])
        if name not in source_columns and not_null and default is None and not is_pk:
            raise RestoreMergeError(
                f"The backup is missing required column '{name}' in table '{table}'. "
                "Use a backup made with the same or a newer application version."
            )

    pk = _pk_columns(target_info)
    if not pk:
        # All Agni business tables have a primary key. Refuse an unknown
        # future table without one instead of risking duplicate append rows.
        raise RestoreMergeError(
            f"Table '{table}' has no primary key, so it cannot be merged safely."
        )
    if any(c not in source_columns for c in pk):
        raise RestoreMergeError(
            f"The backup has an incompatible primary key for table '{table}'."
        )

    fields = ",".join(_quote(c) for c in shared)
    placeholders = ",".join("?" for _ in shared)
    pk_fields = ",".join(_quote(c) for c in pk)
    non_pk = [c for c in shared if c not in pk]
    if non_pk:
        updates = ",".join(f"{_quote(c)}=excluded.{_quote(c)}" for c in non_pk)
        conflict = f"ON CONFLICT ({pk_fields}) DO UPDATE SET {updates}"
    else:
        conflict = f"ON CONFLICT ({pk_fields}) DO NOTHING"
    insert_sql = (
        f"INSERT INTO main.{_quote(table)} ({fields}) VALUES ({placeholders}) {conflict}"
    )
    source_sql = f"SELECT {fields} FROM restore_source.{_quote(table)}"
    select_sql = f"SELECT {pk_fields} FROM main.{_quote(table)} WHERE " + " AND ".join(
        f"{_quote(c)}=?" for c in pk
    )

    inserted = updated = 0
    # Iterate in bounded batches so even a large supplier bill BLOB does not
    # require loading the entire database into Python memory.
    source_cursor = conn.execute(source_sql)
    while True:
        batch = source_cursor.fetchmany(250)
        if not batch:
            break
        for row in batch:
            values = tuple(row)
            row_values = dict(zip(shared, values))
            key = tuple(row_values[c] for c in pk)
            existed = conn.execute(select_sql, key).fetchone() is not None
            conn.execute(insert_sql, values)
            if existed:
                updated += 1
            else:
                inserted += 1
    return inserted, updated


def merge_snapshot_into_database(
    destination: sqlite3.Connection,
    backup_path: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Merge a complete newer Agni snapshot into ``destination``.

    Older snapshots are no-ops. If each database contains different rows that
    are absent from the other, restore is rejected instead of guessing which
    stock, balance, invoice or settings snapshot should win.
    """
    backup_path = os.path.abspath(backup_path)
    if not os.path.isfile(backup_path):
        raise RestoreMergeError("The selected backup file could not be found.")

    attached = False
    in_transaction = False
    try:
        destination.execute("ATTACH DATABASE ? AS restore_source", (backup_path,))
        attached = True
        source_tables = _tables(destination, "restore_source")
        target_tables = _tables(destination, "main")
        missing = REQUIRED_TABLES - source_tables
        if missing:
            raise RestoreMergeError(
                "This does not appear to be a complete Agni Gas backup. "
                "Missing tables: " + ", ".join(sorted(missing))
            )
        missing_current = target_tables - source_tables
        extra_source = source_tables - target_tables
        if missing_current or extra_source:
            details = []
            if missing_current:
                details.append("missing tables: " + ", ".join(sorted(missing_current)))
            if extra_source:
                details.append("unsupported tables: " + ", ".join(sorted(extra_source)))
            raise RestoreMergeError(
                "This backup was created with an older or newer incompatible database structure (" +
                "; ".join(details) + "). Use a backup from the same application version."
            )

        common = sorted(source_tables & target_tables)
        comparison_tables = [t for t in common if t not in NON_BUSINESS_TABLES]
        if not comparison_tables:
            raise RestoreMergeError("The backup does not contain compatible Agni business tables.")

        source_is_superset = True
        target_is_superset = True
        source_extra_rows = 0
        overlapping_rows_differ = False
        for table in comparison_tables:
            source_info = _columns(destination, "restore_source", table)
            target_info = _columns(destination, "main", table)
            source_pk = _pk_columns(source_info)
            target_pk = _pk_columns(target_info)
            source_columns = {str(row[1]) for row in source_info}
            target_columns = {str(row[1]) for row in target_info}
            if source_columns != target_columns:
                raise RestoreMergeError(
                    f"The column structure of table '{table}' differs. "
                    "Use a backup made with the same application version."
                )
            if not source_pk or source_pk != target_pk:
                raise RestoreMergeError(
                    f"The primary-key structure of table '{table}' differs. "
                    "Use a backup made with the same application version."
                )
            source_keys = _key_set(destination, "restore_source", table, source_pk)
            target_keys = _key_set(destination, "main", table, target_pk)
            if not target_keys.issubset(source_keys):
                source_is_superset = False
            if not source_keys.issubset(target_keys):
                target_is_superset = False
                source_extra_rows += len(source_keys - target_keys)
            if source_keys == target_keys:
                shared_cols = [str(col[1]) for col in target_info if str(col[1]) in {str(x[1]) for x in source_info}]
                non_pk_cols = [c for c in shared_cols if c not in target_pk]
                if non_pk_cols:
                    join = " AND ".join(f"t.{_quote(c)}=s.{_quote(c)}" for c in target_pk)
                    differences = " OR ".join(f"t.{_quote(c)} IS NOT s.{_quote(c)}" for c in non_pk_cols)
                    diff_sql = (
                        f"SELECT 1 FROM main.{_quote(table)} AS t "
                        f"JOIN restore_source.{_quote(table)} AS s ON {join} "
                        f"WHERE {differences} LIMIT 1"
                    )
                    if destination.execute(diff_sql).fetchone():
                        overlapping_rows_differ = True

        if target_is_superset and source_is_superset:
            if overlapping_rows_differ:
                raise RestoreMergeError(
                    "The backup and current database have the same record IDs but different values. "
                    "There are no additional records to merge, so the app cannot safely decide "
                    "which copy is newer. No changes were applied."
                )
            return {
                "status": "already_current", "inserted": 0, "updated": 0,
                "tables": len(comparison_tables),
                "message": "This backup contains no additional records; the databases already match.",
            }
        if target_is_superset and not source_is_superset:
            return {
                "status": "older_backup", "inserted": 0, "updated": 0,
                "tables": len(comparison_tables),
                "message": "The selected backup is older than the current database. No records were changed.",
            }
        if not source_is_superset:
            raise RestoreMergeError(
                "This backup and the current database contain different sets of records. "
                "To prevent duplicate or inconsistent stock and ledger entries, they cannot be "
                "merged automatically. Select a complete backup that contains all records "
                "currently in this database."
            )

        if source_extra_rows <= 0:
            return {
                "status": "already_current", "inserted": 0, "updated": 0,
                "tables": len(comparison_tables),
                "message": "This backup contains no additional records; the databases already match.",
            }
        if dry_run:
            return {
                "status": "merge_available", "inserted": source_extra_rows,
                "updated": 0, "tables": len(comparison_tables),
                "message": "A later full backup is available to merge.",
            }

        destination.execute("PRAGMA defer_foreign_keys=ON")
        destination.execute("BEGIN IMMEDIATE")
        in_transaction = True
        inserted_total = updated_total = 0
        for table in common:
            if table == "settings":
                # Restore missing business settings but keep the current
                # machine's backup directory, cadence and retention policy.
                rows = destination.execute(
                    "SELECT key,value FROM restore_source.settings WHERE key NOT LIKE 'backup.%'"
                ).fetchall()
                for key, value in rows:
                    cur = destination.execute(
                        "INSERT OR IGNORE INTO main.settings(key,value) VALUES(?,?)", (key, value)
                    )
                    inserted_total += max(0, cur.rowcount)
                continue
            if table == "counters":
                rows = destination.execute("SELECT name,value FROM restore_source.counters").fetchall()
                for name, value in rows:
                    destination.execute(
                        "INSERT INTO main.counters(name,value) VALUES(?,?) "
                        "ON CONFLICT(name) DO UPDATE SET value=MAX(COALESCE(main.counters.value,0),COALESCE(excluded.value,0))",
                        (name, value),
                    )
                continue

            src_info = _columns(destination, "restore_source", table)
            dst_info = _columns(destination, "main", table)
            added, changed = _merge_table(destination, table, src_info, dst_info)
            inserted_total += added
            updated_total += changed

        violations = destination.execute("PRAGMA main.foreign_key_check").fetchmany(10)
        if violations:
            raise RestoreMergeError(
                "The selected backup contains records with missing related records. "
                "No changes were applied."
            )
        destination.commit()
        in_transaction = False
        return {
            "status": "merged", "inserted": inserted_total, "updated": updated_total,
            "tables": len(comparison_tables),
            "message": f"Restored {inserted_total:,} missing rows and refreshed {updated_total:,} existing rows.",
        }
    except RestoreMergeError:
        if in_transaction:
            destination.rollback()
        raise
    except sqlite3.Error as exc:
        if in_transaction:
            destination.rollback()
        raise RestoreMergeError(
            "The backup could not be merged safely. No changes were applied. "
            f"SQLite reported: {exc}"
        ) from exc
    finally:
        if attached:
            if in_transaction:
                try:
                    destination.rollback()
                except sqlite3.Error:
                    pass
            try:
                destination.execute("DETACH DATABASE restore_source")
            except sqlite3.Error:
                pass
