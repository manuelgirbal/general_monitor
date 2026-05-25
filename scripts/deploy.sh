#!/usr/bin/env bash
set -euo pipefail

# Sync local repo -> VPS staging dir -> /opt/monitor.
# Default is dry-run; pass --apply to execute.
#
# Preserves on the VPS: /opt/monitor/.env and /opt/monitor/.venv/
# (excluded from the staging->target step so --delete won't remove them).

VPS_HOST="main-vps"
APP="monitor"
STAGING="monitor-stage"
REMOTE_DIR="/opt/monitor"

MODE="dry-run"
case "${1:-}" in
    ""|--dry-run) MODE="dry-run" ;;
    --apply)      MODE="apply" ;;
    -h|--help)
        echo "Usage: $0 [--dry-run | --apply]"
        exit 0
        ;;
    *)
        echo "Unknown arg: $1" >&2
        echo "Usage: $0 [--dry-run | --apply]" >&2
        exit 2
        ;;
esac

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .deployignore ]]; then
    echo "Missing .deployignore at $REPO_ROOT" >&2
    exit 1
fi

LOCAL_RSYNC=(-av --delete --exclude-from=.deployignore)
REMOTE_EXCLUDES=(--exclude='.env' --exclude='.venv/')
if [[ "$MODE" == "dry-run" ]]; then
    LOCAL_RSYNC+=(-n)
    echo "==> DRY RUN — nothing will change. Re-run with --apply to execute."
else
    echo "==> APPLY — syncing for real to $VPS_HOST."
fi

echo "==> [1/2] rsync local -> $VPS_HOST:~/$STAGING/"
ssh "$VPS_HOST" "mkdir -p ~/$STAGING"
rsync "${LOCAL_RSYNC[@]}" ./ "$VPS_HOST:$STAGING/"

echo "==> [2/2] promote $STAGING/ -> $REMOTE_DIR on VPS"
if [[ "$MODE" == "dry-run" ]]; then
    ssh -t "$VPS_HOST" "sudo rsync -avn --delete ${REMOTE_EXCLUDES[*]} ~/$STAGING/ $REMOTE_DIR/"
else
    ssh -t "$VPS_HOST" "sudo rsync -a --delete ${REMOTE_EXCLUDES[*]} ~/$STAGING/ $REMOTE_DIR/ && sudo chown -R $APP:$APP $REMOTE_DIR"
fi

echo ""
echo "==> Done ($MODE)."
if [[ "$MODE" == "apply" ]]; then
    cat <<EOF

Suggested post-deploy commands (run on the VPS, none executed by this script):
  sudo systemctl restart monitor
  sudo systemctl restart monitor-ingest.timer
  systemctl status monitor monitor-ingest.timer
  journalctl -u monitor --since "1 min ago"
  journalctl -u monitor-ingest --since "1 min ago"
EOF
fi
