# Demo script — SentinelAI

Target length: **4 minutes**. The rubric scores problem statement, solution demo, and technical
explanation separately, so the script gives each one dedicated time.

**Before recording**

- `ANTHROPIC_API_KEY` set in `backend/.env`
- Backend running on <http://localhost:8000>
- One completed run already in the history (so the console isn't empty on camera)
- Browser zoom ~110%, console open at **Overview**

---

## 0:00 — 0:35 · The problem

> "Companies are starting to hand real work to AI agents. The moment an agent can click *Send*,
> *Pay*, or *Delete* on a live system, you need answers to three questions: what is it allowed
> to do, who authorised this specific action, and what did it actually do?
>
> 'Be careful' is not a security control. SentinelAI is a browser-operating agent where every
> action is checked against a policy engine before it happens — and everything is recorded."

*On screen: the Overview page.*

---

## 0:35 — 1:05 · The policy engine (the part that isn't just another agent)

*Go to **Policies**.*

> "These are the rules. They're declarative, versioned, and editable — not `if` statements
> buried in the agent's prompt. Fourteen rules covering credentials, spending, destructive
> actions, and outbound messages."

*Click the **Type a card number** quick scenario.*

> "I can test any action against the policy without running an agent. Typing a card number:
> blocked, risk 100. And notice two rules matched — a permissive one for ordinary typing at
> priority 15, and the credential deny at priority 100. Highest priority wins, so it's blocked."

*Click **Spend $750**, then **Spend $9,000**.*

> "$750 needs a human. $9,000 is above the hard cap — no human can approve it."

---

## 1:05 — 2:30 · The live run (the core demo)

*Go to **Overview**, click the preset **Book a vendor meeting**, press **Start governed run**.*

> "I'm giving the agent a real job on a real web app: find Acme in the vendor directory and book
> a meeting."

*The run detail page opens and steps stream in.*

> "Claude reads the page, proposes one action at a time, and explains each one in plain English —
> because a human has to be able to judge it. Navigating, clicking through to the vendor,
> filling the form: all allowed, all unattended. Green means policy let it through."

*Wait for the submit step to gate.*

> "Now it wants to submit the form — that writes data to an external system. The policy engine
> stops it. The run is **paused**; the agent is not waiting politely, it is blocked."

*Point at the decision panel.*

> "It tells me exactly which rule fired and why: `approve-form-submission`, risk 55."

*Click **Approve**.*

> "I approve, and only now does it touch the browser."

*Run completes.*

---

## 2:30 — 3:05 · The block that can't be approved

*Start a second run with the preset **Delete a vendor (gets blocked)**.*

> "Different job, and a destructive one: remove a supplier's account entirely. The agent finds
> the settings page and goes for the delete button."

*The step shows as blocked, in red.*

> "Blocked — and notice there's no Approve button. This isn't a confirmation dialog I can click
> through. `deny` is terminal: no human in this console is allowed to authorise it. The agent
> reads the block, stops, and reports the blocker honestly instead of hunting for a workaround."

*Optional, if you want the credential angle too — say it over the same screen rather than
running a second job:*

> "The same thing guards credentials. And there the model isn't trusted at all: it can claim a
> field is ordinary text, but SentinelAI re-reads it from the live DOM, sees
> `autocomplete="cc-number"`, and denies it regardless of what the model said."

**Why this scenario and not the payment page:** in live testing the model usually *self-censors*
on the card field — it sees the SENSITIVE marker and declines on its own, so the policy engine
never visibly fires. That's good defence in depth but a bad demo, because the layer you want to
show does nothing. The delete scenario reproduces reliably: the model is happy to click the
button, and the engine is what stops it.

---

## 3:00 — 3:35 · The audit trail

*Click **Show raw audit**.*

> "Every plan, every policy decision, every approval with the reviewer's name, every execution —
> in order, timestamped. The card number itself is redacted; secrets never reach the log.
>
> This is the artefact a compliance team actually needs. Not a chat transcript."

*Go to **Spend**.*

> "And every model call is costed and attributed per run, with a budget rule that halts a run
> that overspends."

---

## 3:35 — 4:00 · Technical close

> "The stack: FastAPI and async SQLAlchemy on the backend, Playwright driving Chromium, React
> and Tailwind for the console, WebSockets for the live stream. The planner is provider-agnostic
> — this ran on Llama 3.3 70B via Groq, and one env var switches it to Claude, GPT, or a local
> Ollama model.
>
> The design decision I'd point at: the planner proposes, it never executes. It gets a fixed
> action surface — no arbitrary JavaScript — so every step is something the policy engine can
> reason about. 182 tests cover it, including eight that run the whole loop end to end and
> assert a denied action provably never happened.
>
> That's SentinelAI: AI employees you can actually let near production."

---

## Recording checklist

- [ ] Show the **rationale text** on steps — it's what makes approval a real decision
- [ ] Pause on the decision panel long enough to read the rule name
- [ ] Show the **absence** of an Approve button on the hard deny — that's the point
- [ ] Show redaction in the raw audit
- [ ] Don't narrate the code; narrate what the product prevents

## Backup plan

If a live run misbehaves on camera, the **Policies → Quick scenarios** simulator demonstrates
every decision path instantly and never touches the network. Record the live run separately and
cut to it.
