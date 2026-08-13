#!/usr/bin/env bash
# Move Jira issues to a status: scripts/jira_transition.sh Done AVA-10 AVA-11
set -euo pipefail
cd "$(dirname "$0")/.."

TOKEN=$(grep '^JIRA_API_TOKEN=' .env | cut -d= -f2-)
EMAIL=$(grep '^JIRA_EMAIL=' .env | cut -d= -f2-)
SITE=$(grep '^JIRA_SITE_URL=' .env | cut -d= -f2-)

TARGET="$1"; shift
for KEY in "$@"; do
  TID=$(curl -s -u "$EMAIL:$TOKEN" "$SITE/rest/api/3/issue/$KEY/transitions" \
    | T="$TARGET" python3 -c "import json,sys,os; ts=json.load(sys.stdin)['transitions']; print(next((t['id'] for t in ts if t['name'].lower()==os.environ['T'].lower()), ''))")
  if [ -z "$TID" ]; then echo "$KEY -> no '$TARGET' transition available"; continue; fi
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST -u "$EMAIL:$TOKEN" \
    -H 'Content-Type: application/json' -d "{\"transition\":{\"id\":\"$TID\"}}" \
    "$SITE/rest/api/3/issue/$KEY/transitions")
  echo "$KEY -> $TARGET: HTTP $CODE"
done
