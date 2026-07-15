import sqlite3
import json
import os
import shutil

def normalize_phonetic_str(phonetic_str: str) -> dict:
    lines = phonetic_str.strip().splitlines()
    if len(lines) >= 3:
        return {
            "ipa": lines[0].strip(),
            "latin": lines[1].strip(),
            "persian": lines[2].strip()
        }
    return {"ipa": phonetic_str, "latin": "", "persian": ""}

def migrate():
    db_path = 'hamzaban.db'
    backup_path = 'hamzaban.db.bak'
    
    # Backup
    shutil.copyfile(db_path, backup_path)
    print(f"Backup created at {backup_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    for table in ["daily_cards", "saved_words"]:
        print(f"Migrating table: {table}")
        cursor = conn.execute(f"SELECT id, card_data FROM {table} WHERE card_data IS NOT NULL")
        rows = cursor.fetchall()
        
        count = 0
        for row in rows:
            card_id = row["id"]
            try:
                data = json.loads(row["card_data"])
            except json.JSONDecodeError:
                continue
            
            # Skip if already normalized
            phonetic = data.get("phonetic")
            if isinstance(phonetic, dict):
                continue
            
            # Normalize
            if phonetic:
                data["phonetic"] = normalize_phonetic_str(str(phonetic))
                
                # Update
                conn.execute(
                    f"UPDATE {table} SET card_data=? WHERE id=?",
                    (json.dumps(data, ensure_ascii=False), card_id)
                )
                count += 1
        conn.commit()
        print(f"Migrated {count} records in {table}")
        
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
