#!/usr/bin/env bash
# Deploy latest changes to hrapp.elcaro.io (OCI Oracle Linux 9, user opc)
# Usage: ./scripts/deploy.sh [--key /path/to/ssh_key]
set -euo pipefail

SSH_KEY="${DEPLOY_SSH_KEY:-}"
REMOTE_USER="opc"
REMOTE_HOST="hrapp.elcaro.io"
APP_DIR="/opt/acme-hr-agent"

SSH_OPTS=(-o StrictHostKeyChecking=no)
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS+=(-i "$SSH_KEY")
fi

echo "==> Deploying to $REMOTE_USER@$REMOTE_HOST ..."
ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" bash <<'REMOTE'
set -euo pipefail
cd /opt/acme-hr-agent
echo "--- git pull ---"
git pull --ff-only
echo "--- pip sync ---"
.venv/bin/pip install -q -r requirements.txt
echo "--- restart service ---"
sudo systemctl restart acme-hr-agent
sleep 5
sudo systemctl is-active --quiet acme-hr-agent && echo "Service is running." || { echo "Service failed!"; sudo systemctl status acme-hr-agent --no-pager; exit 1; }
echo "--- health check ---"
curl -sf http://127.0.0.1:8000/health | python3 -m json.tool
echo "==> Deploy complete."
REMOTE
