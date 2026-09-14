#!/usr/bin/env python3
"""
Backfill git_author from the git.info bundled in each dataset/submission upload.

Unlike backfill_git_authors.py (which re-derives the author from git_commit by
running `git show` against a local clone), this script reads the author straight
out of the `git.info` / `git_info.json` file that was shipped inside the upload.
That makes it work on a machine that has the ~/.dtofbenchmarking data dir but
NOT the source git repo. When no author can be found in the upload, the row is
stamped with 'Unknown' so the UI stops showing N/A.

Sources (mirrors how app.py stores uploads):
  - submission <id>: uploads/submissions/<id>/git.info, falling back to the
    git.info embedded in uploads/submissions/<id>/submission.zip
  - dataset <name>: git.info embedded in
    uploads/datasets/<secure_filename(name)>/<secure_filename(name)>.zip
    (datasets don't keep an extracted git.info, only the original ZIP)

Idempotent: only touches rows whose git_author is NULL or ''. Safe to re-run.
Run:  python backfill_authors_from_upload.py [--no-unknown] [--dry-run]
"""

import sqlite3
import os
import sys
import json
import zipfile

try:
    from werkzeug.utils import secure_filename
except ImportError:
    # Minimal fallback so the script still runs without Flask installed.
    import re

    def secure_filename(name):
        name = str(name).strip().replace(' ', '_')
        return re.sub(r'[^A-Za-z0-9_.-]', '', name) or 'file'


GIT_INFO_NAMES = ('git.info', 'git_info.json')


def get_data_dir():
    return os.path.join(os.path.expanduser('~'), '.dtofbenchmarking')


def get_db_path():
    return os.path.join(get_data_dir(), 'database.db')


def get_uploads_dir():
    return os.path.join(get_data_dir(), 'uploads')


def _author_from_git_dict(data):
    """Pull a non-empty author string out of a parsed git.info dict."""
    if not isinstance(data, dict):
        return None
    author = (data.get('author') or '').strip()
    return author or None


def _read_git_info_from_dir(dir_path):
    """Read git.info / git_info.json sitting at the root of an extracted upload."""
    for fname in GIT_INFO_NAMES:
        path = os.path.join(dir_path, fname)
        if os.path.isfile(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"    Warning: could not parse {path}: {e}")
    return None


def _read_git_info_from_zip(zip_path):
    """Find and parse the shallowest git.info / git_info.json inside a ZIP."""
    if not os.path.isfile(zip_path):
        return None
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            candidates = [
                n for n in zf.namelist()
                if os.path.basename(n) in GIT_INFO_NAMES and not n.startswith('__MACOSX')
            ]
            # Shallowest path first (root git.info wins over a nested one).
            candidates.sort(key=lambda n: (n.count('/'), len(n)))
            for name in candidates:
                try:
                    with zf.open(name) as f:
                        return json.loads(f.read().decode('utf-8'))
                except Exception as e:
                    print(f"    Warning: could not parse {name} in {zip_path}: {e}")
    except (zipfile.BadZipFile, OSError) as e:
        print(f"    Warning: could not open {zip_path}: {e}")
    return None


def author_for_submission(uploads_dir, submission_id):
    folder = os.path.join(uploads_dir, 'submissions', str(submission_id))
    data = _read_git_info_from_dir(folder)
    author = _author_from_git_dict(data)
    if author:
        return author
    # Fall back to the git.info embedded in the saved submission.zip.
    data = _read_git_info_from_zip(os.path.join(folder, 'submission.zip'))
    return _author_from_git_dict(data)


def author_for_dataset(uploads_dir, dataset_name):
    folder_name = secure_filename(dataset_name)
    folder = os.path.join(uploads_dir, 'datasets', folder_name)
    # Datasets normally only keep the original ZIP, but check an extracted
    # git.info too in case one is present.
    data = _read_git_info_from_dir(folder)
    author = _author_from_git_dict(data)
    if author:
        return author
    data = _read_git_info_from_zip(os.path.join(folder, f"{folder_name}.zip"))
    return _author_from_git_dict(data)


def backfill(stamp_unknown=True, dry_run=False):
    db_path = get_db_path()
    uploads_dir = get_uploads_dir()

    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)
    if not os.path.isdir(uploads_dir):
        print(f"ERROR: Uploads dir not found at {uploads_dir}")
        sys.exit(1)

    print(f"Database:     {db_path}")
    print(f"Uploads dir:  {uploads_dir}")
    print(f"Mode:         {'DRY RUN (no writes)' if dry_run else 'WRITE'}; "
          f"unknown -> {'Unknown' if stamp_unknown else 'left empty'}")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    totals = {}

    # (table, id-or-name column used to locate the upload)
    plans = [
        ('submission', 'id', author_for_submission),
        ('dataset', 'name', author_for_dataset),
    ]

    for table, key_col, resolver in plans:
        print("=" * 60)
        print(f"BACKFILLING {table.upper()} AUTHORS FROM UPLOAD git.info")
        print("=" * 60)
        cursor.execute(
            f"SELECT id, name, {key_col} FROM {table} "
            f"WHERE git_author IS NULL OR git_author = ''"
        )
        rows = cursor.fetchall()
        found = stamped_unknown = 0
        for row_id, name, key in rows:
            author = resolver(uploads_dir, key)
            if author:
                if not dry_run:
                    cursor.execute(
                        f"UPDATE {table} SET git_author = ? WHERE id = ?",
                        (author, row_id),
                    )
                print(f"✅ {table} '{name}' (id={row_id}): {author}")
                found += 1
            elif stamp_unknown:
                if not dry_run:
                    cursor.execute(
                        f"UPDATE {table} SET git_author = 'Unknown' WHERE id = ?",
                        (row_id,),
                    )
                print(f"❓ {table} '{name}' (id={row_id}): no git.info -> Unknown")
                stamped_unknown += 1
            else:
                print(f"⏭️  {table} '{name}' (id={row_id}): no git.info, left empty")
        print(f"\n{table}: {len(rows)} missing | {found} from git.info | "
              f"{stamped_unknown} -> Unknown\n")
        totals[table] = (found, stamped_unknown)

    if dry_run:
        print("DRY RUN complete — no changes written.")
    else:
        conn.commit()
        print("Backfill committed. Refresh the browser to see authors.")
    conn.close()
    return totals


if __name__ == '__main__':
    stamp_unknown = '--no-unknown' not in sys.argv
    dry_run = '--dry-run' in sys.argv
    backfill(stamp_unknown=stamp_unknown, dry_run=dry_run)
