# Deploying SentinelAI

## What this app needs from a host

Not every platform can run it. The requirements are unusual because the product is a
browser-driving agent that pauses for humans:

| Requirement | Why |
|---|---|
| Persistent container (not serverless) | A run waits up to 15 minutes for an approval. The approval gate is an in-process `asyncio.Event`. |
| Single instance | The gate and event bus live in memory. On two instances, the "Approve" request can land somewhere other than the paused run. |
| WebSocket support | The console streams run events over `/ws/...`. |
| ~1 GB RAM | Chromium. 512 MB will OOM under load. |
| Writable `/tmp` | SQLite audit database. |

**Vercel, Netlify Functions, Cloudflare Workers and AWS Lambda cannot run this** — they are
serverless, break the first three rows, and cannot ship a 170 MB Chromium binary.

> ⚠️ Storage is ephemeral on every option below. The audit trail resets when the container
> restarts. That is fine for a demo; a real deployment points `DATABASE_URL` at Postgres
> (uncomment `asyncpg` in `backend/requirements.txt`).

---

## Option 1 — Hugging Face Spaces (free, most RAM)

Free CPU Spaces get 16 GB RAM, which is the most headroom of any free option here.

```bash
hf auth login                                    # paste a token with write scope
hf repo create sentinelai --repo-type space --space_sdk docker
git remote add space https://huggingface.co/spaces/<your-username>/sentinelai
git push space main
```

Then two things in the Space UI:

1. **Settings → Variables and secrets → New secret**: `GROQ_API_KEY` = your key.
   Add `LLM_PROVIDER` = `groq` as a plain variable.
2. Prepend this frontmatter to `README.md` **on the Space branch only** (HF reads it to
   configure the Space; it is noise on GitHub, so do not push it back to `origin`):

```yaml
---
title: SentinelAI
emoji: 🛡️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---
```

The first build takes ~5 minutes (Chromium layer). The console is at the Space root URL.

---

## Option 2 — Railway (fastest to a URL)

```bash
npm i -g @railway/cli
railway login
railway init
railway up
```

Railway detects the root `Dockerfile` and injects `$PORT`, which the image already honours.
Then set variables in the dashboard (or `railway variables set`):

```
LLM_PROVIDER=groq
GROQ_API_KEY=<your key>
```

Free trial credit covers a hackathon demo comfortably. Generate a public domain under
**Settings → Networking → Generate Domain**.

---

## Option 3 — Render (Blueprint already committed)

`render.yaml` is in the repo, so: **New → Blueprint → select the repo → Apply**, then paste
`GROQ_API_KEY` when prompted.

Note the plan: `render.yaml` requests `starter` ($7/mo) deliberately. Render's free instance
is 512 MB and Chromium will be killed mid-run. If you want free, use Option 1.

---

## Verifying a deployment

```bash
curl https://<your-url>/api/health
```

Expect `"planner_configured": true`. If it is `false`, the provider key did not reach the
container — check the secret name matches exactly (`GROQ_API_KEY`).

Then, in the console:

1. **Policies → Type a card number** — should return *Blocked*. This exercises the policy
   engine with no browser and no model, so it isolates config problems from runtime ones.
2. Start the **Delete a vendor (gets blocked)** preset — this exercises Chromium. If step 1
   works and this hangs, the browser failed to launch: check logs for a Chromium sandbox
   error and set `BROWSER_NO_SANDBOX=true` if the host forces the container to run as root.

---

## Honest status

The images here are **not built and run in CI**. They are assembled from the same
`requirements.txt` that the 182-passing test suite runs against, and the base image tag is
pinned to match the Playwright version, but the container itself has not been executed. Budget
a few minutes for the first deploy to surface something — the likeliest candidates are the
Chromium sandbox under root and the port binding.
