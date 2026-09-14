#!/usr/bin/env python3
"""
Backfill Git Author Information from Git Commits
This script uses the git commit hash stored in the database to extract the author name
"""

import sqlite3
import os
import sys
import subprocess

def get_db_path():
    """Get the database path from the app configuration."""
    user_home = os.path.expanduser("~")
    dtof_data_dir = os.path.join(user_home, ".dtofbenchmarking")
    db_path = os.path.join(dtof_data_dir, 'database.db')
    return db_path

def get_author_from_commit(commit_hash, repo_path=None):
    """
    Get the author name from a git commit hash.
    Tries local repository first, then fetches from remote if needed.
    
    Args:
        commit_hash: The git commit hash
        repo_path: Optional path to the git repository. If None, uses current directory.
    
    Returns:
        Author name or None if not found
    """
    if not commit_hash or commit_hash == 'N/A':
        return None
    
    try:
        # First, try to get author from local commit
        cmd = ['git', 'show', '-s', '--format=%an', commit_hash]
        if repo_path:
            cmd = ['git', '-C', repo_path, 'show', '-s', '--format=%an', commit_hash]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            author = result.stdout.strip()
            if author:
                return author
        
        # If not found locally, try fetching from remote
        print(f"    Commit {commit_hash[:7]} not found locally, fetching from remote...")
        
        fetch_cmd = ['git', 'fetch', '--all']
        if repo_path:
            fetch_cmd = ['git', '-C', repo_path, 'fetch', '--all']
        
        fetch_result = subprocess.run(fetch_cmd, capture_output=True, text=True, timeout=30)
        
        if fetch_result.returncode == 0:
            # Try again after fetching
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                author = result.stdout.strip()
                if author:
                    return author
        
        return None
    except Exception as e:
        return None


def backfill_authors_from_git(repo_path=None):
    """Backfill git author information using git commands."""
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)
    
    print(f"Using database: {db_path}")
    if repo_path:
        print(f"Using git repository: {repo_path}")
    else:
        print(f"Using current directory as git repository")
    print()
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Process Datasets
        print("=" * 60)
        print("BACKFILLING DATASET AUTHORS FROM GIT COMMITS")
        print("=" * 60)
        
        cursor.execute("SELECT id, name, git_commit, git_author FROM dataset WHERE git_commit IS NOT NULL AND git_commit != ''")
        datasets = cursor.fetchall()
        
        dataset_updated = 0
        dataset_already_set = 0
        dataset_not_found = 0
        
        for dataset_id, dataset_name, git_commit, current_author in datasets:
            if current_author:
                print(f"⏭️  Dataset '{dataset_name}': Already has author '{current_author}'")
                dataset_already_set += 1
                continue
            
            author = get_author_from_commit(git_commit, repo_path)
            
            if author:
                cursor.execute("UPDATE dataset SET git_author = ? WHERE id = ?", (author, dataset_id))
                print(f"✅ Dataset '{dataset_name}' (commit {git_commit[:7]}): {author}")
                dataset_updated += 1
            else:
                print(f"❌ Dataset '{dataset_name}' (commit {git_commit[:7]}): Could not find author")
                dataset_not_found += 1
        
        print(f"\nDataset Summary:")
        print(f"  Updated: {dataset_updated}")
        print(f"  Already set: {dataset_already_set}")
        print(f"  Not found in git: {dataset_not_found}")
        
        # Process Submissions
        print("\n" + "=" * 60)
        print("BACKFILLING SUBMISSION AUTHORS FROM GIT COMMITS")
        print("=" * 60)
        
        cursor.execute("SELECT id, name, git_commit, git_author FROM submission WHERE git_commit IS NOT NULL AND git_commit != ''")
        submissions = cursor.fetchall()
        
        submission_updated = 0
        submission_already_set = 0
        submission_not_found = 0
        
        for submission_id, submission_name, git_commit, current_author in submissions:
            if current_author:
                print(f"⏭️  Submission '{submission_name}': Already has author '{current_author}'")
                submission_already_set += 1
                continue
            
            author = get_author_from_commit(git_commit, repo_path)
            
            if author:
                cursor.execute("UPDATE submission SET git_author = ? WHERE id = ?", (author, submission_id))
                print(f"✅ Submission '{submission_name}' (ID: {submission_id}, commit {git_commit[:7]}): {author}")
                submission_updated += 1
            else:
                print(f"❌ Submission '{submission_name}' (ID: {submission_id}, commit {git_commit[:7]}): Could not find author")
                submission_not_found += 1
        
        print(f"\nSubmission Summary:")
        print(f"  Updated: {submission_updated}")
        print(f"  Already set: {submission_already_set}")
        print(f"  Not found in git: {submission_not_found}")
        
        # Commit changes
        if dataset_updated > 0 or submission_updated > 0:
            conn.commit()
            print("\n" + "=" * 60)
            print("BACKFILL COMPLETE")
            print("=" * 60)
            print(f"✅ Successfully updated {dataset_updated} dataset(s) and {submission_updated} submission(s)")
            print("\nYou can now refresh your browser to see the author information!")
        else:
            print("\n" + "=" * 60)
            print("NO UPDATES NEEDED")
            print("=" * 60)
            if dataset_already_set > 0 or submission_already_set > 0:
                print("All records already have author information.")
            else:
                print("No git commits found in database or commits not accessible in git repository.")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    print("=" * 60)
    print("BenchHub Git Author Backfill Script (from Git Commits)")
    print("=" * 60)
    print()
    print("This script will use the git commit hashes stored in the database")
    print("to extract author information from your git repository.")
    print()
    print("IMPORTANT: This requires that the git commits are accessible")
    print("in a git repository (either current directory or specified path).")
    print()
    
    # Ask for git repository path
    print("Enter the path to your git repository")
    print("(press Enter to use current directory):")
    repo_path = input("> ").strip()
    
    if not repo_path:
        repo_path = None
        print("Using current directory")
    elif not os.path.exists(repo_path):
        print(f"ERROR: Path '{repo_path}' does not exist")
        sys.exit(1)
    elif not os.path.exists(os.path.join(repo_path, '.git')):
        print(f"WARNING: '{repo_path}' does not appear to be a git repository")
        response = input("Continue anyway? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("Aborted.")
            sys.exit(0)
    
    print()
    response = input("Do you want to proceed? (yes/no): ").strip().lower()
    if response in ['yes', 'y']:
        print()
        backfill_authors_from_git(repo_path)
    else:
        print("Aborted.")
        sys.exit(0)
