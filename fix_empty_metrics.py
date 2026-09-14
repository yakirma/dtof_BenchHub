#!/usr/bin/env python3
"""
Auto-fix empty summary_metrics for leaderboards
This script automatically populates summary_metrics with all available leaderboard_metric IDs
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

def fix_empty_summary_metrics():
    """Fix leaderboards with empty summary_metrics."""
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)
    
    print(f"Using database: {db_path}\n")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all leaderboards
        cursor.execute('SELECT id, name, summary_metrics FROM leaderboard')
        leaderboards = cursor.fetchall()
        
        fixed_count = 0
        skipped_count = 0
        
        for lb_id, lb_name, summary_metrics in leaderboards:
            # Check if summary_metrics is empty
            if not summary_metrics or summary_metrics.strip() == '':
                # Check if there are leaderboard_metric records for this LB
                cursor.execute('SELECT id, target_name FROM leaderboard_metric WHERE leaderboard_id = ? ORDER BY id', (lb_id,))
                metrics = cursor.fetchall()
                
                if metrics:
                    print(f"Fixing LB {lb_id}: {lb_name}")
                    print(f"  Found {len(metrics)} leaderboard_metric(s):")
                    
                    # Build the lm_X list
                    lm_ids = []
                    for metric_id, target_name in metrics:
                        print(f"    - lm_{metric_id} ({target_name})")
                        lm_ids.append(f"lm_{metric_id}")
                    
                    # Update summary_metrics
                    new_summary_metrics = ','.join(lm_ids)
                    cursor.execute('UPDATE leaderboard SET summary_metrics = ? WHERE id = ?', 
                                 (new_summary_metrics, lb_id))
                    
                    print(f"  ✅ Updated summary_metrics to: {new_summary_metrics}")
                    print()
                    fixed_count += 1
                else:
                    print(f"Skipping LB {lb_id}: {lb_name} (no leaderboard_metrics found)")
                    skipped_count += 1
        
        if fixed_count > 0:
            conn.commit()
            print(f"\n✅ Successfully fixed {fixed_count} leaderboard(s)")
        else:
            print(f"\n✅ No leaderboards needed fixing")
        
        if skipped_count > 0:
            print(f"⚠️  Skipped {skipped_count} leaderboard(s) with no metrics")
        
        conn.close()
        
        print("\n" + "=" * 60)
        print("FIX COMPLETE")
        print("=" * 60)
        print("\nYou can now:")
        print("1. Restart the application (if running)")
        print("2. Refresh the leaderboard pages in your browser")
        print("3. Metrics should now be visible!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    print("=" * 60)
    print("BenchHub Summary Metrics Auto-Fix Script")
    print("=" * 60)
    print()
    print("This script will automatically populate empty summary_metrics")
    print("with all available leaderboard_metric IDs for each leaderboard.")
    print()
    
    response = input("Do you want to proceed? (yes/no): ").strip().lower()
    if response in ['yes', 'y']:
        print()
        fix_empty_summary_metrics()
    else:
        print("Aborted.")
        sys.exit(0)
