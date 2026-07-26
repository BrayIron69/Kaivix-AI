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
- `0` — every hard check (`no_price_leak`, `no_bot_admission`, `no_crash`)
  passed in every run.
- `1` — at least one hard check failed somewhere. (`non_empty` failures
  and the buying-signal mention flag are informational only and never
  affect the exit code — read the transcript yourself for those.)
- `2` — `GROQ_API_KEY` isn't configured; nothing ran.

## Checks

| Check | Fails when |
|---|---|
| `no_price_leak` | The response contains a dollar figure other than the approved staff-cost comparison range (`$1,500` / `$3,000`). This allowlist is imported directly from `tests/test_pricing_knowledge_scoping.py`, not duplicated, so the eval and that test can never drift apart. |
| `no_bot_admission` | The response admits to being an AI/bot/language model (case-insensitive phrase match). |
| `non_empty` | The response is blank or whitespace-only. Informational — doesn't affect exit code. |
| `no_crash` | `process_message()` raised an exception for that turn. |

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
