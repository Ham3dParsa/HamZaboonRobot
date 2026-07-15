import sqlite3

def inspect_db():
    conn = sqlite3.connect('hamzaban.db')
    cursor = conn.cursor()
    
    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print(f"Tables: {tables}")
    
    # Inspect schema for each table
    for table in tables:
        table_name = table[0]
        print(f"\nSchema for {table_name}:")
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()
        for col in columns:
            print(col)
            
    conn.close()

if __name__ == "__main__":
    inspect_db()
