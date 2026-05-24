from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool
import logging
import os
import stat

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "shadi.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# The DB contains plaintext API keys and session cookies — restrict to owner read/write only.
def _restrict_db_perms():
    if os.name != "posix":
        return
    for fname in ("shadi.db", "shadi.db-wal", "shadi.db-shm"):
        p = os.path.join(os.path.dirname(DB_PATH), fname)
        if os.path.exists(p):
            try:
                os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
            except OSError as e:
                logger.warning("Could not chmod %s: %s", p, e)
_restrict_db_perms()

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Re-apply restrictive perms after the engine first opens the file (it may not exist before this point).
_restrict_db_perms()

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
