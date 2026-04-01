from decimal import Decimal, ROUND_HALF_UP
from django.core.management.base import BaseCommand
from django.db.models import Sum
from students.models import Student
from payments.services.invoice import InvoiceService

class Command(BaseCommand):
    help = 'Debug audit credit logic for admission 2597'

    def handle(self, *args, **options):
        student = Student.objects.get(admission_number='2597')
        invoices_qs = student.invoices.filter(is_active=True).exclude(status='cancelled')
        credit_balance = student.credit_balance or Decimal('0.00')
        outstanding_balance = student.outstanding_balance or Decimal('0.00')
        expected_unapplied_credit = max(Decimal('0.00'), InvoiceService.get_student_unapplied_credit(student))
        expected_invoice_prepayment_credit = max(
            Decimal('0.00'),
            invoices_qs.aggregate(total=Sum('prepayment'))['total'] or Decimal('0.00')
        )
        rounded_credit = credit_balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        rounded_unapplied = expected_unapplied_credit.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        rounded_prepayment = expected_invoice_prepayment_credit.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        matches_unapplied = rounded_credit == rounded_unapplied
        matches_prepayment = rounded_credit == rounded_prepayment
        credit_mismatch = not (matches_unapplied or matches_prepayment)
        has_outstanding = outstanding_balance > 0
        print({
            'credit_balance': str(credit_balance),
            'outstanding_balance': str(outstanding_balance),
            'expected_unapplied_credit': str(expected_unapplied_credit),
            'expected_invoice_prepayment_credit': str(expected_invoice_prepayment_credit),
            'matches_unapplied': matches_unapplied,
            'matches_prepayment': matches_prepayment,
            'credit_mismatch': credit_mismatch,
            'has_outstanding': has_outstanding,
        })
