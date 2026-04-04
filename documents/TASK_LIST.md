# Project Task List

Master tracking for the LLM abstraction, auth, and deployment work.

## Phase 1 — LLM Abstraction (local only, no Azure yet)

- [x] 1. Create `llm/` module with base protocol + Ollama provider
- [x] 2. Update `app.py` to use new `llm/` module
- [ ] 3. Test locally — everything works exactly as before

> **Note:** Cursor jumped ahead and built Phase 4 (auth + database + adventures)
> in the same pass as Phase 1. The `llm/` module is correct. The app.py rewrite
> includes auth, adventures, and SQLite — all untested. We are fixing forward.

## Phase 1.5 — Fix Forward (stabilize Cursor's big-bang rewrite)

- [ ] 4. Install `bcrypt` in venv (`pip install bcrypt`)
- [ ] 5. Verify Flask server starts without errors
- [ ] 6. Test web UI: register, login, create adventure, play a few turns
- [ ] 7. Fix `play.py` CLI client to work with new auth + adventure API (or add legacy bypass)
- [ ] 8. Remove dead file `src/lib/playBootstrap.ts`
- [ ] 9. Fix `proxyFlaskText` double Set-Cookie relay in `flask.ts`
- [ ] 10. Commit working state to git

## Phase 2 — Azure Provider (code only, no deployment)

- [ ] 11. Add Azure provider to `llm/`
- [ ] 12. Add Azure config vars to `config.py`
- [ ] 13. Add `langchain_openai` to `requirements.txt`
- [ ] 14. Test locally by pointing Azure provider at Azure trial
- [ ] 15. Verify a game works end-to-end on Azure

## Phase 3 — Game Rating + Content Filtering

- [ ] 16. Add `"rating"` field to game JSONs
- [ ] 17. Add `CONTENT_RATING` env var to `config.py`
- [ ] 18. Add filtering to `/api/games` endpoint
- [ ] 19. Test both modes locally (`all` vs `sfw`)

## Phase 4 — Auth + Database (DONE by Cursor, needs testing)

- [x] 20. SQLite schema + `db.py`
- [x] 21. `auth.py` + login endpoints
- [x] 22. Refactor `app.py` endpoints to use adventures
- [x] 23. Frontend login page + adventure picker
- [x] 24. Update play page to use `adventure_id`
- [ ] 25. Full end-to-end test of auth flow

## Phase 5 — Hostinger Deployment

- [ ] 26. Set up Hostinger VPS account
- [ ] 27. Dockerfile + deploy config
- [ ] 28. DNS + SSL
- [ ] 29. First deploy

## Workflow

- **Claude Code** — architecture, planning, Cursor prompts, code review
- **Cursor** — builds code from prompts
- **Git** — commit before and after each Cursor prompt
