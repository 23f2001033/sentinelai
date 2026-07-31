# SentinelAI

**A governance layer for AI employees that operate real software.**

Most agent demos show an AI doing something impressive. The hard question for a business is
the one after that: *what stopped it from doing something terrible?*

SentinelAI is a browser-operating agent where every single action is checked against a policy
engine before it happens. Safe work runs unattended. Risky work stops and waits for a human.
Everything — the plan, the decision, the rule that fired, the human who approved it — is written
to an immutable audit trail you can replay.

---

## The problem

Companies are starting to hand real work to AI agents. The moment an agent can click "Send",
"Pay", or "Delete" on a live system, three questions become urgent:

1. **Who authorised this?** An agent that acts has to act under someone's authority.
2. **What is it allowed to do?** "Be careful" is not a security control.
3. **What did it actually do?** Post-incident, you need a record, not a chat log.

SentinelAI answers all three with one mechanism: **no action reaches the browser without a
recorded policy decision.**

---

## How it works

```
                    ┌──────────────────────────────────────────┐
  Goal ────────────▶│  Planner (pluggable LLM)                 │
                    │  Reads the page, proposes ONE action     │
                    │  plus a plain-English rationale          │
                    └──────────────────┬───────────────────────┘
                                       │  proposed action
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Action validator                        │
                    │  Re-derives labels + sensitivity from     │
                    │  the live DOM — never trusts the model    │
                    └──────────────────┬───────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Policy engine                           │
                    │  allow │ require_approval │ deny         │
                    └────┬──────────────┬──────────────┬───────┘
                         │              │              │
                     allow          approval         deny
                         │              │              │
                         │              ▼              │
                         │      ┌───────────────┐      │
                         │      │ Human review  │      │
                         │      │ approve/deny  │      │
                         │      └───────┬───────┘      │
                         │              │              │
                         ▼              ▼              ▼
                    ┌──────────────────────────────────────────┐
                    │  Browser operator (Playwright/Chromium)  │
                    │  Fixed action surface — no eval, no JS   │
                    └──────────────────┬───────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │  Audit log · spend ledger · live stream   │
                    └──────────────────────────────────────────┘
```

The loop repeats until the goal is met, the step budget runs out, or the agent hits a wall it
is not permitted to climb.

---

## What makes this different from an agent with a confirmation dialog

| | Typical agent | SentinelAI |
|---|---|---|
| Risk assessment | Hardcoded `if action == "delete"` | Declarative rule set, versioned and editable |
| Who decides | The model decides what to ask about | The policy engine decides, deterministically |
| Trusting the model | Model reports its own action as safe | Labels and sensitivity re-derived from the DOM |
| Record | Chat transcript | Structured audit trail with the deciding rule |
| Cost visibility | None | Per-call token and cost ledger, per run |

The third row matters most. If the planner mislabels a password field as "notes", a
model-trusting system types the password. SentinelAI re-reads the field from the page, sees
`type="password"`, and the deny rule fires regardless of what the model claimed.

---

## The policy engine

Rules are declarative. This is the shipped default that blocks credential entry:

```yaml
- id: deny-credential-entry
  description: The agent must never type credentials, card numbers or secrets.
  effect: deny
  priority: 100
  risk: 100
  reason: Entering credentials or payment secrets is never permitted for an autonomous agent.
  when:
    any:
      - field: action.is_sensitive
        op: eq
        value: true
      - field: action.label
        op: matches
        case_sensitive: false
        value: "password|passcode|cvv|card number|ssn|api[ _-]?key|secret"
```

**Conditions** are leaf tests (`field` / `op` / `value`) or boolean groups (`all` / `any` /
`none`), nested arbitrarily. Fifteen operators are supported: `eq`, `neq`, `gt`, `gte`, `lt`,
`lte`, `in`, `not_in`, `contains`, `not_contains`, `startswith`, `endswith`, `matches`,
`exists`, `not_exists`.

**Resolution:** the highest-priority matching rule wins. Rules that tie on priority resolve to
the most restrictive effect, so reordering a file can never silently widen access. When nothing
matches, the policy's `default_effect` applies — and the shipped default is
`require_approval`, not `allow`.

**Every decision records why:** which rules matched, which one decided, the risk score, and
whether the default was used.

### The 14 shipped rules

| Effect | Rule | Covers |
|---|---|---|
| deny | `deny-run-budget-exhausted` | Run has burned its model-spend budget |
| deny | `deny-spend-over-hard-cap` | Single spend above $5,000 |
| deny | `deny-credential-entry` | Passwords, cards, CVV, API keys, SSNs |
| deny | `deny-destructive-actions` | Account deletion, wipes, permanent removal |
| approve | `approve-spend-over-threshold` | Spend above $500 |
| approve | `approve-checkout-pages` | Any interaction on a payment page |
| approve | `approve-outbound-message` | Send, invite, publish, post, share |
| approve | `approve-form-submission` | Writing data to an external system |
| approve | `approve-file-download` | Pulling untrusted bytes in |
| approve | `approve-navigation-off-allowlist` | Leaving approved domains |
| allow | `allow-navigation-within-allowlist` | Approved business domains |
| allow | `allow-benign-clicks` | Ordinary in-page controls |
| allow | `allow-typing-non-sensitive` | Normal form fields |
| allow | `allow-read-only` | Reading, scrolling, waiting |

---

## Features

- **Governed browser operator** — Chromium driven through a fixed action surface
  (`navigate`, `click`, `type`, `select`, `submit`, `scroll`, `download`, `read_page`,
  `finish`). The planner cannot execute arbitrary JavaScript, so every step is a structured
  action the policy engine can reason about.
- **Human approval queue** — risky actions pause the run. Approve or deny from the console,
  with an optional note that lands in the audit trail.
