from django.db import connection


def mutation_lock():
    """PostgreSQL parity with SQLite IMMEDIATE ordering; never a content retry.

    Transaction-scoped and reentrant. Keep this before reading mutable policy
    state. Reads outside explicit transactions take no advisory lock.
    """
    if connection.vendor=='postgresql' and connection.in_atomic_block:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(763834901)')
