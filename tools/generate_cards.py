import sqlite3
import json
import sys
import os
import argparse

# Add parent directory to path to import project modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai
import prompts
import catalog

def generate_and_insert_card(lang, goal, level, dry_run=True):
    print(f"Generating card for {lang} ({goal}, {level})...")
    
    # 1. Generate Prompt
    system_prompt = prompts.daily_card_system_prompt(lang, goal, level=level)
    
    # 2. Call LLM and validate using the bot's own logic
    try:
        card_dict = ai.ask_card(system_prompt, user_prompt="بساز.")
    except Exception as e:
        print(f"Error generating card: {e}")
        return

    print("\nGenerated Card Data:")
    print(json.dumps(card_dict, indent=2, ensure_ascii=False))
    
    if dry_run:
        print("\nDry run mode: Card NOT inserted.")
        return

    # 3. Securely insert into database
    try:
        conn = sqlite3.connect('hamzaban.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO daily_cards (card_data) VALUES (?)",
            (json.dumps(card_dict, ensure_ascii=False),)
        )
        conn.commit()
        print(f"\nSuccessfully inserted card with ID: {cursor.lastrowid}")
        conn.close()
    except Exception as e:
        print(f"\nDatabase error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and insert a new vocabulary card.")
    parser.add_argument("--lang", required=True, choices=catalog.LANGUAGES.keys(), help="Language code")
    parser.add_argument("--goal", required=True, choices=catalog.GOALS.keys(), help="Goal code")
    parser.add_argument("--level", default="beginner", choices=catalog.LEVELS.keys(), help="Level code")
    parser.add_argument("--dry-run", action="store_true", help="Do not insert into database.")
    
    args = parser.parse_args()
    
    generate_and_insert_card(args.lang, args.goal, args.level, dry_run=args.dry_run)
