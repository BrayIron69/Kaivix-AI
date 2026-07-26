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