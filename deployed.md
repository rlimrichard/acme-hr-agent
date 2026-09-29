# Deployment

## Platform

Render (free tier) — single web service.

## URLs

| Endpoint | URL |
|---|---|
| Application | https://acme-hr-agent.onrender.com |
| Health check | https://acme-hr-agent.onrender.com/health |
| Chat API | https://acme-hr-agent.onrender.com/chat |

## Architecture (single service)

All components run in one Render web service:

- **FastAPI web app** — listens on `$PORT` (assigned by Render)
- **MCP server** — launched as a subprocess on `localhost:8001` by the FastAPI lifespan event
- **ChromaDB index** — built during the Render build step (`python -m src.rag.ingest`), persisted to local filesystem for the lifetime of the service instance
- **Employee mock data** — `data/employees.json` committed to repo, read at runtime

## Build and start commands

```
Build:  pip install -r requirements.txt && python -m src.rag.ingest
Start:  uvicorn src.app.main:app --host 0.0.0.0 --port $PORT
```

## Environment variables (set in Render dashboard)

| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | LLM provider key — set as a secret in Render, never committed |
| `OPENROUTER_MODEL` | `qwen/qwen3.8-27b:free` (set in render.yaml) |
| `MCP_SERVER_URL` | `http://127.0.0.1:8001` (set in render.yaml) |

## Cold-start behavior

Render free-tier services spin down after ~15 minutes of inactivity. On a cold start:

1. Render boots the container and runs the start command (~10–15 s)
2. The FastAPI lifespan starts the MCP subprocess and waits up to 10 s for it to be ready
3. The first `/chat` request may experience **30–45 s total latency** due to the embedding model being loaded from disk into memory

Warm requests (after the first) complete in 2–8 s depending on LLM provider latency.

## Latency (warm, measured after deployment)

| Metric | Value |
|---|---|
| p50 latency (local) | 57 ms |
| p95 latency (local) | 6,313 ms (includes LLM round-trip via OpenRouter) |
| p50 latency (Render) | *(run `python evaluation/eval_runner.py --endpoint https://acme-hr-agent.onrender.com`)* |
| p95 latency (Render) | *(see above)* |
| Cold-start total | ~30–45 s (Render free tier; ChromaDB + embedding model load) |
