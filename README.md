# persona-metrics

Build a dashboard from a **role**, not from a list of metrics.

## Install

Paste this into a terminal. It is the whole install — there is nothing to clone
first:

```sh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.sh)"
```

That one line also covers Windows if you use Git Bash, which ships its own
`sh`, `git` and `curl`.

On Windows with only PowerShell (where `curl` is an alias for `Invoke-WebRequest`
and will not accept `-fsSL`):

```powershell
irm https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.ps1 | iex
```

```
Cloning dashserverskills ... done
Anthropic API key for text-to-SQL (hidden, Enter to skip):
Installed persona-metrics · key stored · all checks passed
Ready -- ask a question in the dashboard chat panel.
```

It clones the repo, asks for your Anthropic key with the input hidden, installs
the skill where your agent looks for it, and verifies the result. Press Enter at
the prompt to skip the key — everything still works, and the chat panel falls
back to keyword matching until you add one.

<details>
<summary>Prefer to clone by hand, or no terminal available?</summary>

Cloning and running the installer yourself is identical:

```sh
git clone https://github.com/yuvi-ex/dashserverskills
cd dashserverskills && python install.py
```

A bare `git clone` on its own installs nothing and cannot prompt you: git runs
no code on clone, by design — a post-clone hook would make every clone remote
code execution. That is why the install is a script that clones, rather than a
clone that runs a script.

Where there is no terminal at all — an editor or agent console — the hidden
prompt has nothing to draw on, so pass the key by a route that keeps it out of
the chat transcript, since a key pasted into one has to be rotated:

```sh
python install.py --clipboard       # read the clipboard directly
python install.py --key-file PATH   # read it from a file
<paste> | python install.py         # key piped in on stdin
```

Add `--verbose` for every step, `--quiet` for none, `--force` to replace a key
already stored.
</details>

You say *"build a dashboard for the CFO"* — or for a warehouse shift lead, a
clinical trial coordinator, a head of trust and safety — and this derives what
that person needs **from the dataset actually in front of it**, then builds and
deploys a live dashboard on your local Exasol database.

There is no file of pre-written CFO metrics here. A catalogue only answers for
the personas someone remembered to write down, on the schemas they had in mind.
This runs a procedure instead, so an arbitrary persona meets an arbitrary
dataset and the answer is derived rather than recalled.

## What you get

A single page, deployed at `http://127.0.0.1:<port>/apps/<name>`:

- **KPI tiles** with period-over-period movement
- **Insights** — what moved, what it means, what to do. Every figure read from
  a query; none of it generated prose
- **Charts** chosen by what the data can support, not by what looks full
- **A worklist** of individual rows, but only for personas who act on rows
- **Ask the data** — a text-to-SQL panel that always shows the SQL it ran
- **Share → Download PDF** — a self-contained HTML snapshot that prints to a
  vector, selectable-text PDF

## Requirements

The skill is portable Python and Markdown; what it depends on is not.
Full checklist in **`DEPLOY.md`** — the short version:

1. **Exasol Personal Local Starter Kit**
   `curl -fsSL https://raw.githubusercontent.com/krishna-exasol/update-path/main/install.sh | sh`
2. **Data loaded** — `exakit data-load`, or
   `exapump upload yours.csv --table STARTER_KIT.YOURS -p starter-kit`.
   The pipeline profiles a *live database*, never a file. An empty database
   produces nothing.
3. **The dash-server add-on** — `EXAKIT_MARKETPLACE_ADDONS=dash-server exakit marketplace`
   (never installed by default)
4. **This skill** — the install one-liner above puts it where your agent looks
5. **A model key, for semantic text-to-SQL** — `python setup_llm_key.py`.
   Optional but strongly recommended: without it the Ask-the-data panel matches
   keywords, and fails on plurals, synonyms and intent words.
6. **An AI client with shell access** (Claude Code). This skill is
   *agent-operated*: something has to run `exapump`, run the pipeline, and drive
   dash-server's control plane. A chat-only client cannot use it.

## Platforms

One implementation everywhere: the installers are Python, which the pipeline
already requires, so there is no second copy to drift.

| Platform | Install with |
|---|---|
| macOS | `sh -c "$(curl -fsSL .../get.sh)"` |
| Linux | `sh -c "$(curl -fsSL .../get.sh)"` |
| WSL | `sh -c "$(curl -fsSL .../get.sh)"` |
| Windows, Git Bash | the **same line** — Git for Windows ships `sh`, `git` and `curl` |
| Windows, PowerShell | `irm .../get.ps1 \| iex` |

There is no separate Windows script. `get.sh` covers every platform with a POSIX
shell, Git Bash included; `get.ps1` exists only for people who have PowerShell
and no bash.

**Do not paste the `curl` line into PowerShell.** There, `curl` is an alias for
`Invoke-WebRequest`, which does not accept `-fsSL` and fails with a parameter
error rather than saying so.

Both bootstraps verify the interpreter by *running* it rather than by finding
the name: on a Windows machine without Python, `python3` resolves to a Microsoft
Store stub that opens the Store and exits. Set `DASHSERVER_REPO` to install from
a branch or a local clone, `DASHSERVER_DIR` to clone elsewhere.

The `dash-server` *skill* arrives with the kit in step 1 — you do not install
that separately. Read the real port from `exakit info`: the add-on's default is
5100, but it moves if that port is taken.

## Using it

Ask in plain language — *"build a dashboard for a sales manager from
STARTER_KIT.STORESALES"* — and the agent runs the pipeline. To drive it by hand:

