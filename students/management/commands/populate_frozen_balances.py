"""
Management command to populate frozen balance fields from current credit_balance.

This is a one-time command to initialize the new balance_bf_original and prepayment_original
fields based on existing student credit_balance values.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from students.models import Student


class Command(BaseCommand):
    help = 'Populate frozen balance fields (balance_bf_original, prepayment_original) from credit_balance'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        self.stdout.write('=' * 80)
        self.stdout.write('POPULATE FROZEN BALANCE FIELDS')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        self.stdout.write('=' * 80)
        self.stdout.write('')
        
        students = Student.objects.all()
        total = students.count()
        
        stats = {
            'with_debt': 0,
            'with_prepayment': 0,
            'zero_balance': 0,
            'updated': 0,
        }
        
        for student in students:
            credit_balance = student.credit_balance or Decimal('0.00')
            
            if credit_balance > 0:
                # Debt - set balance_bf_original
                balance_bf_original = credit_balance
                prepayment_original = Decimal('0.00')
                stats['with_debt'] += 1
                change_type = 'DEBT'
            elif credit_balance < 0:
                # Prepayment - set prepayment_original (as positive value)
                balance_bf_original = Decimal('0.00')
                prepayment_original = abs(credit_balance)
                stats['with_prepayment'] += 1
                change_type = 'PREPAYMENT'
            else:
                # Zero balance
                balance_bf_original = Decimal('0.00')
                prepayment_original = Decimal('0.00')
                stats['zero_balance'] += 1
                change_type = 'ZERO'
            
            # Check if update is needed
            needs_update = (
                student.balance_bf_original != balance_bf_original or
                student.prepayment_original != prepayment_original
            )
            
            if needs_update:
                self.stdout.write(
                    f'{student.admission_number}: credit_balance={credit_balance:,.2f} -> '
                    f'balance_bf_original={balance_bf_original:,.2f}, '
                    f'prepayment_original={prepayment_original:,.2f} [{change_type}]'
                )
                
                if not dry_run:
                    student.balance_bf_original = balance_bf_original
                    student.prepayment_original = prepayment_original
                    student.save(update_fields=['balance_bf_original', 'prepayment_original'])
                
                stats['updated'] += 1
        
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write('SUMMARY')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Total students: {total}')
        self.stdout.write(f'With debt (balance_bf_original set): {stats["with_debt"]}')
        self.stdout.write(f'With prepayment (prepayment_original set): {stats["with_prepayment"]}')
        self.stdout.write(f'Zero balance: {stats["zero_balance"]}')
        self.stdout.write(f'Records {"would be " if dry_run else ""}updated: {stats["updated"]}')
        
        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('DRY RUN - No changes were made. Run without --dry-run to apply changes.'))
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'Successfully populated frozen balance fields for {stats["updated"]} students.'))

