"""Phase 12.2 runs only on an empty database (D17): a migration has no user's key, so it can't
encrypt existing rows. accounts.0007 checks before any table changes."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

GUARD = ("accounts", "0007_require_empty_database")
BEFORE = [("accounts", "0006_user_birth_date")]


@pytest.fixture
def before_the_guard(transactional_db):
    """The database just before Phase 12.2. Puts the latest schema back afterwards."""
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    yield MigrationExecutor(connection).loader.project_state(BEFORE).apps
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM accounts_user")
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def migrate_to_the_end():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_a_database_with_accounts_refuses_to_migrate(before_the_guard):
    before_the_guard.get_model("accounts", "User").objects.create(email="a@example.com")
    with pytest.raises(RuntimeError, match="needs an empty database"):
        migrate_to_the_end()


def test_an_empty_database_migrates(before_the_guard):
    migrate_to_the_end()
    applied = MigrationExecutor(connection).loader.applied_migrations
    assert GUARD in applied
    assert ("transactions", "0009_encrypted_core") in applied