```bash
# 3. profile the schema into a card
python assets/profile_schema.py <SCHEMA> --json card.json

# 4. derive metrics for a persona spec you wrote (see references/persona-axes.md)
python assets/derive_metrics.py --card card.json --persona persona.json --json plan.json

# 5. cut the metrics that carry no signal
python assets/signal_check.py --card card.json --plan plan.json --json signal.json

# 6. build the workspace
python assets/build_dashboard.py --card card.json --plan plan.json \
    --signal signal.json --name my-dash --title "My Review" --out ./out
```

Then deploy with the scaffold-first recipe in `DEPLOY.md`. Exit code 3 from
`derive_metrics.py` means the dataset cannot support the persona — that is a
result, not a failure.

## How it works

Six stages. Stages 3 and 5 are code because they are where a plausible wrong
answer is easy to produce and hard to notice.

| # | Stage | Where |
|---|---|---|
| 1 | Resolve the persona onto five axes — altitude, cadence, owned object, action, horizon | your judgement, `references/persona-axes.md` |
| 2 | Elicit 2–5 decisions, and declare the semantic roles each one requires | your judgement |
| 3 | Profile the dataset into a **schema card** — semantic role and additivity class per column, with evidence | `assets/profile_schema.py` |
| 4 | Compose metrics from a grammar; refuse what the data cannot support | `assets/derive_metrics.py` |
| 5 | Test every metric for signal; cut the flat ones and report the flatness | `assets/signal_check.py` |
| 6 | Build the Dash app, queries and shareable snapshot | `assets/build_dashboard.py` |

The card is the only thing consulted about a dataset — not table names, not a
memory of a similar schema.

Stages 3 and 5 batch their SQL. Each query used to be its own `exapump` process,
and on TPC-H that was 63 processes taking 8.7s — of which 8.0s (91%) was process
startup, since the median query took 0.12s against a bare `SELECT 1` baseline of
0.13s. The queries were free; the spawning was the cost.

| | Before | After |
|---|---|---|
| `profile_schema.py` (TPC-H, 8 tables) | 63 processes, 8.7s | **2 processes, 1.9s** |
| `signal_check.py` | one process per probe | **1 process, 0.48s** |

Profiling cannot simply send everything at once — the catalog decides which
columns get profiled, and text re-typing decides which get profiled *again*. So
it walks the build collecting SQL, runs that batch, and walks again, resolving
one dependency layer per round. And because `exapump` abandons the rest of a
batch at the first failing statement, `assets/db.py` records the failure,
re-runs the remainder, and repeats: one process when nothing fails, and never
worse than the old behaviour when everything does. The resulting schema card is
byte-identical to the unbatched one.

## Why it argues with you

The value is in what it refuses.

- **Additivity decides aggregation.** A rate is never summed, a stock is never
  summed across time, a row attribute is never summed across a join. This is
  enforced in code, not left to care.
- **Refuse rather than substitute.** If the persona's subject is not in the
  data, it stops and says so instead of charting whatever columns exist.
- **Flat is a finding.** A metric with no variation is cut, and the flatness is
  reported — on TPC-H, on-time delivery is 63.2% across every dimension because
  the dates are independent random offsets. That is worth knowing; the chart was
  not.
- **Guesses are labelled.** Low-confidence classifications carry the check a
  human needs to make.

Worked examples, on a Global Superstore extract: trailing-12-month sales
$4.30M against profit $504K, with **$811K sold below cost**. On a fulfilment
persona over the same table, cycle time varies 190% across Ship Mode but 1.0%
across Segment — so the lever is routing, not account management, and the
per-segment chart would have been four identical bars.

## Known limits

Read the "Known limits" section of `CHANGES.md` before assuming this is
universal. The headlines:

- The text-to-SQL panel's fallback is **English keyword matching**, not
  language understanding. Real semantics needs an `ANTHROPIC_API_KEY` — see
  `CHANGES.md` item 14 for how the key is resolved and why an exported
  environment variable alone does not reach dash-server.
- The SQL is **Exasol dialect**. Portable across datasets, not across databases.
- The fallback panel queries the fact table only; joined dimensions are
  available to the charts and to the model path.
- On **Windows**, dash-server's `app_deploy_draft` is blocked by a bug in the
  add-on, not in this skill: its `sql_smoke` probe builds keys with OS
  separators (`queries\business\kpi.sql`) but normalises the config keys of
  `queries/sql_smoke.json` to forward slashes, so no config can ever match and
  every parameterised query reports "Missing values". Build, confirm the
  `data_layer` probe passes, then `app_promote_revision`. Full detail in
  `DEPLOY.md`.
- Verified on two single-table datasets of opposite shape. Multi-table joins are
  handled by design but were not re-tested after the most recent changes.

## Files

```
get.sh                    the curl one-liner (macOS/Linux/WSL): clone, then install.py
get.ps1                   the same for PowerShell: irm ... | iex
install.py                one-shot install: skill + key + preflight
preflight.py              verify every prerequisite; exit 1 if the demo will break
setup_llm_key.py          store the Anthropic key owner-only; hidden prompt,
                          clipboard, --key-file or piped stdin
SKILL.md                  the procedure the agent follows
README.md                 this file
DEPLOY.md                 prerequisites and the deploy recipe — read before first use
CHANGES.md                fix log, verification notes, and known limits
assets/profile_schema.py  stage 3 — schema card
assets/derive_metrics.py  stage 4 — metric grammar and the additivity matrix
assets/signal_check.py    stage 5 — signal test
assets/build_dashboard.py stage 6 — Dash app, queries, shareable snapshot
assets/db.py              batched SQL execution; one process, not one per query
assets/prelude.py         shared design tokens, so dashboards read as one system
references/               semantic roles, persona axes, refusal, coverage, scale
```
