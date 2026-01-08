"""
Set a student's credit_balance to a specific value.
Positive value = debt (student owes money)
Negative value = prepayment (student has credit)
"""
from django.core.management.base import BaseCommand
from decimal import Decimal

from students.models import Student


class Command(BaseCommand):
    help = 'Set a student\'s credit_balance to a specific value'

    def add_arguments(self, parser):
        parser.add_argument(
            'admission_number',
            type=str,
            help='Student admission number (e.g., PWA/3047/)',
        )
        parser.add_argument(
            'amount',
            type=Decimal,
            help='Amount to set (positive = debt, negative = prepayment)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )

    def handle(self, *args, **options):
        admission_number = options['admission_number']
        amount = options['amount']
        dry_run = options.get('dry_run', False)
        
        try:
            student = Student.objects.get(admission_number=admission_number)
        except Student.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                f'Student with admission number "{admission_number}" not found'
            ))
            return
        except Student.MultipleObjectsReturned:
            self.stdout.write(self.style.ERROR(
                f'Multiple students found with admission number "{admission_number}"'
            ))
            return
        
        old_balance = student.credit_balance or Decimal('0.00')
        
        self.stdout.write('=' * 80)
        self.stdout.write('SET STUDENT CREDIT BALANCE')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Student: {student.full_name} ({student.admission_number})')
        self.stdout.write(f'Current credit_balance: {old_balance:,.2f}')
        self.stdout.write(f'New credit_balance: {amount:,.2f}')
        self.stdout.write('')
        
        if amount > 0:
            self.stdout.write(f'  → Student will have DEBT of {amount:,.2f}')
        elif amount < 0:
            self.stdout.write(f'  → Student will have PREPAYMENT of {abs(amount):,.2f}')
        else:
            self.stdout.write('  → Student will have ZERO balance')
        
        self.stdout.write('')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
            self.stdout.write('')
            self.stdout.write('Run without --dry-run to apply changes')
        else:
            student.credit_balance = amount
            student.save()
            self.stdout.write(self.style.SUCCESS(f'✓ Successfully updated credit_balance to {amount:,.2f}'))
            self.stdout.write('')
            self.stdout.write('The student\'s outstanding balance should now show this amount.')

