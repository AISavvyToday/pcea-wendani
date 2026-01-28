"""
Reallocate credit_balance to unpaid invoice items.

For students with both credit_balance > 0 and unpaid invoices,
this command creates allocations from existing payments to unpaid items.
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from students.models import Student
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from payments.services.invoice import InvoiceService
from core.models import PaymentStatus


class Command(BaseCommand):
    help = "Reallocate credit_balance to unpaid invoice items"

    def add_arguments(self, parser):
        parser.add_argument(
            '--students',
            nargs='*',
            required=True,
            help='Admission numbers to fix',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Show what would be fixed without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        specific_students = options.get('students')

        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write("🔧 REALLOCATE CREDIT TO INVOICES")
        self.stdout.write("=" * 70)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))

        students = Student.objects.filter(admission_number__in=specific_students)

        for student in students:
            self._fix_student(student, dry_run)

    @transaction.atomic
    def _fix_student(self, student, dry_run):
        self.stdout.write("")
        self.stdout.write(f"Student: {student.admission_number} {student.full_name}")
        self.stdout.write(f"  credit_balance: {student.credit_balance}")

        credit_available = student.credit_balance or Decimal("0.00")
        if credit_available <= 0:
            self.stdout.write("  No credit to reallocate")
            return

        # Get unpaid invoices
        invoices = student.invoices.filter(
            is_active=True,
            balance__gt=0
        ).exclude(status='cancelled').order_by('issue_date', 'created_at')

        if not invoices.exists():
            self.stdout.write("  No unpaid invoices")
            return

        # Find payments with unallocated amounts
        payments = Payment.objects.filter(
            student=student,
            is_active=True,
            status=PaymentStatus.COMPLETED,
        ).order_by('payment_date')

        # Find which payments have unallocated amounts
        payments_with_credit = []
        for p in payments:
            allocated = p.allocations.filter(is_active=True).aggregate(
                total=Sum('amount')
            )['total'] or Decimal("0.00")
            unalloc = p.amount - allocated
            if unalloc > 0:
                payments_with_credit.append((p, unalloc))
                self.stdout.write(f"  Payment {p.payment_reference} has {unalloc} unallocated")

        if not payments_with_credit:
            self.stdout.write("  No payments with unallocated amounts")
            return

        # Now allocate to invoice items
        total_reallocated = Decimal("0.00")
        credit_remaining = credit_available

        for invoice in invoices:
            if credit_remaining <= 0:
                break

            self.stdout.write(f"\n  Processing Invoice {invoice.invoice_number} (balance: {invoice.balance})")

            # Get unpaid items sorted by priority
            items = list(invoice.items.filter(is_active=True))
            items.sort(key=lambda it: (InvoiceService._priority_key(it.category), it.id))

            for item in items:
                if credit_remaining <= 0:
                    break

                # How much is still due on this item?
                already_allocated = PaymentAllocation.objects.filter(
                    invoice_item=item,
                    is_active=True,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED,
                ).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")

                item_due = (item.net_amount or Decimal("0.00")) - already_allocated
                if item_due <= 0:
                    continue

                # How much can we allocate?
                to_allocate = min(item_due, credit_remaining)

                self.stdout.write(f"    {item.category}: due={item_due}, allocating={to_allocate}")

                if not dry_run:
                    # Find a payment with available credit to source this from
                    for payment, payment_unalloc in payments_with_credit:
                        if to_allocate <= 0:
                            break
                        if payment_unalloc <= 0:
                            continue

                        alloc_from_payment = min(to_allocate, payment_unalloc)

                        PaymentAllocation.objects.create(
                            payment=payment,
                            invoice_item=item,
                            amount=alloc_from_payment,
                        )
                        self.stdout.write(f"      Created allocation from {payment.payment_reference}: {alloc_from_payment}")

                        # Update tracking
                        to_allocate -= alloc_from_payment
                        payment_unalloc -= alloc_from_payment
                        # Update the tuple in the list
                        idx = payments_with_credit.index((payment, payment_unalloc + alloc_from_payment))
                        payments_with_credit[idx] = (payment, payment_unalloc)

                total_reallocated += min(item_due, credit_remaining) - to_allocate
                credit_remaining -= min(item_due, credit_remaining) - to_allocate

        if not dry_run and total_reallocated > 0:
            # Recalculate invoice
            for invoice in invoices:
                InvoiceService._recalculate_invoice_fields(invoice)
                self.stdout.write(f"  ✓ Invoice {invoice.invoice_number}: amount_paid={invoice.amount_paid}, balance={invoice.balance}")

            # Update student credit_balance
            student.credit_balance = max(Decimal("0.00"), student.credit_balance - total_reallocated)
            student.save(update_fields=['credit_balance', 'updated_at'])
            student.recompute_outstanding_balance()
            self.stdout.write(f"  ✓ Student credit_balance: {student.credit_balance}, outstanding: {student.outstanding_balance}")

            # Update payment notes
            for payment, _ in payments_with_credit:
                new_alloc = payment.allocations.filter(is_active=True).aggregate(
                    total=Sum('amount')
                )['total'] or Decimal("0.00")
                new_unalloc = payment.amount - new_alloc
                import re
                if new_unalloc > 0:
                    new_note = re.sub(
                        r'Unapplied credit: KES [\d,.]+',
                        f'Unapplied credit: KES {new_unalloc}',
                        payment.notes or ""
                    )
                else:
                    new_note = re.sub(r'\s*\|\s*Unapplied credit: KES [\d,.]+', '', payment.notes or "")
                if new_note != payment.notes:
                    payment.notes = new_note
                    payment.save(update_fields=['notes', 'updated_at'])

        self.stdout.write(f"\n  Total reallocated: {total_reallocated}")

