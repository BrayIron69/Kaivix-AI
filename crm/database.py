import sqlite3


DATABASE_NAME = "crm/leads.db"


def get_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,
            email TEXT NOT NULL,

            phone TEXT,

            company TEXT,
            business TEXT,

            industry TEXT,

            budget TEXT,
            timeline TEXT,

            pain_point TEXT,

            decision_maker TEXT,

            score INTEGER DEFAULT 0,

            priority TEXT DEFAULT 'Cold',

            status TEXT DEFAULT 'New',

            notes TEXT DEFAULT '',

            last_contacted TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            business_id TEXT NOT NULL DEFAULT 'kaivix',

            -- Which stored conversation produced this lead, so the admin
            -- dashboard can show the real transcript behind the extracted
            -- fields (memory/conversation_memory.db, keyed by
            -- business_id + conversation_id -- see
            -- memory/conversation_store.py).
            --
            -- Holds the MOST RECENT conversation for this lead, not every
            -- one: a returning visitor gets a fresh conversation_id per
            -- session and this column is overwritten on each sync, so
            -- earlier conversations remain in conversation_memory.db but
            -- are no longer reachable from the lead row. A full
            -- lead-to-conversations history would need its own join
            -- table; this single column is deliberately the smaller step.
            conversation_id TEXT,

            UNIQUE(business_id, email)
        )
        """
    )

    conn.commit()

    cursor.execute("PRAGMA table_info(leads)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    migrations = {
        "phone": "TEXT",
        "company": "TEXT",
        "industry": "TEXT",
        "decision_maker": "TEXT",
        "business_id": "TEXT NOT NULL DEFAULT 'kaivix'",
        # Needed here as well as in CREATE TABLE above: the table is
        # created with IF NOT EXISTS, so an existing database never
        # re-runs that statement and would otherwise never gain this
        # column. Existing rows get NULL, which the admin view renders as
        # "no stored conversation" rather than failing -- leads captured
        # before this column existed genuinely have no linked transcript.
        "conversation_id": "TEXT",
    }

    for column, column_type in migrations.items():
        if column not in existing_columns:
            cursor.execute(
                f"""
                ALTER TABLE leads
                ADD COLUMN {column} {column_type}
                """
            )

    conn.commit()
    return conn