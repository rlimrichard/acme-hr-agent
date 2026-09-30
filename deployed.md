# Deployment

## Platform

Oracle Cloud Infrastructure (OCI) — Oracle Linux 9.8, always-on VPS.

## URLs

| Endpoint | URL |
|---|---|
| Application | https://hrapp.elcaro.io |
| Health check | https://hrapp.elcaro.io/health |
| Chat API | https://hrapp.elcaro.io/chat |
| HR Documents | https://hrapp.elcaro.io/hr-docs |

## Architecture (single service)

All components run on one OCI compute instance (`hrapp.elcaro.io`):

- **FastAPI web app** — managed by systemd (`acme-hr-agent.service`), reverse-proxied by nginx on port 443 with TLS via Let's Encrypt
- **MCP server** — launched as a subprocess on `localhost:8001` by the FastAPI lifespan event
- **ChromaDB index** — built once with `python -m src.rag.ingest`, persisted to `chroma_db/` on disk
- **Employee mock data** — `data/employees.json` committed to repo, read at runtime

## Server setup

| Detail | Value |
|---|---|
| OS | Oracle Linux 9.8 |
| Python | 3.11 (installed alongside system 3.9) |
| App directory | `/opt/acme-hr-agent/acme-hr-agent/` |
| Venv | `.venv/` inside the app directory |
| systemd service | `/etc/systemd/system/acme-hr-agent.service` |
| nginx config | `/etc/nginx/conf.d/hrapp.elcaro.io.conf` |
| TLS certs | Let's Encrypt via Certbot |

## Environment variables

| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | LLM provider key — stored in `/etc/sysconfig/acme-hr-agent`, never committed |
| `OPENROUTER_MODEL` | `qwen/qwen3.8-27b:free` |
| `MCP_SERVER_URL` | `http://127.0.0.1:8001` |

## Deploying updates

### Automatic (CI/CD)

Every push to `main` that passes CI tests deploys automatically via GitHub Actions:

1. GitHub Actions SSHes into the server using the `DEPLOY_SSH_KEY` secret
2. `git pull --ff-only` in `/opt/acme-hr-agent/acme-hr-agent/`
3. `rsync` syncs source files to the service working directory (preserving `chroma_db/` and `data/`)
4. `sudo systemctl restart acme-hr-agent`
5. Health check confirms the service is up

**Required secret:** Add the OCI SSH private key as `DEPLOY_SSH_KEY` under *GitHub → Settings → Secrets and variables → Actions*.

### Manual

```bash
DEPLOY_SSH_KEY=/path/to/ssh_key ./scripts/deploy.sh
```

Or directly on the server:
```bash
cd /opt/acme-hr-agent/acme-hr-agent
git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
sudo systemctl restart acme-hr-agent
```

## Latency (warm)

No cold-start concern — the OCI VPS runs the systemd service continuously; there is no spin-down period.

Latency measured locally by running `evaluation/eval_runner.py` (25 questions, k=5 baseline):

| Metric | Local dev |
|---|---|
| p50 | 55 ms |
| p95 | 2,346 ms |

p50 is low because most questions follow deterministic fast paths (no LLM call). p95 is driven by the expense-advisor workflow which includes a full LLM round-trip via OpenRouter's free tier.

To measure production latency:
```bash
python evaluation/eval_runner.py --endpoint https://hrapp.elcaro.io
```
