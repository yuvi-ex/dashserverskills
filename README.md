# persona-metrics

Build a dashboard from a **role**, not from a list of metrics.

Say *"build a dashboard for the CFO"* — or a warehouse shift lead, a clinical trial coordinator — and this figures out what that person needs from the dataset actually in front of it, then builds and deploys a live dashboard on your local Exasol database.

There's no file of pre-written metrics per role. It derives the answer from your actual schema, so any persona works on any dataset.

---

## Install

**macOS, Linux, WSL, or Windows with Git Bash:**
```sh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.sh)"
```

**Windows with PowerShell only:**
```powershell
irm https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.ps1 | iex
```

> Don't paste the `curl` command into PowerShell — it won't work there. Use the `irm` command above instead.

This installs everything and asks for your Anthropic API key (press Enter to skip it — the dashboard still works, just with simpler search).

```
Installed persona-metrics · key stored · all checks passed
Ready -- ask a question in the dashboard chat panel.
```

---

## What you get

A single dashboard page with:

- **KPI tiles** showing period-over-period movement
- **Insights** — what moved and what to do about it, pulled straight from queries, not generated text
- **Charts** chosen based on what the data supports
- **A worklist** of individual rows, when relevant
- **Ask the data** — a text-to-SQL chat panel
- **Share → Download PDF**

---

## Requirements

1. **Exasol Personal Local Starter Kit** installed and running
2. **Data loaded** into it (`exakit data-load`, or `exapump upload`)
3. **The dash-server add-on** enabled — `EXAKIT_MARKETPLACE_ADDONS=dash-server exakit marketplace`
4. **This skill** — installed above
5. **A model key** (optional, recommended) — `python setup_llm_key.py`
6. **An AI client with shell access** (e.g. Claude Code) — this only works with an agent that can run commands, not a chat-only client

Full details in `DEPLOY.md`.

---

## Using it

Ask in plain language:

> "Build a dashboard for a sales manager from STARTER_KIT.STORESALES"

The agent runs the pipeline and deploys it. See `DEPLOY.md` for the deploy steps if you're doing it manually.

---

## How it works

| Stage | What happens |
|---|---|
| 1–2 | Figure out what the persona needs to decide, and what data that requires |
| 3 | Profile the dataset — what each column means and how it can be aggregated |
| 4 | Build metrics that match what the data can actually support; refuse the rest |
| 5 | Drop any metric that shows no real variation |
| 6 | Build and deploy the dashboard |

**It refuses rather than guesses.** If the data can't support what a persona needs, it says so instead of showing a misleading chart. Rates are never summed, flat metrics are cut and reported as flat, and low-confidence guesses are flagged for a human to check.

---

## Known limits

- Without a model key, the chat panel only matches keywords — no synonyms or plurals.
- SQL is Exasol-specific.
- **On Windows**, one deploy step (`app_deploy_draft`) doesn't work due to a bug in the dash-server add-on. Skip it — build, confirm the healthcheck passes, then promote directly. See `DEPLOY.md`.

Full list in `CHANGES.md`.

---

## Files

```
get.sh / get.ps1           installer for each platform
install.py                 installs the skill + key + checks everything
preflight.py                verifies your setup is ready
setup_llm_key.py           stores your Anthropic key safely
SKILL.md                   the procedure the agent follows
DEPLOY.md                  setup and deploy instructions — read this first
CHANGES.md                 known limits and fix history

assets/                    the actual pipeline code
references/                supporting docs for the agent
```
