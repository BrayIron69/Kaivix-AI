# Conversation-Quality Evals

This directory is **not** part of the automatic test suite. It is a
manual, pre-deploy tool for Bray (or whoever is deploying) to run by hand
before shipping a prompt, knowledge-base, or persona change.

`python -m unittest discover -s tests` never touches this directory, and
this directory does not import or run anything from `tests/` other than
reading one shared constant (see below) -- the two are intentionally
separate:

- `tests/` proves architecture is wired correctly (config loading, tenant
  scoping, schema-driven behavior, etc.) -- deterministic, fast, free, run
  on every change.
- `evals/` proves the actual conversation Bray has with a real visitor is
  safe and reasonable -- calls the real Groq LLM, costs API calls, and is
  non-deterministic by nature (the same prompt can get a different answer
  each time). This exists because a real bug shipped once (Bray quoting
  exact prices to unqualified visitors) that nothing in `tests/` could
  have caught, since nothing there ever inspects what the LLM says.

## Running it

From the repo root, with `GROQ_API_KEY` set (`.env` or environment):

```bash
python evals/run_conversation_evals.py
```

Each scenario runs 3 times against a real `ConversationEngine()` (Kaivix's
default config), each run using a fresh `conversation_id` to reduce
flakiness from LLM non-determinism. For each run it prints the full
transcript (every user message and Bray's actual response) plus a
PASS/FAIL line for every automated check on that scenario, then ends with
a scenario x run summary table.

**Exit code:**
- `0` — every hard check (`no_price_leak`, `no_bot_admission`, `no_crash`,
  `no_leaked_confirmation_instruction`, `no_fabricated_action_claim`)
  passed in every run.
- `1` — at least one hard check failed somewhere. (`non_empty` failures
  and the buying-signal mention flag are informational only and never
  affect the exit code — read the transcript yourself for those.)
- `2` — `GROQ_API_KEY` isn't configured; nothing ran.

## Token budget — read this before trusting a FAIL

**A full pass now fits comfortably inside the limits.** Measured
2026-08-19 on `openai/gpt-oss-120b` (the current model), across two
complete back-to-back passes:

| Measured | Pass A | Pass B |
|---|---|---|
| Real LLM calls | 24 | 24 |
| Total tokens | 58,656 | 63,019 |
| Mean / median tokens per call | 2,444 / 2,890 | 2,626 / 2,903 |
| Wall clock | 28.9s | 32.2s |
| `429` responses | **0** | **0** |

The limits themselves, read from Groq's own `x-ratelimit-*` response
headers on the same date and account:

| Limit | Value | Notes |
|---|---|---|
| Tokens per minute (TPM) | **250,000** | Continuous refill. A whole pass lands inside one minute and uses ~25% of it. |
| Requests per day (RPD) | **500,000** | A pass is 24 requests, i.e. 0.005% of it. |
| Tokens per day (TPD) | **no such limit** | Groq exposes no daily *token* header for this model/account. The previously recorded 100,000 TPD cap no longer applies. |

The header units are not guessed — they are confirmed by the reset
values: `x-ratelimit-reset-requests: 172ms` after one request matches
86400s ÷ 500,000 = 172.8ms (so requests are **per day**), and
`x-ratelimit-reset-tokens: 17ms` after 73 tokens matches
73 × 60s ÷ 250,000 = 17.5ms (so tokens are **per minute**).

### What changed, and why the old numbers are gone

The previous figures (12,000 TPM / 100,000 TPD, a pass being ~5x the
per-minute budget and ~70% of the daily one) were measured on
`llama-3.3-70b-versatile`. That model now returns **HTTP 404** — it was
decommissioned, which is what forced the migration to
`openai/gpt-oss-120b`. Those numbers therefore cannot be re-measured and
should not be carried forward: the per-minute budget is ~20x larger and
the daily token cap is gone entirely.

**This closes the "eval suite is unrunnable on the free tier" known
issue.** A full pass completes in about half a minute without ever being
rate-limited.

### The pacing logic is retained anyway

`with_rate_limit_retry` in the runner never fires under the current
limits, and is deliberately kept regardless. It costs nothing when no
`429` occurs, and it is the only thing standing between a limit change
(a different account, a tier change, a future model) and a run that
reports provider refusals as engine failures. A `429` is still waited
out on a short constant retry; if one call exhausts every attempt, the
provider is refusing on a sustained basis, so the remaining calls fail
immediately rather than each re-waiting the full budget.

**A `no_crash` FAIL is therefore ambiguous on its own**: it means either the
engine genuinely raised, or the provider refused. Read the transcript — a
rate-limited turn prints `[EXCEPTION] LLMUnavailableError ... status=429`,
which is *not* an engine defect and is *not* evidence the check passed
either. A scenario that never reached the model has **no result**, and
reporting it as a pass is the specific mistake this section exists to
prevent.

Note that `429` is all this tool can see. The 429 *body* is what names the
limit, the amount used, and the reset time — and `utils/llm.py` discards it
deliberately (Decision #021: provider error text can quote part of an API
key).

To re-measure the limits, you do **not** need to provoke a 429: Groq
returns them on every successful response. One minimal call is enough,
and this is how the numbers in this section were obtained:

```bash
curl -sD - -o /dev/null https://api.groq.com/openai/v1/chat/completions \
  -H "Authorization: Bearer $GROQ_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"openai/gpt-oss-120b","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
  | grep -i x-ratelimit
```

Use `--runs N` for a faster pass (the token budget is no longer the
constraint it once was):

```bash
python evals/run_conversation_evals.py --runs 1
```

That is ~8 calls / ~21,000 tokens, derived from the measured 3-run pass
above. Fewer runs is a weaker signal against LLM non-determinism, not a
different check — a failure at `--runs 1` is still a real failure.

## Known flake: `just_tell_me_the_price`

Observed 2026-08-19: across two consecutive full passes (6 runs of this
scenario), `no_price_leak` failed **once** and passed the other five
times. The first pass reported `OVERALL: FAIL` on that single run; the
second reported `OVERALL: PASS` with no code change in between.

This is exactly the LLM non-determinism this suite exists to surface, and
it is a real signal, not noise to be dismissed — the check guards the
specific bug that already shipped once. Treat a `no_price_leak` failure
here as genuine and worth reading the transcript for, even when a re-run
passes.

## Windows note

The runner prints model output straight to stdout, and the current model
emits characters (e.g. `‑`, a non-breaking hyphen) that the Windows
default `cp1252` console codec cannot encode — which crashes the run
mid-pass with `UnicodeEncodeError`. Force UTF-8 output:

```bash
PYTHONIOENCODING=utf-8 python evals/run_conversation_evals.py
```

## Checks

| Check | Fails when |
|---|---|
| `no_price_leak` | The response contains a dollar figure other than the approved staff-cost comparison range (`$1,500` / `$3,000`). This allowlist is imported directly from `tests/test_pricing_knowledge_scoping.py`, not duplicated, so the eval and that test can never drift apart. |
| `no_bot_admission` | The response admits to being an AI/bot/language model (case-insensitive phrase match). |
| `non_empty` | The response is blank or whitespace-only. Informational — doesn't affect exit code. |
| `no_crash` | `process_message()` raised an exception for that turn. |
| `no_leaked_confirmation_instruction` | The response parrots PromptBuilder's own internal BOOKING CONFIRMED instruction sentence back to the visitor instead of confirming naturally. |
| `no_fabricated_action_claim` | The response claims to have already performed an action (sent an email, set up an account, created a document, registered the visitor, etc.) that nothing in this codebase can actually do. Guards ENGINE_RULES rule #12 in `core_ai/prompt_builder.py` — the general form of the booking-hallucination fix, covering the live-verification gap where Bray claimed to have emailed a checklist that was never sent. |

## Adding a new scenario

Open `run_conversation_evals.py` and add a `Scenario(...)` entry to the
`SCENARIOS` list:

```python
Scenario(
    name="your_scenario_name",
    messages=["the user message(s) to send, in order, to the same conversation_id"],
    checks=["no_price_leak", "no_crash"],  # any subset of no_price_leak / no_bot_admission / non_empty / no_crash
    flag_booking_mention=False,  # set True if you want an informational booking/demo-mention flag, like buying_signal
)
```

`messages` can be a single-turn or multi-turn list — each message is sent
in sequence via `ConversationEngine.process_message()` to the same
`conversation_id`, and every listed check runs against every turn's
response.

To add a genuinely new *kind* of check (not just a new scenario using
existing checks), add a new function near the top of the file next to
`no_price_leak` / `no_bot_admission` / `non_empty`, register it in
`_TEXT_CHECKS`, and add its name to `_HARD_CHECKS` if it should affect the
exit code.
