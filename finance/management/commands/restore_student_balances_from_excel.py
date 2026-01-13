"""
Restore student credit_balance from Excel file for affected students.
This command restores balance_bf and prepayments for students whose invoices were deleted.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
import pandas as pd
import os

from students.models import Student


class Command(BaseCommand):
    help = 'Restore student credit_balance from Excel file for affected students'

    def add_arguments(self, parser):
        parser.add_argument(
            'excel_file',
            type=str,
            help='Path to the Excel file (TERM 3 2025 LIST AND BALANCES)',
        )
        parser.add_argument(
            '--admission-numbers',
            type=str,
            nargs='+',
            default=['2333', '2463', '2346', '3048'],
            help='Admission numbers to restore (default: 2333 2463 2346 3048)',
        )
        parser.add_argument(
            '--admission-column',
            type=str,
            default=None,
            help='Column name for admission number (auto-detected if not specified)',
        )
        parser.add_argument(
            '--balance-column',
            type=str,
            default='Total Balance',
            help='Column name for balance (default: "Total Balance")',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be restored without making changes',
        )

    def handle(self, *args, **options):
        excel_file = options.get('excel_file')
        admission_numbers = options.get('admission_numbers', [])
        admission_col = options.get('admission_column')
        balance_col = options.get('balance_column', 'Total Balance')
        dry_run = options.get('dry_run', False)

        if not os.path.exists(excel_file):
            self.stdout.write(self.style.ERROR(f'Excel file not found: {excel_file}'))
            return

        self.stdout.write('=' * 80)
        self.stdout.write('RESTORE STUDENT BALANCES FROM EXCEL')
        self.stdout.write('=' * 80)
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        self.stdout.write('')

        # Read Excel file
        self.stdout.write(f'Reading Excel file: {excel_file}')
        try:
            df = pd.read_excel(excel_file)
            self.stdout.write(f'✓ Loaded {len(df)} rows')
            self.stdout.write(f'Columns: {", ".join(df.columns.tolist())}')
            self.stdout.write('')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error reading Excel file: {e}'))
            return

        # Clean column names
        df.columns = [str(c).strip() for c in df.columns]

        # Auto-detect admission number column if not specified
        if not admission_col:
            for col in df.columns:
                col_lower = str(col).lower()
                if 'admission' in col_lower or 'adm' in col_lower or ('#' in col_lower and 'student' in col_lower):
                    admission_col = col
                    break
                elif col == '#' or col == 'Admission_No':
                    admission_col = col
                    break

        if not admission_col:
            self.stdout.write(self.style.ERROR(
                f'Could not find admission number column. Available columns: {", ".join(df.columns)}'
            ))
            self.stdout.write('Please specify --admission-column')
            return

        # Check if balance column exists
        if balance_col not in df.columns:
            self.stdout.write(self.style.ERROR(
                f'Balance column "{balance_col}" not found. Available columns: {", ".join(df.columns)}'
            ))
            return

        self.stdout.write(f'Using admission column: {admission_col}')
        self.stdout.write(f'Using balance column: {balance_col}')
        self.stdout.write('')

        # Convert admission numbers to strings and normalize
        df[admission_col] = df[admission_col].astype(str).str.strip()

        # Create mapping of admission_number -> balance from Excel
        excel_balances = {}
        for _, row in df.iterrows():
            admission = str(row[admission_col]).strip()
            if pd.notna(row[balance_col]):
                try:
                    balance = Decimal(str(row[balance_col]))
                    excel_balances[admission] = balance
                except (ValueError, TypeError):
                    continue

        self.stdout.write(f'Found {len(excel_balances)} students with balances in Excel')
        self.stdout.write('')

        # Process each affected student
        stats = {
            'found': 0,
            'restored': 0,
            'skipped': 0,
            'not_found_excel': 0,
            'not_found_db': 0,
        }

        self.stdout.write('Processing affected students:')
        self.stdout.write('-' * 80)

        for adm_no in admission_numbers:
            adm_no = str(adm_no).strip()
            self.stdout.write(f'\nStudent: {adm_no}')

            # Check if student exists in database
            try:
                student = Student.objects.get(admission_number=adm_no)
            except Student.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'  ✗ Student not found in database'))
                stats['not_found_db'] += 1
                continue

            stats['found'] += 1

            # Get current credit_balance
            current_balance = student.credit_balance or Decimal('0.00')
            self.stdout.write(f'  Current credit_balance: {current_balance:,.2f}')

            # Get balance from Excel
            excel_balance = excel_balances.get(adm_no)
            if excel_balance is None:
                self.stdout.write(self.style.WARNING(f'  ✗ Student not found in Excel file'))
                stats['not_found_excel'] += 1
                continue

            self.stdout.write(f'  Excel Total Balance: {excel_balance:,.2f}')

            # Determine what type of balance it is
            if excel_balance > 0:
                balance_type = 'Balance B/F (debt)'
            elif excel_balance < 0:
                balance_type = 'Prepayment (credit)'
            else:
                balance_type = 'Zero balance'

            self.stdout.write(f'  Type: {balance_type}')

            # Check if restoration is needed
            if abs(current_balance - excel_balance) < Decimal('0.01'):
                self.stdout.write(self.style.SUCCESS(f'  ✓ Balance already correct, no restoration needed'))
                stats['skipped'] += 1
                continue

            # Show what will be restored
            difference = excel_balance - current_balance
            self.stdout.write(f'  Difference: {difference:,.2f}')

            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'  [DRY RUN] Would restore credit_balance from {current_balance:,.2f} to {excel_balance:,.2f}'
                ))
            else:
                # Restore balance
                try:
                    with transaction.atomic():
                        student.credit_balance = excel_balance
                        student.save(update_fields=['credit_balance', 'updated_at'])
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ Restored credit_balance to {excel_balance:,.2f}'
                    ))
                    stats['restored'] += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  ✗ Error restoring balance: {e}'))

        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write('SUMMARY')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Students found in database: {stats["found"]}')
        self.stdout.write(f'Balances restored: {stats["restored"]}')
        self.stdout.write(f'Already correct (skipped): {stats["skipped"]}')
        self.stdout.write(f'Not found in Excel: {stats["not_found_excel"]}')
        self.stdout.write(f'Not found in database: {stats["not_found_db"]}')

        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('DRY RUN - No changes were made'))
            self.stdout.write('Run without --dry-run to apply changes')

