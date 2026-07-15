import sqlite3
import json

def inspect_daily_cards():
    conn = sqlite3.connect('hamzaban.db')
    cursor = conn.cursor()
    
    # Get a sample of card_data
    cursor.execute("SELECT id, card_data FROM daily_cards LIMIT 5;")
    rows = cursor.fetchall()
    
    for row in rows:
        print(f"\n--- Card ID: {row[0]} ---")
        try:
            data = json.loads(row[1])
            # Assuming card_data is a JSON string
            print(f"Phonetic field: {data.get('phonetic', 'N/A')}")
            # Also check if keys like 'ph' exist for mini-format
            print(f"Ph field: {data.get('ph', 'N/A')}")
            print(f"Full Data: {data}")
        except json.JSONDecodeError:
            print("Error: Could not parse JSON in card_data")
            print(f"Raw Data: {row[1]}")
            
    conn.close()

if __name__ == "__main__":
    inspect_daily_cards()
