"""
Fix balance_bf allocation issues for students with credit_balance > 0 and unpaid invoices.

The issue: Invoice has balance_bf field set, but NO InvoiceItem with category='balance_bf' exists.
This causes payments to not allocate to the balance_bf portion, leaving it unpaid while
excess payment goes to credit_balance.

Fix:
1. Create missing balance_bf InvoiceItem if invoice.balance_bf > 0 but no item exists
2. Re-allocate payments from credit_balance to the balance_bf item
3. Update invoice and student balances
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from students.models import Student
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from core.models import InvoiceStatus, PaymentStatus


class Command(BaseCommand):
    help = "Fix balance_bf allocation issues for students with credit and unpaid invoices"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Show what would be fixed without making changes',
        )
        parser.add_argument(
            '--students',
            nargs='*',
            help='Specific admission numbers to fix (default: auto-detect)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        specific_students = options.get('students')

        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write("🔧 FIX BALANCE_BF ALLOCATION ISSUES")
        self.stdout.write("=" * 70)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))

        # Find affected students
        if specific_students:
            students = Student.objects.filter(admission_number__in=specific_students)
        else:
            # Find students with credit_balance > 0 and unpaid invoices
            students = Student.objects.filter(
                status='active',
                credit_balance__gt=0,
            )

        fixed_count = 0

        for student in students:
            # Check if student has unpaid invoices
            invoices = student.invoices.filter(
                is_active=True,
                balance__gt=0
            ).exclude(status='cancelled')

            if not invoices.exists():
                continue

            for invoice in invoices:
                # Check if invoice has balance_bf but no balance_bf item
                if invoice.balance_bf and invoice.balance_bf > 0:
                    bf_item = invoice.items.filter(category='balance_bf').first()

                    if bf_item is None:
                        self.stdout.write("")
                        self.stdout.write(f"Found issue: {student.admission_number} {student.full_name}")
                        self.stdout.write(f"  Invoice: {invoice.invoice_number}")
                        self.stdout.write(f"  balance_bf: {invoice.balance_bf}")
                        self.stdout.write(f"  Missing balance_bf InvoiceItem!")
                        self.stdout.write(f"  Student credit_balance: {student.credit_balance}")

                        if not dry_run:
                            self._fix_student(student, invoice)
                            fixed_count += 1
                        else:
                            self.stdout.write(self.style.WARNING("  Would fix this..."))

        self.stdout.write("")
        self.stdout.write("=" * 70)
        if dry_run:
            self.stdout.write(f"Would fix {fixed_count} student(s)")
        else:
            self.stdout.write(self.style.SUCCESS(f"✅ Fixed {fixed_count} student(s)"))

    @transaction.atomic
    def _fix_student(self, student, invoice):
        """Fix a single student's balance_bf allocation issue."""
        
        balance_bf = invoice.balance_bf
        credit_to_use = min(student.credit_balance or Decimal("0.00"), balance_bf)

        self.stdout.write(f"  Fixing: Creating balance_bf item for {balance_bf}")

        # 1. Create the missing balance_bf InvoiceItem
        bf_item = InvoiceItem.objects.create(
            invoice=invoice,
            fee_item=None,
            category='balance_bf',
            description='Balance B/F from previous term',
            amount=balance_bf,
            discount_applied=Decimal("0.00"),
            net_amount=balance_bf,
        )
        self.stdout.write(f"  ✓ Created balance_bf InvoiceItem (id={bf_item.id})")

        if credit_to_use <= 0:
            self.stdout.write(f"  No credit to allocate")
            return

        # 2. Find the payment that created the unapplied credit
        # Look for payments with "Unapplied credit" in notes
        payments = Payment.objects.filter(
            student=student,
            is_active=True,
            status=PaymentStatus.COMPLETED,
            notes__icontains='Unapplied credit'
        ).order_by('-payment_date')

        if not payments.exists():
            # Try to find any payment with excess
            payments = Payment.objects.filter(
                student=student,
                is_active=True,
                status=PaymentStatus.COMPLETED,
            ).order_by('-payment_date')

        for payment in payments:
            if credit_to_use <= 0:
                break

            # Check how much of this payment is unallocated
            allocated = payment.allocations.filter(is_active=True).aggregate(
                total=Sum('amount')
            )['total'] or Decimal("0.00")
            unallocated = payment.amount - allocated

            if unallocated <= 0:
                continue

            # Allocate from this payment to the balance_bf item
            amount_to_allocate = min(unallocated, credit_to_use)

            PaymentAllocation.objects.create(
                payment=payment,
                invoice_item=bf_item,
                amount=amount_to_allocate,
            )
            self.stdout.write(f"  ✓ Created allocation: {payment.payment_reference} -> balance_bf: {amount_to_allocate}")

            # Update payment notes
            old_note = payment.notes or ""
            if "Unapplied credit" in old_note:
                # Remove or update the unapplied credit note
                import re
                new_remaining = unallocated - amount_to_allocate
                if new_remaining > 0:
                    new_note = re.sub(
                        r'Unapplied credit: KES [\d,.]+',
                        f'Unapplied credit: KES {new_remaining}',
                        old_note
                    )
                else:
                    new_note = re.sub(r'\s*\|\s*Unapplied credit: KES [\d,.]+', '', old_note)
                payment.notes = new_note
                payment.save(update_fields=['notes', 'updated_at'])

            credit_to_use -= amount_to_allocate

        # 3. Update invoice amount_paid and balance
        total_allocations = PaymentAllocation.objects.filter(
            invoice_item__invoice=invoice,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED,
        ).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")

        invoice.amount_paid = total_allocations
        invoice.save()  # This will recalculate balance via save()
        self.stdout.write(f"  ✓ Updated invoice: amount_paid={invoice.amount_paid}, balance={invoice.balance}")

        # 4. Update student credit_balance
        original_credit = student.credit_balance
        used_credit = min(original_credit, balance_bf)
        student.credit_balance = max(Decimal("0.00"), original_credit - used_credit)
        student.save(update_fields=['credit_balance', 'updated_at'])
        student.recompute_outstanding_balance()
        self.stdout.write(f"  ✓ Updated student: credit_balance {original_credit} -> {student.credit_balance}")
        self.stdout.write(f"  ✓ Outstanding balance: {student.outstanding_balance}")

