"""
Investigate students with credit_balance > 0 and unpaid invoices.
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db.models import Sum

from students.models import Student
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from core.models import PaymentStatus


class Command(BaseCommand):
    help = "Investigate students with credit_balance > 0 and unpaid invoices"

    def add_arguments(self, parser):
        parser.add_argument(
            '--students',
            nargs='*',
            help='Specific admission numbers to investigate',
        )

    def handle(self, *args, **options):
        specific_students = options.get('students')

        if specific_students:
            students = Student.objects.filter(admission_number__in=specific_students)
        else:
            # Auto-detect problematic students
            students = Student.objects.filter(
                status='active',
                credit_balance__gt=0,
            )

        for student in students:
            invoices = student.invoices.filter(
                is_active=True,
                balance__gt=0
            ).exclude(status='cancelled')

            if not invoices.exists():
                continue

            self.stdout.write("")
            self.stdout.write("=" * 70)
            self.stdout.write(f"Student: {student.admission_number} {student.full_name}")
            self.stdout.write(f"  credit_balance: {student.credit_balance}")
            self.stdout.write(f"  outstanding_balance: {student.outstanding_balance}")
            self.stdout.write(f"  balance_bf_original: {student.balance_bf_original}")

            for inv in invoices:
                self.stdout.write("")
                self.stdout.write(f"Invoice: {inv.invoice_number}")
                self.stdout.write(f"  created_at: {inv.created_at}")
                self.stdout.write(f"  total_amount: {inv.total_amount}")
                self.stdout.write(f"  balance_bf: {inv.balance_bf}")
                self.stdout.write(f"  prepayment: {inv.prepayment}")
                self.stdout.write(f"  amount_paid: {inv.amount_paid}")
                self.stdout.write(f"  balance: {inv.balance}")
                self.stdout.write(f"  status: {inv.status}")

                # Check items
                self.stdout.write(f"  Invoice Items:")
                total_item_amount = Decimal("0.00")
                for item in inv.items.all():
                    alloc = PaymentAllocation.objects.filter(
                        invoice_item=item,
                        is_active=True,
                        payment__is_active=True,
                        payment__status=PaymentStatus.COMPLETED,
                    ).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")
                    due = (item.net_amount or Decimal("0.00")) - alloc
                    self.stdout.write(
                        f"    - {item.category}: net={item.net_amount}, "
                        f"alloc={alloc}, due={due}, is_active={item.is_active}"
                    )
                    if item.is_active and item.net_amount and item.net_amount > 0:
                        total_item_amount += item.net_amount

                self.stdout.write(f"  Total positive item amounts: {total_item_amount}")

            # Check payments
            payments = Payment.objects.filter(
                student=student,
                is_active=True,
                status=PaymentStatus.COMPLETED,
            ).order_by('-payment_date')

            self.stdout.write("")
            self.stdout.write(f"Payments ({payments.count()}):")
            for p in payments:
                allocs = p.allocations.filter(is_active=True)
                total_alloc = allocs.aggregate(total=Sum('amount'))['total'] or Decimal("0.00")
                unalloc = p.amount - total_alloc
                self.stdout.write(f"  {p.payment_reference}: amount={p.amount}, alloc={total_alloc}, unalloc={unalloc}")
                self.stdout.write(f"    notes: {(p.notes or '')[:100]}")
                if allocs.exists():
                    for a in allocs:
                        self.stdout.write(f"      -> {a.invoice_item.category} ({a.invoice_item.invoice.invoice_number}): {a.amount}")

