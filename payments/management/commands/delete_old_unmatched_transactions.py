# payments/management/commands/delete_old_unmatched_transactions.py
"""
Management command to delete older unmatched bank transactions (before 13th Feb 2026).
Keeps unmatched transactions from 13th Feb 2026 onwards.

Unmatched = payment__isnull=True, excluding failed/duplicate processing status.
"""
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from payments.models import BankTransaction


# Cutoff: 13th Feb 2026 00:00:00 UTC
CUTOFF_DATE = datetime(2026, 2, 13, 0, 0, 0, tzinfo=timezone.utc)


class Command(BaseCommand):
    help = (
        "Delete unmatched bank transactions before 13th Feb 2026. "
        "Keeps unmatched transactions from 13th Feb onwards."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Unmatched: no payment linked, exclude failed/duplicate
        queryset = BankTransaction.objects.filter(
            payment__isnull=True,
            is_active=True,
        ).exclude(
            processing_status__in=["failed", "duplicate"],
        ).filter(
            callback_received_at__lt=CUTOFF_DATE,
        )

        count = queryset.count()

        if count == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "No unmatched transactions found before 13th Feb 2026."
                )
            )
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would delete {count} unmatched transaction(s) "
                    f"before 13th Feb 2026."
                )
            )
            for txn in queryset[:20]:
                self.stdout.write(
                    f"  - {txn.transaction_id} | {txn.gateway} | "
                    f"KES {txn.amount} | {txn.callback_received_at}"
                )
            if count > 20:
                self.stdout.write(f"  ... and {count - 20} more")
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("Run without --dry-run to perform deletion.")
            )
            return

        try:
            with db_transaction.atomic():
                deleted, _ = queryset.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully deleted {deleted} unmatched transaction(s) "
                    f"before 13th Feb 2026."
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Deletion failed: {e}")
            )
            raise
