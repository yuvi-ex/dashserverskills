# persona-metrics

Build a dashboard from a **role**, not from a list of metrics.

You say *"build a dashboard for the CFO"* — or for a warehouse shift lead, a
clinical trial coordinator, a head of trust and safety — and this derives what
that person needs **from the dataset actually in front of it**, then builds and
deploys a live dashboard on your local Exasol database.

There is no file of pre-written CFO metrics here. A catalogue only answers for
the personas someone remembered to write down, on the schemas they had in mind.
This runs a procedure instead, so an arbitrary persona meets an arbitrary
dataset and the answer is derived rather than recalled.

## Install

Clone, then run this **in a terminal** — once:

```sh
./install.sh
```

It installs the skill where the agent looks for it, then prompts for the
Anthropic API key with the input hidden, and finishes with a preflight.

The key prompt is interactive by design. A hidden prompt cannot be read from an
editor or agent console, and a key pasted into a chat transcript has to be
rotated — so the key goes from your keyboard straight to a `600` file and is
never echoed, logged, or printed. Pressing Enter skips it: the dashboards still
work, and the Ask-the-data panel falls back to keyword matching until a key is
present.

Check the machine at any time:

```sh
./preflight.sh      # exit 0 = ready, exit 1 = something will break
```


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
4. **This skill** — unzip into `.claude/skills/`
5. **A model key, for semantic text-to-SQL** — `./setup-llm-key.sh`.
   Optional but strongly recommended: without it the Ask-the-data panel matches
   keywords, and fails on plurals, synonyms and intent words.
6. **An AI client with shell access** (Claude Code). This skill is
   *agent-operated*: something has to run `exapump`, run the pipeline, and drive
   dash-server's control plane. A chat-only client cannot use it.

The `dash-server` *skill* arrives with the kit in step 1 — you do not install
that separately. Read the real port from `exakit info`: the add-on's default is
5100, but it moves if that port is taken.

## Using it

Ask in plain language — *"build a dashboard for a sales manager from
STARTER_KIT.STORESALES"* — and the agent runs the pipeline. To drive it by hand:

```bash
# 3. profile the schema into a card
python3 assets/profile_schema.py <SCHEMA> --json card.json

# 4. derive metrics for a persona spec you wrote (see references/persona-axes.md)
python3 assets/derive_metrics.py --card card.json --persona persona.json --json plan.json

# 5. cut the metrics that carry no signal
python3 assets/signal_check.py --card card.json --plan plan.json --json signal.json

# 6. build the workspace
python3 assets/build_dashboard.py --card card.json --plan plan.json \
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
- Verified on two single-table datasets of opposite shape. Multi-table joins are
  handled by design but were not re-tested after the most recent changes.

## Files

```
install.sh                one-shot install: skill + key prompt + preflight
preflight.sh              verify every prerequisite; exit 1 if the demo will break
setup-llm-key.sh          store the Anthropic key in a 600 file, input hidden
SKILL.md                  the procedure the agent follows
README.md                 this file
DEPLOY.md                 prerequisites and the deploy recipe — read before first use
CHANGES.md                fix log, verification notes, and known limits
assets/profile_schema.py  stage 3 — schema card
assets/derive_metrics.py  stage 4 — metric grammar and the additivity matrix
assets/signal_check.py    stage 5 — signal test
assets/build_dashboard.py stage 6 — Dash app, queries, shareable snapshot
assets/prelude.py         shared design tokens, so dashboards read as one system
references/               semantic roles, persona axes, refusal, coverage, scale
```
