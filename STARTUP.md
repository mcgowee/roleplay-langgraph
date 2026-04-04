# Startup Guide

Three terminals are needed to run the full stack.

## Terminal 1 — Ollama (LLM server)

```bash
ollama serve
```

Runs on `http://localhost:11434`. Leave running.

## Terminal 2 — Flask API (backend)

```bash
cd ~/projects/roleplay-langgraph
source ~/open-webui-env/bin/activate
python app.py
```

Runs on `http://localhost:5051`. Leave running.

## Terminal 3 — SvelteKit (frontend)

```bash
cd ~/projects/roleplay-langgraph/web
source ~/open-webui-env/bin/activate
npm run dev
```

Runs on `http://localhost:5173`. The `--host` flag exposes it on your local network. From another machine, use the Network URL printed by Vite (e.g., `http://192.168.x.x:5173`).

## Terminal 4 (optional) — Claude Code

```bash
cd ~/projects/roleplay-langgraph
opencode
```

## Quick checks

| What             | How to verify                              |
|------------------|--------------------------------------------|
| Ollama running   | `curl http://localhost:11434`               |
| Flask running    | `curl http://localhost:5051/games`          |
| Frontend running | Open `http://localhost:5173` in browser     |
| Models available | `ollama list`                               |
