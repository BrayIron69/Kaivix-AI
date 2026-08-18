import unittest

from core_ai.em_dash_filter import strip_em_dashes


class TestStripEmDashes(unittest.TestCase):
    """
    Deterministic, fixed-string tests -- no LLM involved. Every case
    asserts both the exact expected output and, separately, that no "—"
    survives, so a future change to the replacement style can't
    accidentally reintroduce one while still matching a stale exact
    string.
    """

    def _assert_clean(self, result: str) -> None:
        self.assertNotIn("—", result)

    # -- No em dash present --------------------------------------------

    def test_no_em_dash_returns_text_unchanged(self):
        text = "We build custom AI agents for support and lead qualification."
        self.assertEqual(strip_em_dashes(text), text)

    def test_empty_string_returns_empty_string(self):
        self.assertEqual(strip_em_dashes(""), "")

    def test_none_input_returns_none(self):
        self.assertIsNone(strip_em_dashes(None))

    # -- Single em dash: split into a separate sentence -----------------

    def test_single_em_dash_mid_sentence_spaced(self):
        text = "It works around the clock — no breaks, no sick days."
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(result, "It works around the clock. No breaks, no sick days.")

    def test_single_em_dash_no_surrounding_spaces(self):
        text = "It works around the clock—no breaks, no sick days."
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(result, "It works around the clock. No breaks, no sick days.")

    def test_single_em_dash_asymmetric_spacing(self):
        text = "It works around the clock —no breaks, no sick days."
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(result, "It works around the clock. No breaks, no sick days.")

    def test_single_em_dash_at_start_of_string(self):
        text = "—that's the short version."
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(result, "That's the short version.")

    def test_single_em_dash_at_end_of_string(self):
        text = "It just works—"
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(result, "It just works.")

    def test_single_em_dash_followed_by_non_letter_is_not_capitalized(self):
        text = "The rough shape is a setup fee plus a retainer—$1,500 to $3,000 a month."
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(
            result,
            "The rough shape is a setup fee plus a retainer. $1,500 to $3,000 a month.",
        )

    # -- Multiple em dashes: replaced with commas ------------------------

    def test_two_em_dashes_become_commas(self):
        text = "Bray — our AI sales agent — is available 24/7."
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(result, "Bray, our AI sales agent, is available 24/7.")

    def test_two_em_dashes_no_surrounding_spaces(self):
        text = "Bray—our AI sales agent—is available 24/7."
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(result, "Bray, our AI sales agent, is available 24/7.")

    def test_three_em_dashes_all_become_commas(self):
        text = "It qualifies leads—answers questions—books demos—all day."
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(result, "It qualifies leads, answers questions, books demos, all day.")

    # -- Realistic multi-sentence response -------------------------------

    def test_em_dash_in_a_realistic_multi_sentence_response(self):
        text = (
            "Great question. An AI employee works differently than a tool—it's "
            "trained specifically on your business and runs on its own. Most "
            "clients recover the cost quickly through saved time alone."
        )
        result = strip_em_dashes(text)
        self._assert_clean(result)
        self.assertEqual(
            result,
            "Great question. An AI employee works differently than a tool. It's "
            "trained specifically on your business and runs on its own. Most "
            "clients recover the cost quickly through saved time alone.",
        )

    # -- Never-contains-one invariant, swept across every case above ----

    def test_no_case_above_ever_leaves_an_em_dash(self):
        samples = [
            "We build custom AI agents for support and lead qualification.",
            "",
            "It works around the clock — no breaks, no sick days.",
            "It works around the clock—no breaks, no sick days.",
            "It works around the clock —no breaks, no sick days.",
            "—that's the short version.",
            "It just works—",
            "The rough shape is a setup fee plus a retainer—$1,500 to $3,000 a month.",
            "Bray — our AI sales agent — is available 24/7.",
            "Bray—our AI sales agent—is available 24/7.",
            "It qualifies leads—answers questions—books demos—all day.",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self._assert_clean(strip_em_dashes(sample))


if __name__ == "__main__":
    unittest.main()
