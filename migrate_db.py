#!/usr/bin/env python3
"""
Database Migration Script for BenchHub
This script adds the tag_filter column to the leaderboard_metric table if it doesn't exist.
"""

import sqlite3
import os
import sys

def get_db_path():
    """Get the database path from the app configuration."""
    user_home = os.path.expanduser("~")
    dtof_data_dir = os.path.join(user_home, ".dtofbenchmarking")
    db_path = os.path.join(dtof_data_dir, 'database.db')
    return db_path

def check_and_migrate():
    """Check database schema and apply migrations if needed."""
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        print("Please ensure the application has been run at least once to create the database.")
        sys.exit(1)
    
    print(f"Using database: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if leaderboard_metric table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leaderboard_metric'")
        if not cursor.fetchone():
            print("ERROR: leaderboard_metric table does not exist!")
            print("Please run the application first to create the initial schema.")
            conn.close()
            sys.exit(1)
        
        # Check current columns in leaderboard_metric table
        cursor.execute("PRAGMA table_info(leaderboard_metric)")
        columns = [row[1] for row in cursor.fetchall()]
        
        print(f"\nCurrent columns in leaderboard_metric table:")
        for col in columns:
            print(f"  - {col}")
        
        # Check if tag_filter column exists
        if 'tag_filter' not in columns:
            print("\n⚠️  Missing 'tag_filter' column detected!")
            print("Adding 'tag_filter' column to 'leaderboard_metric' table...")
            
            try:
                cursor.execute("ALTER TABLE leaderboard_metric ADD COLUMN tag_filter TEXT DEFAULT NULL")
                conn.commit()
                print("✅ Migration successful: Added 'tag_filter' column.")
                
                # Verify the column was added
                cursor.execute("PRAGMA table_info(leaderboard_metric)")
                new_columns = [row[1] for row in cursor.fetchall()]
                
                if 'tag_filter' in new_columns:
                    print("✅ Verification successful: 'tag_filter' column is now present.")
                else:
                    print("❌ Verification failed: 'tag_filter' column was not added.")
                    conn.close()
                    sys.exit(1)
                    
            except Exception as e:
                print(f"❌ Migration error: {e}")
                conn.rollback()
                conn.close()
                sys.exit(1)
        else:
            print("\n✅ 'tag_filter' column already exists. No migration needed.")
        
        # Check and add git_author to dataset table
        cursor.execute("PRAGMA table_info(dataset)")
        dataset_columns = [row[1] for row in cursor.fetchall()]
        
        if 'git_author' not in dataset_columns:
            print("\n⚠️  Missing 'git_author' column in dataset table!")
            print("Adding 'git_author' column to 'dataset' table...")
            try:
                cursor.execute("ALTER TABLE dataset ADD COLUMN git_author VARCHAR(100) DEFAULT NULL")
                conn.commit()
                print("✅ Migration successful: Added 'git_author' column to dataset.")
            except Exception as e:
                print(f"❌ Migration error (dataset.git_author): {e}")
                conn.rollback()
        else:
            print("\n✅ 'git_author' column already exists in dataset table.")
        
        # Check and add git_author to submission table
        cursor.execute("PRAGMA table_info(submission)")
        submission_columns = [row[1] for row in cursor.fetchall()]
        
        if 'git_author' not in submission_columns:
            print("\n⚠️  Missing 'git_author' column in submission table!")
            print("Adding 'git_author' column to 'submission' table...")
            try:
                cursor.execute("ALTER TABLE submission ADD COLUMN git_author VARCHAR(100) DEFAULT NULL")
                conn.commit()
                print("✅ Migration successful: Added 'git_author' column to submission.")
            except Exception as e:
                print(f"❌ Migration error (submission.git_author): {e}")
                conn.rollback()
        else:
            print("\n✅ 'git_author' column already exists in submission table.")
        
        # Show summary
        cursor.execute("SELECT COUNT(*) FROM leaderboard_metric")
        count = cursor.fetchone()[0]
        print(f"\nTotal leaderboard_metric records: {count}")
        
        if count > 0:
            cursor.execute("SELECT id, leaderboard_id, target_name FROM leaderboard_metric LIMIT 5")
            print("\nFirst 5 leaderboard metrics:")
            for row in cursor.fetchall():
                print(f"  ID: {row[0]}, LB_ID: {row[1]}, Target: {row[2]}")
        
        conn.close()
        print("\n✅ Migration completed successfully!")
        print("You can now restart the application.")
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    print("=" * 60)
    print("BenchHub Database Migration Script")
    print("=" * 60)
    check_and_migrate()
