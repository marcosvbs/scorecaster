"""Daily SQLite backup with simple rotation.

Runs from the start.sh daily loop. Uses the stdlib sqlite3 backup API, which
is online-safe with WAL (no downtime, no torn copy), so the slim image needs
no sqlite3 CLI. Keeps the last KEEP copies on the same volume as the
database: <db>.bak.1 (newest) ... <db>.bak.KEEP (oldest).
"""

import logging
import os
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

KEEP = 3


class Command(BaseCommand):
    help = "Back up the SQLite database, keeping the last %d rotated copies." % KEEP

    def handle(self, *args, **options):
        db_path = str(settings.DATABASES["default"]["NAME"])
        if not os.path.exists(db_path):
            raise CommandError(f"Database not found at {db_path}.")

        # Rotate before writing: .bak.(KEEP-1) -> .bak.KEEP, ..., .bak.1 -> .bak.2
        for n in range(KEEP - 1, 0, -1):
            src = f"{db_path}.bak.{n}"
            if os.path.exists(src):
                os.replace(src, f"{db_path}.bak.{n + 1}")

        target = f"{db_path}.bak.1"
        source = sqlite3.connect(db_path)
        try:
            dest = sqlite3.connect(target)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

        logger.info("Database backed up to %s", target)
        self.stdout.write(self.style.SUCCESS(f"Backup written to {target}."))
