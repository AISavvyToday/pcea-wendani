"""
Apply balance_bf_original values from Excel file mapping (JSON format).
This command accepts a JSON mapping of admission_number -> balance_bf_original.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
import json

from finance.models import Invoice
from portal.views import _get_current_term, _invoice_base_qs


class Command(BaseCommand):
    help = 'Apply balance_bf_original values from Excel mapping (JSON)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mapping-json',
            type=str,
            help='JSON string with admission_number -> balance_bf_original mapping',
        )
        parser.add_argument(
            '--mapping-file',
            type=str,
            help='Path to JSON file with mapping',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be applied without making changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output',
        )

    def handle(self, *args, **options):
        mapping_json = options.get('mapping_json')
        mapping_file = options.get('mapping_file')
        dry_run = options.get('dry_run', False)
        verbose = options.get('verbose', False)
        
        # Load mapping
        if mapping_file:
            with open(mapping_file, 'r') as f:
                mapping = json.load(f)
        elif mapping_json:
            mapping = json.loads(mapping_json)
        else:
            self.stdout.write(self.style.ERROR('Please provide either --mapping-json or --mapping-file'))
            return
        
        term = _get_current_term()
        if not term:
            self.stdout.write(self.style.ERROR('No current term found'))
            return
        
        self.stdout.write('=' * 80)
        self.stdout.write('APPLYING balance_bf_original FROM EXCEL MAPPING')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Term: {term}')
        self.stdout.write(f'Mapping entries: {len(mapping)}')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        self.stdout.write('')
        
        # Get current term invoices
        base = _invoice_base_qs()
        invoices = base.filter(term=term).select_related('student', 'term')
        
        fixes = []
        total_old = Decimal('0.00')
        total_new = Decimal('0.00')
        matched = 0
        unmatched = 0
        
        for invoice in invoices:
            admission = invoice.student.admission_number
            current_bf_original = invoice.balance_bf_original or Decimal('0.00')
            
            # Try to find in mapping
            excel_balance = mapping.get(admission)
            if excel_balance is None and '/' in admission:
                # Try alternative formats
                parts = admission.split('/')
                if len(parts) >= 2:
                    alt_admission = parts[-2] if parts[-1] == '' else parts[-1]
                    excel_balance = mapping.get(alt_admission)
            
            if excel_balance is not None:
                matched += 1
                excel_balance_decimal = Decimal(str(excel_balance))
                
                # Only apply positive values (debts) as balance_bf_original
                # Negative values (prepayments) should not be in balance_bf_original
                if excel_balance_decimal > 0:
                    if abs(current_bf_original - excel_balance_decimal) > Decimal('0.01'):
                        fixes.append({
                            'invoice': invoice,
                            'admission': admission,
                            'old_value': current_bf_original,
                            'new_value': excel_balance_decimal,
                        })
                        total_old += current_bf_original
                        total_new += excel_balance_decimal
                        
                        if verbose:
                            self.stdout.write(
                                f'  {invoice.invoice_number} ({admission}): '
                                f'{current_bf_original:,.2f} -> {excel_balance_decimal:,.2f}'
                            )
                elif excel_balance_decimal < 0 and current_bf_original > 0:
                    # Excel shows prepayment, but we have balance_bf_original - clear it
                    fixes.append({
                        'invoice': invoice,
                        'admission': admission,
                        'old_value': current_bf_original,
                        'new_value': Decimal('0.00'),
                    })
                    total_old += current_bf_original
                    if verbose:
                        self.stdout.write(
                            f'  {invoice.invoice_number} ({admission}): '
                            f'Clearing balance_bf_original (Excel shows prepayment)'
                        )
            else:
                unmatched += 1
                if verbose:
                    self.stdout.write(f'  ⚠ No Excel data for {admission}')
        
        self.stdout.write('')
        self.stdout.write(f'Matched: {matched} invoices')
        self.stdout.write(f'Unmatched: {unmatched} invoices')
        self.stdout.write(f'Invoices to fix: {len(fixes)}')
        self.stdout.write(f'Total old balance_bf_original: {total_old:,.2f}')
        self.stdout.write(f'Total new balance_bf_original: {total_new:,.2f}')
        self.stdout.write(f'Difference: {total_new - total_old:,.2f}')
        self.stdout.write('')
        
        if fixes:
            if dry_run:
                self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes were made'))
                self.stdout.write('Run without --dry-run to apply fixes')
            else:
                self.stdout.write('Applying fixes...')
                
                with transaction.atomic():
                    fixed_count = 0
                    for fix in fixes:
                        inv = fix['invoice']
                        inv.balance_bf_original = fix['new_value']
                        inv.save(update_fields=['balance_bf_original'])
                        fixed_count += 1
                
                self.stdout.write(self.style.SUCCESS(
                    f'✓ Successfully fixed {fixed_count} invoices'
                ))
                self.stdout.write(f'Total balance_bf_original updated: {total_new:,.2f}')
        else:
            self.stdout.write(self.style.SUCCESS('No fixes needed!'))
        
        self.stdout.write('')
        self.stdout.write('=' * 80)