- **Replayable audit trail** — every plan, decision, approval, execution, and error, in order,
  with the deciding rule attached.
- **Policy simulator** — test any action against any policy set without running an agent.
  Shows the effect, the reason, every matched rule, and authoring warnings.
- **Spend ledger** — token counts and cost per planner call, attributed per run, with a
  budget rule that halts a run that overspends.
- **Live updates** — WebSocket event stream; the console follows a run as it happens.
- **Sandbox site** — a bundled procurement portal (`/demo/`) so the agent operates a real page,
  including a payment form specifically for demonstrating the credential block.

---

## Running it

### Prerequisites

- Python 3.11+
- Node 18+ (only to rebuild the console; a build is committed)
- An API key for one LLM provider — **a free [Groq](https://console.groq.com/keys) key is the
  default and needs no credit card**

### Choosing a planner

The planner is provider-agnostic. Set `LLM_PROVIDER` in `backend/.env`:

| `LLM_PROVIDER` | Default model | Key | Cost |
|---|---|---|---|
| `groq` *(default)* | `llama-3.3-70b-versatile` | `GROQ_API_KEY` | Free tier, no card |
| `openrouter` | `meta-llama/llama-3.3-70b-instruct:free` | `OPENROUTER_API_KEY` | Free models available |
| `together` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | `TOGETHER_API_KEY` | Free starting credit |
| `ollama` | `llama3.1` | none | Free, fully local |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` | Paid |
| `anthropic` | `claude-opus-5` | `ANTHROPIC_API_KEY` | Paid |

Everything except `anthropic` speaks the OpenAI chat-completions dialect, so `LLM_BASE_URL`
points the same client at any other compatible endpoint. `PLANNER_MODEL` overrides the model.

Smaller open models sometimes wrap JSON in prose or drop a field, so the planner extracts JSON
from fenced or chatty replies and, if that fails, sends one repair round with the validation
error attached. Anthropic uses native structured outputs and skips the repair path.

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env            # add your GROQ_API_KEY (or another provider's)
python -m uvicorn app.main:app --reload --port 8000
```

The database is created and seeded with the baseline policy and a starter agent on first boot.

### Frontend

The console is pre-built into `backend/app/static/app`, so **the backend alone serves the whole
product** at <http://localhost:8000>. To develop the UI with hot reload:

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173, proxies the API to :8000
npm run build                   # rebuild into the backend's static tree
```

### Tests

```bash
cd backend
python -m pytest
```

182 tests, ~25 seconds. Coverage spans policy-engine semantics, the shipped rule set against
real scenarios, action validation and sensitivity detection, provider resolution and JSON
repair, the REST API, browser-operator integration against a real Chromium, and **eight
end-to-end governed-run tests** that script the planner and assert on the real loop: that an approved action executes, that a denied action
provably never does, that a hard deny skips the human entirely, that secrets are redacted from
the audit trail, and that an agent retrying a forbidden action gets shut down.

### Docker

```bash
cd backend
docker build -t sentinelai .
docker run -p 8000:8000 -e LLM_PROVIDER=groq -e GROQ_API_KEY=gsk_... sentinelai
```

The image is based on `mcr.microsoft.com/playwright/python`, which ships Chromium and its
system dependencies. A root-level `Dockerfile` exists too, for hosts that expect one there.
See **[DEPLOY.md](DEPLOY.md)** for Hugging Face Spaces, Railway and Render walkthroughs —
and for why Vercel and other serverless hosts cannot run this.
system dependencies. `render.yaml` deploys the same image as a single web service.

---

## Try it in 60 seconds

1. Open <http://localhost:8000> and go to **Policies → Quick scenarios**.
2. Click **Type a card number** — blocked, risk 100, by `deny-credential-entry`. Note that
   `allow-typing-non-sensitive` also matched but lost on priority.
3. Click **Spend $750** — needs approval. Click **Spend $9,000** — denied outright.
4. Go to **Overview**, pick the preset *"Book a vendor meeting"*, and start the run.
5. Watch the timeline: navigation and clicks run unattended; submitting the meeting form stops
   and waits for you.
6. Approve it, then open **Show raw audit** to see the full recorded trail.

---

## Layout

```
backend/
  app/
    policy/          Rule schema, evaluator, shipped default policy
    operator/        Action taxonomy, Playwright driver, Claude planner
    services/        Run loop, approval gate, audit log, event bus
    routers/         REST + WebSocket API
    static/demo/     Sandbox procurement portal the agent operates
    static/app/      Built console (generated by `npm run build`)
  tests/             182 tests
frontend/
  src/pages/         Overview, run detail, approvals, policies, spend
```

---

## Design decisions worth calling out

**The planner is not trusted.** It proposes; it never executes. Labels and sensitivity flags
are re-derived from the live DOM before policy evaluation, so a mislabelled proposal cannot
slip past a rule.

**Deny by default.** An action no rule covers requires approval rather than proceeding. New
capabilities are safe until someone decides otherwise.

**Priority over ordering.** Effect precedence only breaks ties. This lets you write a
high-priority exception to a broad deny without the file's line order becoming load-bearing.

**Downloads never touch disk.** An approved download records the URL for audit but writes no
bytes, so an approved action cannot plant an executable.

**Secrets stay out of the log.** Sensitive field contents are redacted before the audit record
is written.

---

## Limits

- Approval waits live in process memory; a server restart abandons an in-flight run. Durable
  waits would need a job queue.
- One browser context per run, so runs do not currently share session state.
- The spend ledger prices Claude models from a static table rather than a billing API.
- Web-app operation only. Native desktop control is deliberately out of scope.

---

Built for the Blueprint Hackathon, July 2026.
