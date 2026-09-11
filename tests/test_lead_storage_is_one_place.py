"""
Everything that touches leads must land in the SAME database.

A real production bug, found by capturing a lead through the live site
and then failing to find it in the dashboard: ConversationEngine passes
the business's configured crm_provider and wrote to Postgres, while
api/routers/admin.py and api/routers/leads.py construct a bare
LeadService() which defaulted to "sqlite" and read the ephemeral file.
The logs said "[LeadService] Lead saved." and the admin page returned
404 for the same address, at the same moment.

Before leads moved to Postgres this was harmless -- both sides happened
to default to the same SQLite file, so the inconsistency was invisible.
That is exactly why it needs a test rather than care.
"""

import unittest
from unittest.mock import patch

from crm.registry import get_crm_provider
from crm.sqlite_crm import SQLiteCRM
from services.lead_service import DEFAULT_CRM_PROVIDER, LeadService


class TestTheDefaultFollowsTheDeployment(unittest.TestCase):
    def test_default_is_not_a_hardcoded_backend(self):
        """
        A default naming one concrete backend is what allowed the reader
        and the writer to disagree. It has to resolve, not assert.
        """
        self.assertEqual(DEFAULT_CRM_PROVIDER, "internal")

    @patch.dict("os.environ", {}, clear=True)
    def test_with_no_database_url_a_bare_leadservice_is_still_sqlite(self):
        """Local development and this suite must be completely unaffected."""
        self.assertIsInstance(LeadService().crm, SQLiteCRM)

    @patch.dict("os.environ", {}, clear=True)
    def test_the_admin_reader_and_the_engine_writer_agree(self):
        """
        The actual property that broke. Whatever backend the engine's
        configured provider resolves to, a bare LeadService() -- what
        both admin.py and leads.py construct -- must resolve to the same
        one.
        """
        from core_ai.business_config import BusinessConfigRepository, DEFAULT_BUSINESS_ID

        configured = (
            BusinessConfigRepository().load(DEFAULT_BUSINESS_ID).providers.crm_provider
        )

        writer = get_crm_provider(configured)
        reader = LeadService().crm

        self.assertIs(type(writer), type(reader))

    def test_an_explicit_provider_still_wins(self):
        self.assertIsInstance(LeadService(crm_provider="sqlite").crm, SQLiteCRM)


if __name__ == "__main__":
    unittest.main()
