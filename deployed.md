# Deployment

## Platform

Oracle Cloud Infrastructure (OCI) — Oracle Linux 9.8, always-on VPS. The
instance metadata reports `VM.Standard.E6.Ax.Flex` with 4 OCPUs and 28 GB
memory (checked October 1, 2026). This is **not an OCI Always Free shape**:
Oracle lists `VM.Standard.E2.1.Micro` and eligible `VM.Standard.A1.Flex`
capacity under its [Always Free compute resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
The app is currently running, but account billing, credits, and any special
pricing arrangement are not visible to this repository. Do not describe this
deployment as free-tier until the owner verifies the tenancy's billing and
either confirms an equivalent no-cost arrangement or migrates to an eligible
shape. A shape migration should be planned separately to avoid interrupting
the live service or losing its persisted index and ticket data.

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
- **MCP server** — official MCP SDK Streamable HTTP endpoint at `localhost:8001/mcp`, launched as a subprocess by FastAPI lifespan
- **ChromaDB index** — built once with `python -m src.rag.ingest`, persisted to `chroma_db/` on disk
- **Employee mock data** — `data/employees.json` committed to repo, read at runtime

## Server setup

| Detail | Value |
|---|---|
| OS | Oracle Linux 9.8 |
| Python | 3.11 (installed alongside system 3.9) |
| Git checkout | `/opt/acme-hr-agent/acme-hr-agent/` |
| Service working directory | `/opt/acme-hr-agent/` |
| Python virtual environment | `/opt/acme-hr-agent/.venv311/` |
| systemd service | `/etc/systemd/system/acme-hr-agent.service` |
| nginx config | `/etc/nginx/conf.d/hrapp.elcaro.io.conf` |
| TLS certs | Let's Encrypt via Certbot |

## Environment variables

| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | LLM provider key — stored in `/opt/acme-hr-agent/.env`, never committed |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash-lite` (low-cost paid model; usage charges apply) |
| `MCP_SERVER_URL` | `http://127.0.0.1:8001` |

The app loads `/opt/acme-hr-agent/.env`; `/etc/sysconfig/acme-hr-agent` is not
an active systemd environment file for this service. Keep the actual runtime
file and the checkout's excluded `.env` in sync when changing model settings.
The previous free model was rate-limited upstream and silently triggered the
app's deterministic fallback. Verify LLM use via admin audit routing source and
confidence status, not merely a passing response test.

## Deploying updates

### Automatic (CI/CD)

Every push to `main` that passes CI tests deploys automatically via GitHub Actions:

1. GitHub Actions SSHes into the server using the `DEPLOY_SSH_KEY` secret
2. `git pull --ff-only` in `/opt/acme-hr-agent/acme-hr-agent/`
3. `rsync` syncs source files to the service working directory, preserving the live `chroma_db/`, `data/`, and logs
4. `.venv311/bin/python -m pip install -r requirements.txt` and the deterministic regression suite run
5. `sudo systemctl restart acme-hr-agent`; the health check confirms app and MCP discovery

**Required secret:** Add the OCI SSH private key as `DEPLOY_SSH_KEY` under *GitHub → Settings → Secrets and variables → Actions*.

### Manual

```bash
DEPLOY_SSH_KEY=/path/to/ssh_key ./scripts/deploy.sh
```

The manual script follows the same checkout → sync → dependency install → regression → restart sequence as CI. A `git pull` alone does **not** update the service working directory. If policy files change, rebuild the persisted index explicitly from `/opt/acme-hr-agent` with `.venv311/bin/python -m src.rag.ingest` before restart.

## Latency (warm)

No cold-start concern — the OCI VPS runs the systemd service continuously; there is no spin-down period.

Older latency figures in the repository predate the current LLM-driven workflows and should not be used as current measurements. The evaluation runner reports fresh warm-request p50/p95 (excluding login) when run against the deployed service. The VPS does not spin down, so there is no hosting cold start, though model-provider latency can vary.

To measure production latency:
```bash
PORTAL_EVAL_PASSWORD=acme123 python evaluation/eval_runner.py --endpoint https://hrapp.elcaro.io
```
