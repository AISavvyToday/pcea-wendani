"""
Management command to fix payment allocation issue for transferred student 2374.

The issue: Payment was allocated to an invoice for a transferred student.
For transferred students, invoices should be inactive and payments should
be applied directly to outstanding_balance, not to invoices.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from students.models import Student
from finance.models import Invoice
from payments.models import Payment, PaymentAllocation
from core.models import InvoiceStatus, PaymentStatus


class Command(BaseCommand):
    help = 'Fix payment allocation for transferred student 2374'

    def add_arguments(self, parser):
        parser.add_argument(
            '--admission-number',
            type=str,
            default='2374',
            help='Admission number of student to fix'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        admission_number = options['admission_number']
        dry_run = options['dry_run']

        try:
            student = Student.objects.get(admission_number=admission_number)
        except Student.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Student {admission_number} not found'))
            return

        if student.status != 'transferred':
            self.stdout.write(
                self.style.WARNING(
                    f'Student {admission_number} is not transferred (status: {student.status}). '
                    f'Proceeding anyway...'
                )
            )

        self.stdout.write(f'\n=== Fixing student {admission_number}: {student.full_name} ===')
        self.stdout.write(f'Current status: {student.status}')
        self.stdout.write(f'Current balance_bf_original: {student.balance_bf_original}')
        self.stdout.write(f'Current outstanding_balance: {student.outstanding_balance}')
        self.stdout.write(f'Current credit_balance: {student.credit_balance}')

        # Get active invoice
        active_invoice = student.invoices.filter(is_active=True).exclude(
            status=InvoiceStatus.CANCELLED
        ).first()

        if not active_invoice:
            self.stdout.write(self.style.WARNING('No active invoice found. Checking inactive invoices...'))
            inactive_invoice = student.invoices.filter(is_active=False).exclude(
                status=InvoiceStatus.CANCELLED
            ).first()
            if inactive_invoice:
                self.stdout.write(f'Found inactive invoice: {inactive_invoice.invoice_number}')
                active_invoice = inactive_invoice
            else:
                self.stdout.write(self.style.ERROR('No invoice found at all!'))
                return

        self.stdout.write(f'\nInvoice: {active_invoice.invoice_number}')
        self.stdout.write(f'  Current is_active: {active_invoice.is_active}')
        self.stdout.write(f'  Current amount_paid: {active_invoice.amount_paid}')
        self.stdout.write(f'  Current balance: {active_invoice.balance}')
        self.stdout.write(f'  Current balance_bf: {active_invoice.balance_bf}')
        self.stdout.write(f'  Current status: {active_invoice.status}')

        # Get payment allocations for this invoice (both active and inactive)
        allocations = PaymentAllocation.objects.filter(
            invoice_item__invoice=active_invoice
        ).select_related('payment', 'invoice_item')

        active_allocations = allocations.filter(is_active=True)
        inactive_allocations = allocations.filter(is_active=False)
        
        total_allocated = sum(a.amount for a in active_allocations)
        self.stdout.write(f'\nFound {active_allocations.count()} active allocation(s) totaling: {total_allocated}')
        if inactive_allocations.exists():
            self.stdout.write(f'Found {inactive_allocations.count()} inactive allocation(s) (already removed)')

        # Get payment references (initialize as empty list)
        payment_refs = []
        if active_allocations.exists():
            payment_refs = list(set(a.payment.payment_reference for a in active_allocations))
            self.stdout.write(f'  Payments involved: {", ".join(payment_refs)}')
        elif inactive_allocations.exists():
            # If only inactive allocations, get those payment refs
            payment_refs = list(set(a.payment.payment_reference for a in inactive_allocations))
            self.stdout.write(f'  Payments from inactive allocations: {", ".join(payment_refs)}')
        else:
            # If no allocations at all, find payments that might have been allocated but are now inactive
            # or find the payment that was made around the invoice date
            payments = student.payments.filter(
                is_active=True,
                status=PaymentStatus.COMPLETED
            ).order_by('-payment_date')
            if payments.exists():
                payment_refs = [p.payment_reference for p in payments[:5]]  # Get up to 5 most recent
                self.stdout.write(f'  No allocations found. Recent payments: {", ".join(payment_refs)}')

        # Calculate what the invoice balance should be
        # balance = total_amount + balance_bf - prepayment - amount_paid
        # We want: balance = 75250, amount_paid = 0
        # So: 75250 = total_amount + balance_bf - prepayment - 0
        # This means: total_amount + balance_bf - prepayment = 75250
        
        # Actually, let's check what the invoice currently has
        current_total = (
            (active_invoice.total_amount or Decimal('0.00')) +
            (active_invoice.balance_bf or Decimal('0.00')) -
            (active_invoice.prepayment or Decimal('0.00'))
        )
        self.stdout.write(f'\nInvoice total (before payments): {current_total}')
        self.stdout.write(f'  Expected balance: 75250.00')
        self.stdout.write(f'  Current balance: {active_invoice.balance}')

        if not dry_run:
            # 1. Remove payment allocations (soft delete)
            self.stdout.write('\n1. Removing payment allocations...')
            if active_allocations.exists():
                for alloc in active_allocations:
                    self.stdout.write(f'   Deleting allocation: {alloc.payment.payment_reference} -> '
                                    f'{alloc.invoice_item.category}: {alloc.amount}')
                    alloc.is_active = False
                    alloc.save(update_fields=['is_active', 'updated_at'])
            else:
                self.stdout.write('   No active allocations to remove')

            # 2. Fix invoice
            self.stdout.write('\n2. Fixing invoice...')
            active_invoice.amount_paid = Decimal('0.00')
            active_invoice.balance = Decimal('75250.00')
            active_invoice.status = InvoiceStatus.OVERDUE
            active_invoice.is_active = False  # Make inactive since student is transferred
            active_invoice.save(update_fields=[
                'amount_paid', 'balance', 'status', 'is_active', 'updated_at'
            ])
            self.stdout.write(f'   ✓ Invoice updated: amount_paid=0, balance=75250, status=overdue, is_active=False')

            # 3. Fix student balances
            self.stdout.write('\n3. Fixing student balances...')
            
            # Since the invoice is inactive, outstanding_balance should NOT include invoice amounts
            # For transferred students with inactive invoices:
            # - outstanding_balance = balance_bf_original - total_paid
            # - balance_bf_original = 44250 (frozen balance from previous term)
            # - total_paid = 20000
            # - outstanding_balance = 44250 - 20000 = 24250
            
            student.balance_bf_original = Decimal('44250.00')
            student.outstanding_balance = Decimal('24250.00')  # balance_bf_original - total_paid
            student.credit_balance = Decimal('0.00')
            student.save(update_fields=[
                'balance_bf_original', 'outstanding_balance', 'credit_balance', 'updated_at'
            ])
            self.stdout.write(f'   ✓ Student updated:')
            self.stdout.write(f'     balance_bf_original: {student.balance_bf_original}')
            self.stdout.write(f'     outstanding_balance: {student.outstanding_balance}')
            self.stdout.write(f'     credit_balance: {student.credit_balance}')

            # 4. Update payment notes to reflect what actually happened
            self.stdout.write('\n4. Updating payment notes...')
            if payment_refs:
                for payment_ref in payment_refs:
                    try:
                        payment = Payment.objects.get(payment_reference=payment_ref)
                        old_notes = payment.notes or ''
                        # Remove any allocation-related notes and add correct note
                        new_notes = old_notes
                        if 'Unapplied credit' in new_notes:
                            # Remove unapplied credit note since payment was applied to outstanding
                            import re
                            new_notes = re.sub(r'\s*\|\s*Unapplied credit: KES [\d,.]+', '', new_notes)
                        if 'Applied to outstanding balance' not in new_notes:
                            new_notes += f' | Applied to outstanding balance (no active invoices - student transferred)'
                        payment.notes = new_notes
                        payment.save(update_fields=['notes', 'updated_at'])
                        self.stdout.write(f'   ✓ Updated payment {payment_ref}')
                    except Payment.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f'   Payment {payment_ref} not found'))
            else:
                self.stdout.write('   No payments to update (no allocations found)')

            self.stdout.write(self.style.SUCCESS('\n✓ Fix completed successfully!'))
        else:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No changes made'))

        # Show summary
        self.stdout.write('\n=== Summary ===')
        self.stdout.write(f'Invoice will be: amount_paid=0, balance=75250, status=overdue, is_active=False')
        self.stdout.write(f'Student will be: outstanding_balance=24250, credit_balance=0, balance_bf_original=44250')
        self.stdout.write(f'Payment allocations: {active_allocations.count()} will be removed')

