# Project Task List

Master tracking for all project work.

## Completed Phases

### Phase 1 — LLM Abstraction
- [x] `llm/` module with base protocol, Ollama provider, Azure provider
- [x] Config-driven provider selection via `LLM_PROVIDER` env var
- [x] `python-dotenv` support for `.env` files

### Phase 2 — Auth + Database
- [x] SQLite schema: users, adventures, save_slots, game_content
- [x] bcrypt auth with Flask session cookies
- [x] Login/register endpoints and frontend login page
- [x] Adventure-scoped gameplay (game_content_id)

### Phase 3 — Hostinger Deployment
- [x] VPS: Ubuntu 24.04, gunicorn + node, nginx reverse proxy, SSL
- [x] Live at https://rpg.earl-mcgowen.com
- [x] GitHub auto-deploy via webhook (rpg-webhook.service)
- [x] Deploy script at `/var/www/rpg-engine/deploy.sh`

### Phase 4 — Story Creation + Community
- [x] game_content DB table with seed from games/ folder
- [x] Community browse page (/community)
- [x] My Stories page (/stories) with CRUD
- [x] Create Story page with Build form + Paste JSON tabs
- [x] AI story generator (POST /generate-story)
- [x] AI polish/rewrite controls on form fields (POST /improve-story-text)
- [x] Copy-on-play with attribution tracking
- [x] Lobby redesigned with story catalog cards

### Phase 5 — LangGraph Pipeline Improvements
- [x] Mood scoping: only update NPCs in current room
- [x] Conditional edges: skip unnecessary nodes
- [x] Per-adventure locking on /chat
- [x] Pause enforcement in /chat
- [x] Narrator engine brief + strict move/pickup parsing
- [x] NPC sees narrator beat for context

## Next Up (Not Started)

### Graphics — AI-generated location images
- [ ] Decide approach: per-location cached images via DALL-E 3 or similar
- [ ] Backend endpoint to generate/cache images
- [ ] Frontend: show location banner image in Play page
- [ ] Budget: ~$0.04/image, 1-5 per story

### Story Creation Enhancements
- [ ] Guided form builder (multi-step wizard for non-technical users)
- [ ] AI assist on Edit page (same polish controls as Create)
- [ ] Story versioning (track edits over time)

### Gameplay Improvements
- [ ] Streaming LLM responses (LangGraph astream for better perceived latency)
- [ ] Quest/objective tracking node
- [ ] Combat/challenge node (conditional edge)
- [ ] NPC dialogue memory (per-NPC summaries across turns)
- [ ] Merge movement+inventory into single structured LLM call

### Infrastructure
- [ ] Deploy script for game files (automate the rsync for games/)
- [ ] Database backup strategy
- [ ] Rate limiting on registration (if traffic grows)
- [ ] Admin view for user/content management

## Deployment Details

- **VPS**: 45.132.241.60 (srv674751.hstgr.cloud)
- **App root**: `/var/www/rpg-engine/`
- **Services**: rpg-flask (gunicorn:5051), rpg-web (node:3002), rpg-webhook (port 9000)
- **Auto-deploy**: git push → GitHub webhook → deploy.sh
- **Manual**: `rsync games/ root@45.132.241.60:/var/www/rpg-engine/games/`
- **DB reset**: `ssh root@45.132.241.60 "rm -f /var/www/rpg-engine/rpg.db && systemctl restart rpg-flask"`
- **Game copy**: `rsync -avz games/ root@45.132.241.60:/var/www/rpg-engine/games/`

## Workflow

- **Claude Code** — architecture, planning, Cursor prompts, code review
- **Cursor** — builds code from prompts (instructions, not code blocks)
- **Git** — commit before and after each Cursor prompt, push triggers auto-deploy
