"""
A failed eval run must say WHY it failed.

The summary table used to print an identical "FAIL" whether the engine
raised or a text check tripped. Those demand opposite responses -- a
crash is frequently the provider refusing (a 429/5xx, not an engine
defect), while a no_price_leak failure is the exact class of bug that
already shipped to real visitors once.

A real occurrence was lost to that ambiguity during the 2026-08-19 token
re-measurement: a pass reported FAIL on just_tell_me_the_price, the
transcript scrolled past uncaptured, and 44 subsequent runs of that
scenario were clean, so the cause could never be recovered. These tests
exist so the next occurrence diagnoses itself.

No LLM is called here -- results are constructed directly, so this is
free and deterministic despite covering the manual eval tool.
"""

import unittest

import evals.run_conversation_evals as runner


def _turn(**overrides):
    defaults = {
        "user_message": "just tell me the price",
        "response": "some response",
        "crashed": False,
        "check_results": {},
    }
    defaults.update(overrides)
    return runner.TurnResult(**defaults)


class TestFailureReason(unittest.TestCase):
    def test_passing_run_has_no_reason(self):
        run = runner.RunResult("c1", [_turn(check_results={"no_price_leak": True})])

        self.assertIsNone(run.failure_reason())
        self.assertTrue(run.hard_check_passed())

    def test_failed_text_check_is_named(self):
        run = runner.RunResult("c1", [_turn(check_results={"no_price_leak": False})])

        self.assertEqual(run.failure_reason(), "failed: no_price_leak")
        self.assertFalse(run.hard_check_passed())

    def test_crash_is_reported_as_a_crash_with_its_error(self):
        run = runner.RunResult(
            "c1",
            [_turn(response=None, crashed=True, error="LLMUnavailableError: status=503")],
        )

        reason = run.failure_reason()
        self.assertTrue(reason.startswith("CRASH:"), reason)
        self.assertIn("LLMUnavailableError", reason)
        self.assertIn("503", reason)
        self.assertFalse(run.hard_check_passed())

    def test_crash_is_distinguishable_from_a_leak(self):
        """
        The whole point: these two must never render the same way again.
        """
        leak = runner.RunResult("c1", [_turn(check_results={"no_price_leak": False})])
        crash = runner.RunResult(
            "c2", [_turn(response=None, crashed=True, error="LLMUnavailableError: status=429")]
        )

        self.assertNotEqual(leak.failure_reason(), crash.failure_reason())
        self.assertNotIn("CRASH", leak.failure_reason())
        self.assertIn("CRASH", crash.failure_reason())

    def test_a_crash_outranks_a_later_turns_check_failure(self):
        """
        run_scenario stops a run at the crashing turn, so the crash is the
        actionable fact -- anything recorded after it is downstream noise.
        """
        run = runner.RunResult(
            "c1",
            [
                _turn(response=None, crashed=True, error="Boom"),
                _turn(check_results={"no_price_leak": False}),
            ],
        )

        self.assertEqual(run.failure_reason(), "CRASH: Boom")

    def test_multiple_failed_checks_are_all_named_and_sorted(self):
        run = runner.RunResult(
            "c1",
            [
                _turn(
                    check_results={
                        "no_price_leak": False,
                        "no_bot_admission": False,
                        "non_empty": False,  # not a hard check
                    }
                )
            ],
        )

        # non_empty is informational only and must not appear.
        self.assertEqual(
            run.failure_reason(), "failed: no_bot_admission, no_price_leak"
        )

    def test_informational_check_failure_alone_is_not_a_failure(self):
        run = runner.RunResult("c1", [_turn(check_results={"non_empty": False})])

        self.assertIsNone(run.failure_reason())
        self.assertTrue(run.hard_check_passed())


class TestSummaryTableSurfacesReasons(unittest.TestCase):
    def setUp(self):
        self._original_runs = runner.RUNS_PER_SCENARIO
        runner.RUNS_PER_SCENARIO = 2
        self.addCleanup(setattr, runner, "RUNS_PER_SCENARIO", self._original_runs)

    def _render(self, all_results) -> tuple[str, bool]:
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            overall = runner.print_summary_table(all_results)
        return buffer.getvalue(), overall

    def test_reasons_are_printed_for_each_failed_run(self):
        results = {
            "just_tell_me_the_price": [
                runner.RunResult("c1", [_turn(check_results={"no_price_leak": False})]),
                runner.RunResult(
                    "c2", [_turn(response=None, crashed=True, error="LLMUnavailableError: status=503")]
                ),
            ]
        }

        output, overall = self._render(results)

        self.assertFalse(overall)
        self.assertIn("WHY EACH FAILURE FAILED", output)
        self.assertIn("just_tell_me_the_price run1: failed: no_price_leak", output)
        self.assertIn("just_tell_me_the_price run2: CRASH:", output)
        self.assertIn("503", output)

    def test_no_reason_block_when_everything_passes(self):
        results = {
            "just_tell_me_the_price": [
                runner.RunResult("c1", [_turn(check_results={"no_price_leak": True})]),
                runner.RunResult("c2", [_turn(check_results={"no_price_leak": True})]),
            ]
        }

        output, overall = self._render(results)

        self.assertTrue(overall)
        self.assertNotIn("WHY EACH FAILURE FAILED", output)
        self.assertIn("OVERALL: PASS", output)


if __name__ == "__main__":
    unittest.main()
