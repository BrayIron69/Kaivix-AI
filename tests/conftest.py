"""
Suite-wide safety net: no test writes the real offered-slots database.

Thirty test files define or use an _IsolatedDatabasesMixin that redirects
crm/leads.db, memory/long_term_memory.db and memory/conversation_memory.db
at temp files. Every ConversationEngine now also constructs an offered-slot
store (scheduling/offered_slots.db), and adding a fourth line to thirty
mixins would leave the next store someone adds in exactly the same position.

This is deliberately a session-scoped autouse fixture rather than a
thirty-file edit: it cannot be forgotten by a new test file, and a test
that wants its own store still just passes one.

The problem it prevents is not hypothetical here. Commit f4bc12b records
seven mixins that isolated CRM and long-term memory but never conversation
memory, so every engine those files built wrote real rows into the real
database -- 3,478 of them across 72 conversation ids before anyone noticed,
found while verifying something unrelated rather than by inspection. A real
scheduling/offered_slots.db appeared in the working tree the first time this
store shipped, which is the same bug starting over.
"""

import os
import tempfile

import pytest

from scheduling.offered_slot_store import SQLiteOfferedSlotStore


@pytest.fixture(autouse=True, scope="session")
def _isolate_offered_slot_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)

    original = SQLiteOfferedSlotStore.DB_PATH
    SQLiteOfferedSlotStore.DB_PATH = path

    yield

    SQLiteOfferedSlotStore.DB_PATH = original
    if os.path.exists(path):
        os.remove(path)
