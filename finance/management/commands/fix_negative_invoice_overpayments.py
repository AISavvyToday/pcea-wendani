from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from finance.models import Invoice
from payments.models import PaymentAllocation


class Command(BaseCommand):
    help = (
        "Fix invoices that have negative balances because amount_paid exceeds the invoice due. "
        "Clamps invoice balance to 0, caps invoice.amount_paid to amount due, and moves the excess to student.credit_balance."
    )

    def add_arguments(self, parser):
        parser.add_argument('--invoice-number', required=True, help='Invoice number to fix')
        parser.add_argument('--dry-run', action='store_true', help='Show what would change without writing')

    @transaction.atomic
    def handle(self, *args, **options):
        invoice_number = options['invoice_number']
        dry_run = options['dry_run']

        try:
            invoice = Invoice.objects.select_for_update().select_related('student').get(invoice_number=invoice_number)
        except Invoice.DoesNotExist:
            raise CommandError(f'Invoice not found: {invoice_number}')

        student = invoice.student
        allocations_total = (
            PaymentAllocation.objects.filter(
                is_active=True,
                invoice_item__invoice=invoice,
                payment__is_active=True,
            ).aggregate(total=Sum('amount'))['total']
            or Decimal('0.00')
        )

        total_due = (
            (invoice.total_amount or Decimal('0.00'))
            + (invoice.balance_bf or Decimal('0.00'))
            - (invoice.prepayment or Decimal('0.00'))
        )
        total_due = max(total_due, Decimal('0.00'))

        excess = max(allocations_total - total_due, Decimal('0.00'))
        new_amount_paid = min(allocations_total, total_due)
        new_balance = max(total_due - new_amount_paid, Decimal('0.00'))
        new_credit = (student.credit_balance or Decimal('0.00')) + excess

        self.stdout.write(f'Invoice: {invoice.invoice_number}')
        self.stdout.write(f'Student: {student.admission_number} {student.full_name}')
        self.stdout.write(f'Current invoice.amount_paid: {invoice.amount_paid}')
        self.stdout.write(f'Current invoice.balance: {invoice.balance}')
        self.stdout.write(f'Allocations total: {allocations_total}')
        self.stdout.write(f'Total due: {total_due}')
        self.stdout.write(f'Excess overpayment: {excess}')
        self.stdout.write(f'Current student.credit_balance: {student.credit_balance}')
        self.stdout.write(f'New student.credit_balance: {new_credit}')
        self.stdout.write(f'New student.outstanding_balance: 0.00')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run only; no data modified.'))
            return

        if excess <= 0 and invoice.balance >= 0:
            self.stdout.write(self.style.SUCCESS('No negative overpayment issue found. Nothing to fix.'))
            return

        invoice.amount_paid = new_amount_paid
        invoice.balance = new_balance
        if invoice.balance == 0:
            invoice.status = 'paid'
        elif invoice.amount_paid > 0:
            invoice.status = 'partial'
        invoice.save(update_fields=['amount_paid', 'balance', 'status', 'updated_at'])

        student.credit_balance = new_credit
        student.outstanding_balance = Decimal('0.00')
        student.save(update_fields=['credit_balance', 'outstanding_balance', 'updated_at'])

        self.stdout.write(self.style.SUCCESS('Fixed negative invoice overpayment successfully.'))
