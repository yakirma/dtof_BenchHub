#!/bin/sh
# Update BenchHub to the latest origin/main and restart the honcho stack.
#
#   ./scripts/update.sh            update and restart
#   ./scripts/update.sh --check    report status only, change nothing
#
# Refuses to touch anything unless the checkout is clean, on main, and strictly
# behind origin/main, so it can never discard local work or rewrite history.

set -e
BRANCH=main
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$REPO is not a git checkout."

say "Fetching origin/$BRANCH ..."
git fetch origin "$BRANCH"

CURRENT=$(git rev-parse --abbrev-ref HEAD)
LOCAL=$(git rev-parse --short HEAD)
REMOTE=$(git rev-parse --short "origin/$BRANCH")
BEHIND=$(git rev-list --count "HEAD..origin/$BRANCH")
AHEAD=$(git rev-list --count "origin/$BRANCH..HEAD")
DIRTY=$(git status --porcelain)

say ""
say "  branch:  $CURRENT"
say "  local:   $LOCAL  $(git log -1 --format=%s)"
say "  remote:  $REMOTE  ($BEHIND behind, $AHEAD ahead)"
[ -n "$DIRTY" ] && say "  tree:    UNCOMMITTED CHANGES"
say ""

if [ "$1" = "--check" ]; then
    [ "$BEHIND" -gt 0 ] && say "Update available. Run without --check to apply." || say "Up to date."
    exit 0
fi

[ "$CURRENT" = "$BRANCH" ] || die "on '$CURRENT', not '$BRANCH'. Checkout $BRANCH first."
[ -z "$DIRTY" ] || die "uncommitted changes present. Commit or stash them first."
[ "$AHEAD" -eq 0 ] || die "$AHEAD local commit(s) are not on origin/$BRANCH. Push or reset them first."
if [ "$BEHIND" -eq 0 ]; then say "Already up to date — nothing to do."; exit 0; fi

say "Fast-forwarding $LOCAL -> $REMOTE ..."
git merge --ff-only "origin/$BRANCH"

say "Applying any schema migrations ..."
python migrate_db.py || die "migration failed; the code is updated but the stack was NOT restarted."

if pgrep -f 'honcho start' >/dev/null 2>&1; then
    say "Restarting the honcho stack ..."
    pkill -f 'honcho start' >/dev/null 2>&1 || true
    sleep 1
fi
say "Starting honcho ..."
exec honcho start
