#!/usr/bin/env python3
"""
Diagnostic Script for BenchHub Metrics Issue
This script checks why metrics aren't appearing on the leaderboard page.
"""

import sqlite3
import os
import sys
import json

def get_db_path():
    """Get the database path from the app configuration."""
    user_home = os.path.expanduser("~")
    dtof_data_dir = os.path.join(user_home, ".dtofbenchmarking")
    db_path = os.path.join(dtof_data_dir, 'database.db')
    return db_path

def diagnose():
    """Run diagnostics on the database."""
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)
    
    print(f"Using database: {db_path}\n")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. Check leaderboard_metric table structure
        print("=" * 60)
        print("1. LEADERBOARD_METRIC TABLE STRUCTURE")
        print("=" * 60)
        cursor.execute("PRAGMA table_info(leaderboard_metric)")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col[1]:20s} {col[2]:10s} {'NOT NULL' if col[3] else 'NULL':10s} Default: {col[4]}")
        
        # 2. Check leaderboard_metric records
        print("\n" + "=" * 60)
        print("2. LEADERBOARD_METRIC RECORDS")
        print("=" * 60)
        cursor.execute("SELECT COUNT(*) FROM leaderboard_metric")
        count = cursor.fetchone()[0]
        print(f"Total records: {count}\n")
        
        if count > 0:
            cursor.execute("""
                SELECT id, leaderboard_id, global_metric_id, target_name, tag_filter 
                FROM leaderboard_metric 
                ORDER BY leaderboard_id, id
            """)
            print(f"{'ID':<5} {'LB_ID':<7} {'GM_ID':<7} {'Target Name':<25} {'Tag Filter':<20}")
            print("-" * 70)
            for row in cursor.fetchall():
                tag_filter = row[4] if row[4] else 'NULL'
                print(f"{row[0]:<5} {row[1]:<7} {row[2]:<7} {str(row[3]):<25} {tag_filter:<20}")
        
        # 3. Check leaderboards
        print("\n" + "=" * 60)
        print("3. LEADERBOARDS")
        print("=" * 60)
        cursor.execute("SELECT id, name, summary_metrics FROM leaderboard")
        leaderboards = cursor.fetchall()
        
        for lb in leaderboards:
            print(f"\nLeaderboard ID: {lb[0]}")
            print(f"Name: {lb[1]}")
            print(f"Summary Metrics: {lb[2]}")
            
            # Check if summary_metrics references leaderboard_metrics
            if lb[2]:
                metrics = [m.strip() for m in lb[2].split(',') if m.strip()]
                print(f"  Parsed metrics ({len(metrics)}): {metrics}")
                
                # Check which ones are lm_* references
                lm_refs = [m for m in metrics if m.startswith('lm_')]
                if lm_refs:
                    print(f"  LeaderboardMetric references: {lm_refs}")
                    
                    # Verify these exist
                    for lm_ref in lm_refs:
                        lm_id = lm_ref.replace('lm_', '')
                        cursor.execute("SELECT id, target_name FROM leaderboard_metric WHERE id = ?", (lm_id,))
                        result = cursor.fetchone()
                        if result:
                            print(f"    ✅ {lm_ref} -> {result[1]}")
                        else:
                            print(f"    ❌ {lm_ref} -> NOT FOUND!")
        
        # 4. Check global_metric table
        print("\n" + "=" * 60)
        print("4. GLOBAL_METRICS")
        print("=" * 60)
        cursor.execute("SELECT COUNT(*) FROM global_metric")
        gm_count = cursor.fetchone()[0]
        print(f"Total global metrics: {gm_count}\n")
        
        if gm_count > 0:
            cursor.execute("SELECT id, name, label FROM global_metric")
            print(f"{'ID':<5} {'Name':<30} {'Label':<30}")
            print("-" * 70)
            for row in cursor.fetchall():
                label = row[2] if row[2] else 'NULL'
                print(f"{row[0]:<5} {row[1]:<30} {label:<30}")
        
        # 5. Check submissions and custom_fields
        print("\n" + "=" * 60)
        print("5. SUBMISSIONS AND CUSTOM FIELDS")
        print("=" * 60)
        cursor.execute("""
            SELECT s.id, s.name, s.leaderboard_id, COUNT(cf.id) as custom_field_count
            FROM submission s
            LEFT JOIN custom_field cf ON cf.submission_id = s.id AND cf.field_type IN ('metric', 'scalar')
            GROUP BY s.id
            ORDER BY s.leaderboard_id, s.id
            LIMIT 10
        """)
        print(f"{'Sub ID':<7} {'LB_ID':<7} {'Name':<30} {'Custom Fields':<15}")
        print("-" * 70)
        for row in cursor.fetchall():
            print(f"{row[0]:<7} {row[2]:<7} {row[1]:<30} {row[3]:<15}")
        
        # 6. Sample custom fields from submissions
        print("\n" + "=" * 60)
        print("6. SAMPLE CUSTOM FIELDS (metrics/scalars)")
        print("=" * 60)
        cursor.execute("""
            SELECT DISTINCT name, field_type, submission_id
            FROM custom_field
            WHERE field_type IN ('metric', 'scalar') AND submission_id IS NOT NULL
            ORDER BY name
            LIMIT 20
        """)
        print(f"{'Field Name':<30} {'Type':<10} {'Sub ID':<10}")
        print("-" * 70)
        for row in cursor.fetchall():
            print(f"{row[0]:<30} {row[1]:<10} {row[2]:<10}")
        
        conn.close()
        
        print("\n" + "=" * 60)
        print("DIAGNOSIS COMPLETE")
        print("=" * 60)
        print("\nLook for:")
        print("  1. Are there leaderboard_metric records?")
        print("  2. Does summary_metrics contain 'lm_X' references?")
        print("  3. Do those lm_X IDs exist in leaderboard_metric table?")
        print("  4. Are there custom_field records with field_type='metric'?")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    print("=" * 60)
    print("BenchHub Metrics Diagnostic Script")
    print("=" * 60)
    print()
    diagnose()
