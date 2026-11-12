# AI usage, cost and billing

## What was found on this server

- Claude Code 2.1.322 is installed and signed in with a **claude.ai subscription login (Pro plan)**.
- There is **no Anthropic API key** in the environment or in this project.
- So the only AI execution method available without new credentials is the local CLI in headless
  mode (`claude -p`), which draws on the subscription's usage allowance. It is not billed per call,
  but it does consume the same limits you use interactively.

Subscription logins are meant for your own use of Claude. Running the CLI unattended from a
background service is a decision for you, not something this system assumes. Therefore:

## Default: AI is off

`SONIC_AI_MODE=off`. With AI off the system still does everything except writing free text:

| Function | Without AI | With AI |
|---|---|---|
| Discovery, dedupe, verification | Scripts | Scripts (never AI) |
| Eligibility, visa evidence, fit score | Rules | Rules, plus optional deeper review of chosen jobs |
| Cover letter | Plain factual template from your profile | Written from your profile facts |
| Free-text questions ("Why us?") | Left for you to answer | Drafted from your profile facts, marked "Generated — check it" |
| Form filling, approval, submission | Scripts | Scripts (never AI) |

## Turning it on (two switches, both required)

1. Server: set `SONIC_AI_MODE=claude_cli` in `.env`, then
   `sudo systemctl restart sonic-jobs-api sonic-jobs-worker`. This cannot be changed from the browser.
2. Dashboard: Settings → AI → "Use AI when preparing applications".

Automatic review of new strong matches is a third, separate switch and is off by default.

## How calls are kept small and safe

- AI never runs during discovery. It runs when you prepare an application or press "AI review",
  and optionally for new jobs above a star threshold.
- Every call is one request with **all tools disabled**, no session saved, in an empty directory.
- Results are cached by content: asking the same thing twice costs nothing.
- Budgets (Settings → AI): daily and monthly limits on calls and on estimated cost. Defaults:
  25 calls / day, 300 / month, $1 / day, $10 / month. When a limit is hit, AI stops and everything
  else continues. Failed calls are not retried in a loop.
- Model: `haiku` by default (`SONIC_AI_MODEL`). One measured test call used 590 input and 15 output
  tokens and took about 3 seconds.
- Every call is logged in `ai_usage` and shown in Analytics → AI usage.

## About the cost figures

The CLI reports an API-equivalent cost per call. Under a subscription login that figure is an
**estimate of consumption**, not a charge. It is labelled "Est. cost" everywhere.

Rough size of one application preparation: about 3–5K input tokens (profile + job text) and
300–600 output tokens. With the default model that is a fraction of a cent API-equivalent.

## Paid API billing

Not implemented and never used. The CLI is started with any `ANTHROPIC_*` variables removed from
its environment, so it cannot fall back to an API key. If you later want metered API billing
instead of the subscription, that would be a new `SONIC_AI_MODE` value added on purpose
(see ROADMAP), with your key and your approval.

## Truthfulness guards

- The model receives only your profile facts and the job text, and is told to return `null` when
  the facts do not cover a question.
- A visa status proposed by the model is accepted only if its quote appears word for word in the
  official posting; otherwise the classification is unchanged and the note is labelled
  "AI interpretation".
- Everything generated is shown with its source label and needs your approval before sending.
