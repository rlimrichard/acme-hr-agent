#!/usr/bin/env bash
# Deploy latest changes to hrapp.elcaro.io (OCI Oracle Linux 9, user opc)
# Usage: DEPLOY_SSH_KEY=/path/to/ssh_key ./scripts/deploy.sh
set -euo pipefail

SSH_KEY="${DEPLOY_SSH_KEY:-}"
REMOTE_USER="opc"
REMOTE_HOST="hrapp.elcaro.io"

SSH_OPTS=(-o StrictHostKeyChecking=no)
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS+=(-i "$SSH_KEY")
fi

echo "==> Deploying to $REMOTE_USER@$REMOTE_HOST ..."
ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" bash <<'REMOTE'
set -euo pipefail
cd /opt/acme-hr-agent/acme-hr-agent
echo "--- git pull ---"
git pull --ff-only
echo "--- sync to service directory ---"
sudo -n rsync -a --chown=opc:opc \
  --exclude='.git' --exclude='.venv' --exclude='.venv311' --exclude='.env' \
  --exclude='logs' --exclude='chroma_db' --exclude='data' \
  --exclude='evaluation/results.csv' . /opt/acme-hr-agent/
cd /opt/acme-hr-agent
echo "--- pip sync ---"
.venv311/bin/python -m pip install -q -r requirements.txt
echo "--- regression tests ---"
.venv311/bin/python scripts/run_regression_tests.py
echo "--- restart service ---"
sudo systemctl restart acme-hr-agent
sleep 5
sudo systemctl is-active --quiet acme-hr-agent && echo "Service is running." || { echo "Service failed!"; sudo systemctl status acme-hr-agent --no-pager; exit 1; }
echo "--- health check ---"
curl -sf http://127.0.0.1:8000/health | .venv311/bin/python -m json.tool
echo "==> Deploy complete."
REMOTE
