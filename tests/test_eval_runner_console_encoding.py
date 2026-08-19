"""
The eval runner must be able to print whatever the model emitted.

Regression coverage for a crash found while re-measuring the eval token
budget: on Windows the default console codec is cp1252, the current model
(openai/gpt-oss-120b) emits characters outside it -- U+2011 NON-BREAKING
HYPHEN was the one that hit -- and the plain `print` in
print_scenario_transcripts raised UnicodeEncodeError, killing the run
mid-pass. The real API calls had already been paid for and no summary
table was printed, so a completed eval was lost to a console codec.

These tests deliberately do NOT call the LLM. They exercise only the
console-encoding guard, so they are free, deterministic, and safe to keep
in the normal test suite even though evals/ itself is a manual tool.

A subprocess is required: the parent pytest process has already fixed its
own streams, and sys.stdout's encoding cannot be meaningfully un-fixed
in-process.
"""

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The exact character that crashed the real run, plus the other
# non-cp1252 characters this model routinely emits.
UNENCODABLE_IN_CP1252 = "‑"          # non-breaking hyphen -- the real one
ALSO_EMITTED = "—‘’“”"  # em dash, curly quotes


def _run_child(program: str, encoding: str) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = encoding

    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        timeout=120,
    )


class TestEvalRunnerSurvivesNonCp1252ModelOutput(unittest.TestCase):
    def test_plain_print_under_cp1252_really_does_crash(self):
        """
        Precondition. Without this, the test below could pass simply
        because the environment never had the problem, and would silently
        stop protecting anything.
        """
        result = _run_child(
            f"print({UNENCODABLE_IN_CP1252!r})",
            encoding="cp1252",
        )

        self.assertNotEqual(
            result.returncode, 0,
            "Expected an unencodable character to crash a plain print under "
            "cp1252; if this environment no longer does, this test file's "
            "premise needs revisiting.",
        )
        self.assertIn(b"UnicodeEncodeError", result.stderr)

    def test_importing_the_runner_makes_that_same_print_succeed(self):
        program = (
            "import evals.run_conversation_evals\n"
            f"print({UNENCODABLE_IN_CP1252 + ALSO_EMITTED!r})\n"
        )
        result = _run_child(program, encoding="cp1252")

        self.assertEqual(
            result.returncode, 0,
            f"The eval runner did not make model output printable.\n"
            f"stderr:\n{result.stderr.decode('utf-8', 'replace')}",
        )
        self.assertNotIn(b"UnicodeEncodeError", result.stderr)

        printed = result.stdout.decode("utf-8", "replace")
        self.assertIn(UNENCODABLE_IN_CP1252, printed)

    def test_streams_are_utf8_after_import(self):
        program = (
            "import sys\n"
            "import evals.run_conversation_evals\n"
            "print(sys.stdout.encoding, sys.stderr.encoding)\n"
        )
        result = _run_child(program, encoding="cp1252")

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout.decode().strip(), "utf-8 utf-8")

    def test_transcript_printer_handles_model_text_end_to_end(self):
        """
        Exercises the real print path that crashed
        (print_scenario_transcripts), rather than a bare print -- with a
        hand-built result object, so no LLM call is made.
        """
        program = (
            "import evals.run_conversation_evals as r\n"
            "scenario = r.Scenario(\n"
            "    name='encoding_probe',\n"
            "    messages=['hi'],\n"
            "    checks=[],\n"
            ")\n"
            "turn = r.TurnResult(\n"
            "    user_message='hi',\n"
            f"    response='pre{UNENCODABLE_IN_CP1252}qualified "
            f"{ALSO_EMITTED}',\n"
            "    crashed=False,\n"
            ")\n"
            "run = r.RunResult(conversation_id='c1', turns=[turn])\n"
            "r.print_scenario_transcripts(scenario, [run])\n"
        )
        result = _run_child(program, encoding="cp1252")

        self.assertEqual(
            result.returncode, 0,
            f"print_scenario_transcripts crashed on model text.\n"
            f"stderr:\n{result.stderr.decode('utf-8', 'replace')}",
        )
        self.assertIn(
            UNENCODABLE_IN_CP1252, result.stdout.decode("utf-8", "replace")
        )


if __name__ == "__main__":
    unittest.main()
