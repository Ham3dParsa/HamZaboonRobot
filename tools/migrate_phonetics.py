import sqlite3
import json
import os
import shutil
import argparse
import logging
import sys

log = logging.getLogger("migrate_phonetics")


def normalize_phonetic_str(phonetic_str: str) -> dict:
    lines = phonetic_str.strip().splitlines()
    if len(lines) >= 3:
        return {
            "ipa": lines[0].strip(),
            "persian": lines[2].strip()
        }
    elif len(lines) == 2:
        return {
            "ipa": lines[0].strip(),
            "persian": lines[1].strip()
        }
    return {"ipa": phonetic_str, "persian": ""}


def migrate(db_path: str, dry_run: bool = False) -> bool:
    backup_path = db_path + ".bak"

    if not os.path.isfile(db_path):
        log.error("Database file not found: %s", db_path)
        return False

    try:
        shutil.copyfile(db_path, backup_path)
        log.info("Backup created at %s", backup_path)
    except (OSError, shutil.Error) as e:
        log.error("Failed to create backup: %s", e)
        return False

    if not os.path.isfile(backup_path):
        log.error("Backup verification failed: %s not found", backup_path)
        return False

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        log.error("Failed to connect to database: %s", e)
        return False

    total_migrated = 0
    total_errors = 0

    for table in ["daily_cards", "saved_words"]:
        log.info("Migrating table: %s", table)
        try:
            cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table} WHERE card_data IS NOT NULL")
            total_rows = cursor.fetchone()["cnt"]
        except sqlite3.Error as e:
            log.error("Failed to count rows in %s: %s", table, e)
            conn.close()
            return False

        if total_rows == 0:
            log.info("No rows to migrate in %s", table)
            continue

        log.info("Found %d rows with card_data in %s", total_rows, table)

        try:
            cursor = conn.execute(f"SELECT id, card_data FROM {table} WHERE card_data IS NOT NULL")
            rows = cursor.fetchall()
        except sqlite3.Error as e:
            log.error("Failed to query %s: %s", table, e)
            conn.close()
            return False

        count = 0
        errors = 0
        for idx, row in enumerate(rows, 1):
            if idx % 100 == 0 or idx == len(rows):
                log.info("Processing %s: %d/%d rows", table, idx, len(rows))

            card_id = row["id"]
            try:
                data = json.loads(row["card_data"])
            except json.JSONDecodeError as e:
                log.warning("Invalid JSON in %s id=%d: %s", table, card_id, e)
                errors += 1
                continue

            phonetic = data.get("phonetic")
            if isinstance(phonetic, dict):
                if "latin" in phonetic:
                    data["phonetic"] = {
                        "ipa": phonetic.get("ipa", ""),
                        "persian": phonetic.get("persian", "")
                    }
                    if not dry_run:
                        try:
                            conn.execute(
                                f"UPDATE {table} SET card_data=? WHERE id=?",
                                (json.dumps(data, ensure_ascii=False), card_id)
                            )
                        except sqlite3.Error as e:
                            log.error("Failed to update %s id=%d: %s", table, card_id, e)
                            errors += 1
                            continue
                    count += 1
                continue

            if phonetic:
                data["phonetic"] = normalize_phonetic_str(str(phonetic))
                if not dry_run:
                    try:
                        conn.execute(
                            f"UPDATE {table} SET card_data=? WHERE id=?",
                            (json.dumps(data, ensure_ascii=False), card_id)
                        )
                    except sqlite3.Error as e:
                        log.error("Failed to update %s id=%d: %s", table, card_id, e)
                        errors += 1
                        continue
                count += 1
        if not dry_run:
            conn.commit()
        log.info("Migrated %d records in %s (%d errors)", count, table, errors)
        total_migrated += count
        total_errors += errors

    conn.close()
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Migrate phonetic data: strip Latin from stored cards"
    )
    parser.add_argument(
        "--db-path", default="hamzaban.db",
        help="Path to the SQLite database (default: hamzaban.db)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be migrated without making changes"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug-level logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.dry_run:
        log.info("DRY RUN: no changes will be made")

    success = migrate(db_path=args.db_path, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
