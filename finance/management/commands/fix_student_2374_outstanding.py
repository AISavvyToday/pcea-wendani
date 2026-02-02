"""
Quick fix for student 2374 outstanding balance.
Since invoice was deleted, just update the outstanding_balance directly.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from decimal import Decimal
from students.models import Student


class Command(BaseCommand):
    help = 'Fix outstanding balance for student 2374'

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            student = Student.objects.get(admission_number='2374')
        except Student.DoesNotExist:
            self.stdout.write(self.style.ERROR('Student 2374 not found'))
            return

        self.stdout.write(f'\n=== Fixing student 2374: {student.full_name} ===')
        self.stdout.write(f'Current balance_bf_original: {student.balance_bf_original}')
        self.stdout.write(f'Current outstanding_balance: {student.outstanding_balance}')
        self.stdout.write(f'Current credit_balance: {student.credit_balance}')
        
        # Calculate total paid
        from payments.models import Payment
        from core.models import PaymentStatus
        total_paid = Payment.objects.filter(
            student=student,
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        self.stdout.write(f'Total paid: {total_paid}')
        
        # For transferred student with no active invoices:
        # outstanding_balance = balance_bf_original - total_paid
        expected_outstanding = (student.balance_bf_original or Decimal('0.00')) - total_paid
        
        self.stdout.write(f'\nExpected outstanding: {expected_outstanding}')
        self.stdout.write(f'Current outstanding: {student.outstanding_balance}')
        
        if student.outstanding_balance != expected_outstanding:
            student.outstanding_balance = expected_outstanding
            student.save(update_fields=['outstanding_balance', 'updated_at'])
            self.stdout.write(self.style.SUCCESS(f'\n✓ Updated outstanding_balance to {expected_outstanding}'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ Outstanding balance is already correct'))
        
        self.stdout.write(f'\nFinal state:')
        self.stdout.write(f'  balance_bf_original: {student.balance_bf_original}')
        self.stdout.write(f'  outstanding_balance: {student.outstanding_balance}')
        self.stdout.write(f'  credit_balance: {student.credit_balance}')

