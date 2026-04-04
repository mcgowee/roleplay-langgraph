# Project Task List

Master tracking for the LLM abstraction, auth, and deployment work.

## Phase 1 — LLM Abstraction (local only, no Azure yet)

- [x] 1. Create `llm/` module with base protocol + Ollama provider
- [x] 2. Update `app.py` to use new `llm/` module
- [x] 3. Test locally — everything works exactly as before

> **Note:** Cursor jumped ahead and built Phase 4 (auth + database + adventures)
> in the same pass as Phase 1. The `llm/` module is correct. The app.py rewrite
> includes auth, adventures, and SQLite — all untested. We are fixing forward.

## Phase 1.5 — Fix Forward (stabilize Cursor's big-bang rewrite)

- [x] 4. Install `bcrypt` in venv (`pip install bcrypt`)
- [x] 5. Verify Flask server starts without errors
- [x] 6. Test web UI: register, login, create adventure, play a few turns
- [x] 7. Fix `play.py` CLI client to work with new auth + adventure API
- [x] 8. Remove dead file `src/lib/playBootstrap.ts` (already removed by Cursor)
- [x] 9. Fix `proxyFlaskText` double Set-Cookie relay in `flask.ts`
- [x] 10. Commit working state to git — `d999503`

## Phase 2 — Azure Provider (code only, no deployment)

- [x] 11. Add Azure provider to `llm/`
- [x] 12. Add Azure config vars to `config.py` + `python-dotenv` support
- [x] 13. Add `langchain_openai` to `requirements.txt`
- [x] 14. Test locally — Ollama still works, Azure works via `.env`
- [x] 15. Verify a game works end-to-end on Azure — confirmed, NSFW blocked by Azure filters

## Phase 3 — Game Rating + Content Filtering — SKIPPED

> Not needed. SFW/NSFW is handled at the deployment level: only copy SFW game
> files to the hosted server. Azure's built-in content filters provide an
> additional safety net. No code changes required.

## Phase 4 — Auth + Database (DONE by Cursor, needs testing)

- [x] 20. SQLite schema + `db.py`
- [x] 21. `auth.py` + login endpoints
- [x] 22. Refactor `app.py` endpoints to use adventures
- [x] 23. Frontend login page + adventure picker
- [x] 24. Update play page to use `adventure_id`
- [x] 25. Full end-to-end test of auth flow

## Phase 5 — Hostinger Deployment — DONE

- [x] 26. VPS already running (Ubuntu 24.04 LTS, KVM 1, 45.132.241.60)
- [x] 27. Deployed directly (no Docker) — gunicorn + node, matching existing VPS setup
- [x] 28. DNS: `rpg.earl-mcgowen.com` → A record to VPS IP. SSL via existing Let's Encrypt.
- [x] 29. First deploy — live at **https://rpg.earl-mcgowen.com**

### VPS deployment details
- App root: `/var/www/rpg-engine/`
- Flask: gunicorn on port 5051 (`rpg-flask.service`)
- SvelteKit: node on port 3002 (`rpg-web.service`)
- nginx: reverse proxy on 443, proxies all traffic to SvelteKit
- `.env`: Azure provider (`LLM_PROVIDER=azure`, `gpt-4o-mini`)
- Deploy command (from desktop): `rsync -avz --exclude='node_modules' --exclude='.svelte-kit' --exclude='__pycache__' --exclude='.env' --exclude='rpg.db' --exclude='sessions' --exclude='logs' --exclude='.venv' --exclude='.git' . root@45.132.241.60:/var/www/rpg-engine/`
- After rsync: SSH in, rebuild SvelteKit (`cd web && npm run build`), restart services (`systemctl restart rpg-flask rpg-web`)

## Workflow

- **Claude Code** — architecture, planning, Cursor prompts, code review
- **Cursor** — builds code from prompts
- **Git** — commit before and after each Cursor prompt
