"""Shared Flask extension instances (initialised in the app factory)."""
import sqlite3 as _sqlite3
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.query import Query
from flask_migrate import Migrate
from sqlalchemy import event as _sa_event
from sqlalchemy.engine import Engine as _SA_Engine

class CompatibleQuery(Query):
    """Backward-compatible query API with modern primary-key lookup semantics."""

    def get(self, ident):
        entity = self.column_descriptions[0].get('entity') if self.column_descriptions else None
        return self.session.get(entity, ident) if entity is not None else super().get(ident)


db = SQLAlchemy(query_class=CompatibleQuery)
migrate = Migrate()


@_sa_event.listens_for(_SA_Engine, "connect")
def _sqlite_concurrency_pragmas(dbapi_connection, connection_record):
    """Harden SQLite for multi-user use. No effect on PostgreSQL.

    - WAL journal mode: readers no longer block on a concurrent writer, so a
      cashier saving an invoice doesn't lock out reception/lab reads.
    - busy_timeout: a second writer waits up to 5s for the lock instead of
      immediately failing with 'database is locked'.
    - synchronous=NORMAL: safe and faster under WAL.

    NOTE: FK enforcement (PRAGMA foreign_keys=ON) is deliberately NOT set here.
    SQLite ran with it OFF historically, so enabling it would surface pre-existing
    referential gaps as hard errors in working flows. Turning it on safely is a
    separate, planned correctness effort with a data audit first.
    """
    if isinstance(dbapi_connection, _sqlite3.Connection):
        cur = dbapi_connection.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
            # Referential integrity is OPT-IN (default off for backward compatibility
            # with existing databases). Set SQLITE_FK=1 to enforce foreign keys —
            # recommended for fresh installs after a referential-integrity audit.
            import os as _os
            if _os.environ.get('SQLITE_FK', '0') == '1':
                cur.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        finally:
            cur.close()
