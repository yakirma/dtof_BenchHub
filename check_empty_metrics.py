#!/usr/bin/env python3
"""
Check and fix empty summary_metrics for leaderboards
"""

import sqlite3
import os

db_path = os.path.expanduser('~/.dtofbenchmarking/database.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Checking leaderboards with empty summary_metrics...\n")

# Get all leaderboards
cursor.execute('SELECT id, name, summary_metrics FROM leaderboard')
leaderboards = cursor.fetchall()

for lb_id, lb_name, summary_metrics in leaderboards:
    # Check if summary_metrics is empty
    if not summary_metrics or summary_metrics.strip() == '':
        # Check if there are leaderboard_metric records for this LB
        cursor.execute('SELECT id, target_name FROM leaderboard_metric WHERE leaderboard_id = ?', (lb_id,))
        metrics = cursor.fetchall()
        
        if metrics:
            print(f"LB {lb_id}: {lb_name}")
            print(f"  Current summary_metrics: EMPTY")
            print(f"  Available leaderboard_metrics ({len(metrics)}):")
            
            # Build the lm_X list
            lm_ids = []
            for metric_id, target_name in metrics:
                print(f"    - lm_{metric_id} ({target_name})")
                lm_ids.append(f"lm_{metric_id}")
            
            # Suggest fix
            suggested = ','.join(lm_ids)
            print(f"  Suggested summary_metrics: {suggested}")
            print()

print("\nTo fix this, you can either:")
print("1. Use the web UI to select metrics on each leaderboard's settings")
print("2. Run the auto-fix script (coming next)")

conn.close()
