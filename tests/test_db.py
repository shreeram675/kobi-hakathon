from core.schemas import build_initial_state
from core.db import connect, migrate, upsert_run


def test_sqlite_migration_and_run_upsert(tmp_path):
    conn = connect(tmp_path / "kobie.sqlite3")
    migrate(conn)
    state = build_initial_state("Air India")
    upsert_run(conn, state)

    row = conn.execute("SELECT run_id, user_input FROM runs").fetchone()
    assert row["run_id"] == state["run_id"]
    assert row["user_input"] == "Air India"
