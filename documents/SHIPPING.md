# Shipping checklist (LangGraph RPG)

## What you are deploying

- **API**: Flask app (`app.py`) — JSON API, SQLite DB, proxies LLM (Ollama or Azure).
- **Web**: SvelteKit Node server — server-side proxy to Flask (`FLASK_API_URL`), serves the UI.

Do **not** expose Flask directly to the public internet without a reverse proxy and hardening; the supported pattern is **web on :3000 (or behind TLS)** talking to **API on an internal network**.

## Required environment (API / `.env`)

| Variable | Notes |
|----------|--------|
| `SECRET_KEY` | **Required in production.** Long random string; used to sign Flask sessions. |
| `LLM_PROVIDER` | `ollama` (default) or `azure`. |
| `OLLAMA_HOST` | URL reachable **from the API process** (e.g. `http://host.docker.internal:11434` in Docker on Linux). |
| Azure vars | If `LLM_PROVIDER=azure`: `AZURE_ENDPOINT`, `AZURE_API_KEY`, `AZURE_DEPLOYMENT`, `AZURE_API_VERSION`. |

## HTTPS / cookies

When the site is served over **HTTPS**:

- Set `SESSION_COOKIE_SECURE=true` on the API so session cookies are marked `Secure`.
- Set SvelteKit **`ORIGIN`** to your public URL (e.g. `https://rpg.example.com`). The compose file defaults to `http://localhost:3000` for local use.

## Docker (recommended path)

```bash
cp .env.example .env
# Edit .env: SECRET_KEY, LLM settings, optionally SESSION_COOKIE_SECURE + ORIGIN for HTTPS

docker compose up --build
```

- **UI**: http://localhost:3000  
- **API** (debug / health): http://localhost:5051/games  

Data persists in the **`rpg-data`** Docker volume (`DATABASE_PATH=/data/rpg.db`, logs under `/data/logs`).

### Ollama and Docker

- Run Ollama on the **same machine** as Docker; `docker-compose.yml` sets `OLLAMA_HOST` to `http://host.docker.internal:11434` and adds `extra_hosts` for Linux.
- Pull the models your stories use (`DEFAULT_MODEL` in `.env`).

### Gunicorn

The API image runs **one Gunicorn worker** (`--workers 1`) because SQLite does not handle concurrent writers well. For heavy traffic, plan a move to PostgreSQL (not included in this repo).

## Bare metal (no Docker)

1. Python venv: `pip install -r requirements.txt gunicorn`
2. `gunicorn --bind 0.0.0.0:5051 --workers 1 --threads 4 --timeout 120 app:app`
3. `cd web && npm ci && npm run build && NODE_ENV=production HOST=0.0.0.0 PORT=3000 FLASK_API_URL=http://127.0.0.1:5051 node build/index.js`
4. Put **nginx** (or similar) in front: TLS → web `:3000`; keep API on loopback or a private interface.

## Reverse proxy (sketch)

- Terminate TLS at nginx/Caddy/Traefik.
- Route `https://your-domain/` → Node (port 3000).
- Do **not** need to expose Flask publicly if the browser only talks to SvelteKit (default design).

## Smoke test after deploy

1. Open the web app → register / log in.
2. Lobby loads catalog → start a story → send one message on Play.
3. If using **Tools**, confirm `RPG_REPO_ROOT` points at this repo on the web server (Docker compose mounts `.` at `/repo`). The web image includes **Python 3** and **python-dotenv** so **Validate JSON** and **Feedback report** can run against the mounted repo. **Story → draft** may still need extra Python packages (`requests`, etc.); run that script from the host or extend the web image if you rely on it in production.

## Optional next steps

- Central logging / metrics (outside repo).
- Automated DB backups for `/data/rpg.db` (or `DATABASE_PATH`).
- `@types/node` in `web/` so `npm run check` is clean in CI.
