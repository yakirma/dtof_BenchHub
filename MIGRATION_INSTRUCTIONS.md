# Database Migration Instructions

## Problem
After updating to the latest code, metrics may not appear on the leaderboard page due to a missing `tag_filter` column in the `leaderboard_metric` table.

## Solution

### On the affected machine:

1. **Stop the application** (if running):
   ```bash
   # Press Ctrl+C in the terminal where the app is running
   ```

2. **Pull the latest code**:
   ```bash
   cd /path/to/BenchHub
   git pull
   ```

3. **Run the migration script**:
   ```bash
   python3 migrate_db.py
   ```

   You should see output like:
   ```
   ============================================================
   BenchHub Database Migration Script
   ============================================================
   Using database: /Users/username/.dtofbenchmarking/database.db
   
   Current columns in leaderboard_metric table:
     - id
     - leaderboard_id
     - global_metric_id
     - arg_mappings
     - target_name
     - pooling_type
     - pooling_percentile
     - sort_direction
   
   ⚠️  Missing 'tag_filter' column detected!
   Adding 'tag_filter' column to 'leaderboard_metric' table...
   ✅ Migration successful: Added 'tag_filter' column.
   ✅ Verification successful: 'tag_filter' column is now present.
   
   Total leaderboard_metric records: X
   
   ✅ Migration completed successfully!
   You can now restart the application.
   ```

4. **Restart the application**:
   ```bash
   python run.py
   ```

5. **Verify metrics are visible**:
   - Open the leaderboard page in your browser
   - Metrics should now be visible

## What the migration does

The migration script:
- Locates your database at `~/.dtofbenchmarking/database.db`
- Checks if the `tag_filter` column exists in the `leaderboard_metric` table
- Adds the column if it's missing
- Verifies the migration was successful
- Shows a summary of your leaderboard metrics

## Troubleshooting

### If you see "Database not found"
Make sure you've run the application at least once to create the database.

### If you see "leaderboard_metric table does not exist"
This means your database schema is very old. Run the application once to create all tables, then run the migration script.

### If metrics still don't appear after migration
1. Check the terminal output when starting the app for any errors
2. Check the browser console (F12) for JavaScript errors
3. Verify the migration completed successfully by running `python3 migrate_db.py` again

## Alternative: Automatic migration on startup

The application now includes automatic migration on startup. If you prefer, you can simply:
1. Pull the latest code
2. Restart the application

The migration will run automatically. However, using the standalone script is recommended as it provides better visibility into what's happening.
