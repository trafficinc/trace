from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Enable SQLite WAL once, on local disk, with all web workers stopped."

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError("This command is only for SQLite.")
        name = str(connection.settings_dict["NAME"])
        if name == ":memory:" or name.startswith("file:"):
            raise CommandError("WAL requires a regular database file on the server's local filesystem.")
        if connection.in_atomic_block:
            raise CommandError("Run outside a transaction with application workers stopped.")
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL")
            mode = cursor.fetchone()[0]
            cursor.execute("PRAGMA busy_timeout")
            timeout = cursor.fetchone()[0]
        if mode.lower() != "wal":
            raise CommandError("SQLite did not enable WAL; verify the filesystem and running processes.")
        self.stdout.write(self.style.SUCCESS(f"SQLite journal=wal; busy_timeout={timeout} ms."))
