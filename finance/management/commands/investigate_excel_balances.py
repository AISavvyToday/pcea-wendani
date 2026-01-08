"""
Investigate balance_bf_original discrepancies using original Excel upload data.
This script reads the original student data Excel file and compares it
with current invoice balance_bf_original values to identify and fix discrepancies.
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.db import transaction
from decimal import Decimal
import pandas as pd
import os

from finance.models import Invoice
from students.models import Student
from core.models import InvoiceStatus
from portal.views import _get_current_term, _invoice_base_qs


class Command(BaseCommand):
    help = 'Investigate balance_bf_original discrepancies using original Excel upload data'

    def add_arguments(self, parser):
        parser.add_argument(
            'excel_file',
            type=str,
            help='Path to the original Excel file with student data',
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
            default=None,
            help='Column name for balance brought forward (default: auto-detect "Bal BF")',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be corrected without making changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for each invoice',
        )
        parser.add_argument(
            '--apply-corrections',
            action='store_true',
            help='Apply corrections to balance_bf_original values (use with caution)',
        )

    def handle(self, *args, **options):
        excel_file = options['excel_file']
        admission_col = options.get('admission_column')
        balance_col = options.get('balance_column')
        dry_run = options.get('dry_run', False)
        verbose = options.get('verbose', False)
        apply_corrections = options.get('apply_corrections', False)
        
        if not os.path.exists(excel_file):
            self.stdout.write(self.style.ERROR(f'Excel file not found: {excel_file}'))
            return
        
        term = _get_current_term()
        if not term:
            self.stdout.write(self.style.ERROR('No current term found'))
            return
        
        self.stdout.write('=' * 80)
        self.stdout.write('INVESTIGATING balance_bf_original DISCREPANCIES')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Term: {term}')
        self.stdout.write(f'Excel file: {excel_file}')
        self.stdout.write('')
        
        # Read Excel file
        self.stdout.write('Reading Excel file...')
        try:
            df = pd.read_excel(excel_file)
            self.stdout.write(f'✓ Loaded {len(df)} rows')
            self.stdout.write(f'Columns: {", ".join(df.columns.tolist())}')
            self.stdout.write('')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error reading Excel file: {e}'))
            return
        
        # Auto-detect admission number column if not specified
        if not admission_col:
            for col in df.columns:
                col_lower = str(col).lower()
                if 'admission' in col_lower or 'adm' in col_lower or ('student' in col_lower and 'id' in col_lower):
                    admission_col = col
                    break
        
        if not admission_col:
            self.stdout.write(self.style.ERROR(
                f'Could not find admission number column. Available columns: {", ".join(df.columns)}'
            ))
            self.stdout.write('Please specify --admission-column')
            return
        
        # Auto-detect balance column if not specified
        if not balance_col:
            for col in df.columns:
                col_lower = str(col).lower()
                if 'bal bf' in col_lower or 'balance bf' in col_lower or ('balance' in col_lower and 'bf' in col_lower):
                    balance_col = col
                    break
        
        if not balance_col:
            self.stdout.write(self.style.ERROR(
                f'Could not find balance column. Available columns: {", ".join(df.columns)}'
            ))
            self.stdout.write('Please specify --balance-column')
            return
        
        self.stdout.write(f'Using admission column: {admission_col}')
        self.stdout.write(f'Using balance column: {balance_col}')
        self.stdout.write('')
        
        # Create mapping of admission_number -> original balance
        # Note: Excel has positive = debt, negative = prepayment/credit
        original_balances = {}
        for _, row in df.iterrows():
            admission = str(row[admission_col]).strip() if pd.notna(row[admission_col]) else ''
            balance_val = row[balance_col] if pd.notna(row[balance_col]) else 0
            balance = Decimal(str(balance_val))
            
            if admission:
                # Store in multiple formats for matching
                original_balances[admission] = balance
                # Handle formats like "PWA/3047/" and "3047"
                if '/' in admission:
                    # Format: PWA/3047/ -> also try without PWA/ prefix
                    parts = admission.split('/')
                    if len(parts) >= 2:
                        alt_admission = parts[-2] if parts[-1] == '' else parts[-1]
                        if alt_admission:
                            original_balances[alt_admission] = balance
                else:
                    # Format: 3047 -> also try with PWA/ prefix
                    original_balances[f'PWA/{admission}/'] = balance
        
        self.stdout.write(f'✓ Loaded {len(original_balances)} original balance records')
        self.stdout.write('')
        
        # Get current term invoices
        base = _invoice_base_qs()
        term_invoices = base.filter(term=term)
        invoices = term_invoices.select_related('student', 'term').order_by('student__admission_number')
        
        discrepancies = []
        total_original_excel = Decimal('0.00')
        total_current_bf_original = Decimal('0.00')
        matched = 0
        unmatched = 0
        
        self.stdout.write('Comparing with current invoices...')
        self.stdout.write('-' * 80)
        
        for invoice in invoices:
            admission = invoice.student.admission_number
            current_bf_original = invoice.balance_bf_original or Decimal('0.00')
            total_current_bf_original += current_bf_original
            
            # Try to find original balance from Excel
            original_balance = original_balances.get(admission)
            if original_balance is None and '/' in admission:
                # Try alternative formats
                parts = admission.split('/')
                if len(parts) >= 2:
                    alt_admission = parts[-2] if parts[-1] == '' else parts[-1]
                    original_balance = original_balances.get(alt_admission)
            
            if original_balance is not None:
                matched += 1
                # Only count positive balances (debts) for total
                if original_balance > 0:
                    total_original_excel += original_balance
                
                difference = current_bf_original - original_balance
                if abs(difference) > Decimal('0.01'):
                    discrepancies.append({
                        'invoice': invoice,
                        'admission': admission,
                        'excel_balance': original_balance,
                        'current_bf_original': current_bf_original,
                        'difference': difference
                    })
                    if verbose:
                        self.stdout.write(
                            f'  {invoice.invoice_number} ({admission}): '
                            f'Excel={original_balance:,.2f}, Current={current_bf_original:,.2f}, '
                            f'Diff={difference:,.2f}'
                        )
            else:
                unmatched += 1
                if verbose:
                    self.stdout.write(f'  ⚠ No Excel data found for {admission} (Invoice: {invoice.invoice_number})')
        
        self.stdout.write('')
        self.stdout.write(f'Matched: {matched} invoices')
        self.stdout.write(f'Unmatched: {unmatched} invoices')
        self.stdout.write('')
        
        # Show totals
        self.stdout.write('TOTALS:')
        self.stdout.write('-' * 80)
        self.stdout.write(f'Total from Excel (positive balances only): {total_original_excel:,.2f}')
        self.stdout.write(f'Total current balance_bf_original: {total_current_bf_original:,.2f}')
        difference_total = total_current_bf_original - total_original_excel
        self.stdout.write(f'Difference: {difference_total:,.2f}')
        self.stdout.write('')
        
        target_reduction = Decimal('154456')
        if abs(difference_total - target_reduction) < Decimal('100'):
            self.stdout.write(self.style.SUCCESS(
                f'✓ Difference ({difference_total:,.2f}) matches target ({target_reduction:,.2f})!'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'⚠ Difference ({difference_total:,.2f}) does not match target ({target_reduction:,.2f})'
            ))
            self.stdout.write('   This might be due to:')
            self.stdout.write('   - Some students not in Excel file')
            self.stdout.write('   - Different column names in Excel')
            self.stdout.write('   - Additional adjustments needed')
        
        # Show discrepancies
        if discrepancies:
            discrepancies.sort(key=lambda x: abs(x['difference']), reverse=True)
            self.stdout.write('')
            self.stdout.write(f'Found {len(discrepancies)} invoices with discrepancies:')
            self.stdout.write('-' * 80)
            self.stdout.write(
                f'{"Invoice":<20} {"Student":<15} {"Excel":>15} {"Current":>15} {"Difference":>15}'
            )
            self.stdout.write('-' * 80)
            
            for disc in discrepancies[:50]:  # Show top 50
                inv = disc['invoice']
                self.stdout.write(
                    f"{inv.invoice_number:<20} "
                    f"{disc['admission']:<15} "
                    f"{disc['excel_balance']:>15,.2f} "
                    f"{disc['current_bf_original']:>15,.2f} "
                    f"{disc['difference']:>15,.2f}"
                )
            
            if len(discrepancies) > 50:
                self.stdout.write(f'... and {len(discrepancies) - 50} more')
            
            # Apply corrections if requested
            if apply_corrections and not dry_run:
                self.stdout.write('')
                self.stdout.write('Applying corrections...')
                
                with transaction.atomic():
                    corrected_count = 0
                    for disc in discrepancies:
                        inv = disc['invoice']
                        inv.balance_bf_original = disc['excel_balance']
                        inv.save(update_fields=['balance_bf_original'])
                        corrected_count += 1
                
                self.stdout.write(self.style.SUCCESS(
                    f'✓ Successfully corrected {corrected_count} invoices'
                ))
            elif dry_run:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes were made'))
                self.stdout.write('Run with --apply-corrections (without --dry-run) to apply corrections')
            else:
                self.stdout.write('')
                self.stdout.write('To apply corrections, run with --apply-corrections flag')
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('No discrepancies found!'))



