from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from students.models import Student
from payments.models import Payment, PaymentAllocation


class Command(BaseCommand):
    help = 'Fix student 2584 credit balance to canonical value from payment residue'

    @transaction.atomic
    def handle(self, *args, **options):
        student = Student.objects.select_for_update().get(admission_number='2584')
        total_paid = Payment.objects.filter(student=student, is_active=True, status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_alloc = PaymentAllocation.objects.filter(payment__student=student, payment__is_active=True, payment__status='completed', is_active=True).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        expected_credit = max(Decimal('0.00'), total_paid - total_alloc)
        self.stdout.write(f'Current credit={student.credit_balance}')
        self.stdout.write(f'Expected credit={expected_credit}')
        student.credit_balance = expected_credit
        student.outstanding_balance = Decimal('0.00')
        student.save(update_fields=['credit_balance', 'outstanding_balance', 'updated_at'])
        self.stdout.write(self.style.SUCCESS(f'Fixed 2584 credit_balance -> {student.credit_balance}'))
