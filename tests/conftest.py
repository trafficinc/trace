import pytest
from apps.accounts.models import User
from apps.engagements.models import Engagement, EngagementMembership


def pytest_configure(config):
    from django.conf import settings
    if settings.SETTINGS_MODULE != "config.settings.test":
        raise pytest.UsageError("TRACE tests require config.settings.test; production/development databases are forbidden. Use the dedicated PostgreSQL integration helper.")


@pytest.fixture
def access_setup(db):
    users = {role: User.objects.create_user(role) for role in ("lead", "tester", "reviewer", "viewer", "outsider")}
    users["admin"] = User.objects.create_superuser("admin")
    first = Engagement.objects.create(name="First engagement")
    second = Engagement.objects.create(name="Second engagement")
    for role in ("lead", "tester", "reviewer", "viewer"):
        EngagementMembership.objects.create(engagement=first, user=users[role], role=role)
    EngagementMembership.objects.create(engagement=second, user=users["lead"], role="viewer")
    EngagementMembership.objects.create(engagement=second, user=users["outsider"], role="lead")
    return users, first, second


@pytest.fixture(autouse=True, scope="session")
def audit_test_database_flush():
    """Disable FK-backed audit deletion guards only during disposable DB flush."""
    from django.db.backends.sqlite3.operations import DatabaseOperations
    original = DatabaseOperations.execute_sql_flush

    def flush(self, sql_list):
        with self.connection.constraint_checks_disabled():
            return original(self, sql_list)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(DatabaseOperations, "execute_sql_flush", flush)
        yield
