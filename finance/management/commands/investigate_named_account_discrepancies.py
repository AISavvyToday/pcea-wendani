from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from students.models import Student
from finance.models import Invoice
from payments.models import Payment, PaymentAllocation


class Command(BaseCommand):
    help = "Investigate specific student account discrepancies by admission number"

    def add_arguments(self, parser):
        parser.add_argument('admission_numbers', nargs='+', help='Admission numbers to inspect')

    def handle(self, *args, **options):
        for adm in options['admission_numbers']:
            self.stdout.write('\n' + '=' * 100)
            self.stdout.write(f'ADMISSION {adm}')

            student = Student.objects.filter(admission_number=adm).first()
            if not student:
                self.stdout.write(self.style.ERROR('Student not found'))
                continue

            self.stdout.write(f'Student: {student.full_name} ({student.admission_number})')
            self.stdout.write(f'  status={student.status}')
            self.stdout.write(f'  outstanding_balance={student.outstanding_balance}')
            self.stdout.write(f'  credit_balance={student.credit_balance}')
            self.stdout.write(f'  balance_bf_original={student.balance_bf_original}')
            self.stdout.write(f'  prepayment_original={student.prepayment_original}')

            total_paid = Payment.objects.filter(
                student=student, is_active=True, status='completed'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            total_alloc = PaymentAllocation.objects.filter(
                payment__student=student,
                payment__is_active=True,
                payment__status='completed',
                is_active=True,
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            expected_credit_from_unallocated = max(Decimal('0.00'), total_paid - total_alloc)

            self.stdout.write(f'  total_paid={total_paid}')
            self.stdout.write(f'  total_allocated={total_alloc}')
            self.stdout.write(f'  expected_credit_from_unallocated={expected_credit_from_unallocated}')

            self.stdout.write('  Invoices:')
            for inv in Invoice.objects.filter(student=student).order_by('issue_date', 'created_at'):
                alloc = PaymentAllocation.objects.filter(
                    invoice_item__invoice=inv,
                    is_active=True,
                    payment__is_active=True,
                    payment__status='completed',
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                due = (inv.total_amount or Decimal('0.00')) + (inv.balance_bf or Decimal('0.00')) - (inv.prepayment or Decimal('0.00'))
                self.stdout.write(
                    f'    {inv.invoice_number}: active={inv.is_active} status={inv.status} due={due} amount_paid={inv.amount_paid} alloc={alloc} balance={inv.balance}'
                )

            self.stdout.write('  Payments:')
            for p in Payment.objects.filter(student=student, is_active=True).order_by('payment_date', 'created_at'):
                alloc = p.allocations.filter(is_active=True).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                self.stdout.write(
                    f'    {p.payment_reference} | receipt={p.receipt_number} | amount={p.amount} | allocated={alloc} | unallocated={(p.amount or Decimal("0.00")) - alloc} | date={p.payment_date} | notes={(p.notes or "")[:180]}'
                )
