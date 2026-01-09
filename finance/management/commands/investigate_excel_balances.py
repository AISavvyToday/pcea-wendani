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
from payments.models import PaymentAllocation
from payments.services.invoice import InvoiceService
from core.models import PaymentStatus


class Command(BaseCommand):
    help = 'Investigate balance_bf_original discrepancies using original Excel upload data'

    def add_arguments(self, parser):
        parser.add_argument(
            'excel_file',
            type=str,
            nargs='?',
            default=None,
            help='Path to the original Excel file with student data (or use --excel-base64)',
        )
        parser.add_argument(
            '--excel-base64',
            type=str,
            default=None,
            help='Base64 encoded Excel file data (alternative to excel_file path)',
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
        excel_file = options.get('excel_file')
        excel_base64 = options.get('excel_base64')
        admission_col = options.get('admission_column')
        balance_col = options.get('balance_column')
        dry_run = options.get('dry_run', False)
        verbose = options.get('verbose', False)
        apply_corrections = options.get('apply_corrections', False)
        
        # Handle base64 encoded Excel data
        if excel_base64:
            import base64
            import tempfile
            try:
                excel_data = base64.b64decode(excel_base64)
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                temp_file.write(excel_data)
                temp_file.close()
                excel_file = temp_file.name
                self.stdout.write(f'✓ Decoded Excel file from base64: {excel_file}')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error decoding base64 Excel data: {e}'))
                return
        
        if not excel_file or not os.path.exists(excel_file):
            self.stdout.write(self.style.ERROR(f'Excel file not found: {excel_file}'))
            self.stdout.write('Please provide either excel_file path or --excel-base64')
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
            
            # Calculate what balance_bf_original SHOULD be based on current state + payments
            # If payments were made to balance_bf, we need to restore the original value
            allocations_to_items = InvoiceService._sum_allocations_for_invoice(invoice)
            balance_bf_paid = Decimal('0.00')
            if invoice.balance_bf > 0 and invoice.amount_paid > allocations_to_items:
                balance_bf_paid = invoice.amount_paid - allocations_to_items
                balance_bf_paid = min(balance_bf_paid, invoice.balance_bf)
            
            # Original balance_bf should be current balance_bf + what was paid to it
            calculated_bf_original = invoice.balance_bf + balance_bf_paid
            
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
                
                # Use Excel value as the authoritative source for balance_bf_original
                # But also check if calculated value matches
                difference = current_bf_original - original_balance
                calculated_difference = calculated_bf_original - original_balance
                
                if abs(difference) > Decimal('0.01') or abs(calculated_difference) > Decimal('0.01'):
                    discrepancies.append({
                        'invoice': invoice,
                        'admission': admission,
                        'excel_balance': original_balance,
                        'current_bf_original': current_bf_original,
                        'calculated_bf_original': calculated_bf_original,
                        'current_balance_bf': invoice.balance_bf,
                        'balance_bf_paid': balance_bf_paid,
                        'difference': difference,
                        'calculated_difference': calculated_difference
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
                f'{"Invoice":<20} {"Student":<15} {"Excel":>12} {"Current":>12} {"Calculated":>12} {"BF Paid":>12} {"Diff":>12}'
            )
            self.stdout.write('-' * 100)
            
            for disc in discrepancies[:50]:  # Show top 50
                inv = disc['invoice']
                self.stdout.write(
                    f"{inv.invoice_number:<20} "
                    f"{disc['admission']:<15} "
                    f"{disc['excel_balance']:>12,.2f} "
                    f"{disc['current_bf_original']:>12,.2f} "
                    f"{disc.get('calculated_bf_original', 0):>12,.2f} "
                    f"{disc.get('balance_bf_paid', 0):>12,.2f} "
                    f"{disc['difference']:>12,.2f}"
                )
            
            if len(discrepancies) > 50:
                self.stdout.write(f'... and {len(discrepancies) - 50} more')
            
            # Apply corrections if requested
            if apply_corrections and not dry_run:
                self.stdout.write('')
                self.stdout.write('Applying corrections...')
                self.stdout.write('Setting balance_bf_original from Excel values...')
                
                with transaction.atomic():
                    corrected_count = 0
                    total_corrected = Decimal('0.00')
                    for disc in discrepancies:
                        inv = disc['invoice']
                        old_value = inv.balance_bf_original or Decimal('0.00')
                        new_value = disc['excel_balance']
                        # Only set positive values (debts) as balance_bf_original
                        # Negative values (prepayments) should go to prepayment field
                        if new_value > 0:
                            inv.balance_bf_original = new_value
                            inv.save(update_fields=['balance_bf_original'])
                            corrected_count += 1
                            total_corrected += new_value
                            if verbose:
                                self.stdout.write(
                                    f'  {inv.invoice_number} ({disc["admission"]}): '
                                    f'{old_value:,.2f} -> {new_value:,.2f}'
                                )
                        elif new_value < 0:
                            # Negative value = prepayment, should not be in balance_bf_original
                            if old_value > 0:
                                inv.balance_bf_original = Decimal('0.00')
                                inv.save(update_fields=['balance_bf_original'])
                                corrected_count += 1
                                if verbose:
                                    self.stdout.write(
                                        f'  {inv.invoice_number} ({disc["admission"]}): '
                                        f'Cleared balance_bf_original (was {old_value:,.2f}, Excel shows prepayment)'
                                    )
                
                self.stdout.write(self.style.SUCCESS(
                    f'✓ Successfully corrected {corrected_count} invoices'
                ))
                self.stdout.write(f'Total balance_bf_original set: {total_corrected:,.2f}')
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



