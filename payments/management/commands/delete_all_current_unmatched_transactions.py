from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

from payments.models import BankTransaction


class Command(BaseCommand):
    help = "Delete all currently unmatched bank transactions (payment is null and not matched/processing)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        queryset = BankTransaction.objects.filter(
            payment__isnull=True,
            is_active=True,
        ).exclude(
            processing_status__in=["matched", "processing"],
        )

        count = queryset.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No unmatched transactions found."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: Would delete {count} unmatched transaction(s)."))
            for txn in queryset.order_by('-callback_received_at')[:20]:
                self.stdout.write(
                    f"  - {txn.transaction_id} | {txn.gateway} | KES {txn.amount} | {txn.callback_received_at}"
                )
            if count > 20:
                self.stdout.write(f"  ... and {count - 20} more")
            return

        with db_transaction.atomic():
            deleted, _ = queryset.delete()
        self.stdout.write(self.style.SUCCESS(f"Successfully deleted {deleted} unmatched transaction(s)."))
