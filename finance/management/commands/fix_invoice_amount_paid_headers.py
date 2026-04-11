from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from finance.models import Invoice
from payments.models import PaymentAllocation


class Command(BaseCommand):
    help = "Fix invoice.amount_paid headers to match actual active allocations for specific invoices. Does not touch student balances."

    def add_arguments(self, parser):
        parser.add_argument('invoice_numbers', nargs='+', help='Invoice numbers to fix')
        parser.add_argument('--dry-run', action='store_true', help='Preview only')

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']

        for invoice_number in options['invoice_numbers']:
            try:
                invoice = Invoice.objects.select_for_update().get(invoice_number=invoice_number)
            except Invoice.DoesNotExist:
                raise CommandError(f'Invoice not found: {invoice_number}')

            allocations_sum = PaymentAllocation.objects.filter(
                invoice_item__invoice=invoice,
                is_active=True,
                payment__is_active=True,
                payment__status='completed',
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            old_amount_paid = invoice.amount_paid or Decimal('0.00')
            old_balance = invoice.balance or Decimal('0.00')
            total_due = (
                (invoice.total_amount or Decimal('0.00'))
                + (invoice.balance_bf or Decimal('0.00'))
                - (invoice.prepayment or Decimal('0.00'))
            )
            total_due = max(total_due, Decimal('0.00'))
            new_amount_paid = min(allocations_sum, total_due)
            new_balance = max(total_due - new_amount_paid, Decimal('0.00'))

            self.stdout.write(
                f'{invoice.invoice_number}: old_amount_paid={old_amount_paid} allocations_sum={allocations_sum} old_balance={old_balance} new_amount_paid={new_amount_paid} new_balance={new_balance}'
            )

            if dry_run:
                continue

            invoice.amount_paid = new_amount_paid
            invoice.balance = new_balance
            invoice.save(update_fields=['amount_paid', 'balance', 'updated_at'])

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run only, no changes saved.'))
        else:
            self.stdout.write(self.style.SUCCESS('Invoice header fixes applied successfully.'))
