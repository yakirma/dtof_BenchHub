import sqlite3
import os

user_home = os.path.expanduser("~")
db_path = os.path.join(user_home, ".dtofbenchmarking", "database.db")

def migrate():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Checking for tag_filter column in leaderboard_metric table...")
        cursor.execute("PRAGMA table_info(leaderboard_metric)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'tag_filter' not in columns:
            print("Adding tag_filter column to leaderboard_metric table...")
            cursor.execute("ALTER TABLE leaderboard_metric ADD COLUMN tag_filter TEXT")
            conn.commit()
            print("Migration successful.")
        else:
            print("tag_filter column already exists.")
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
