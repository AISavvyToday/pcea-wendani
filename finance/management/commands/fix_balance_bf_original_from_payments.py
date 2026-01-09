"""
Fix balance_bf_original values by calculating original balance from current state + payments.
This restores balance_bf_original to what it should have been at invoice creation.

Formula: balance_bf_original = current balance_bf + payments made to balance_bf
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal

from finance.models import Invoice
from portal.views import _get_current_term, _invoice_base_qs
from payments.services.invoice import InvoiceService


class Command(BaseCommand):
    help = 'Fix balance_bf_original by calculating from current balance_bf + payments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for each invoice',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        verbose = options.get('verbose', False)
        
        term = _get_current_term()
        if not term:
            self.stdout.write(self.style.ERROR('No current term found'))
            return
        
        self.stdout.write('=' * 80)
        self.stdout.write('FIXING balance_bf_original FROM CURRENT STATE + PAYMENTS')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Term: {term}')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        self.stdout.write('')
        
        # Get current term invoices
        base = _invoice_base_qs()
        invoices = base.filter(term=term).select_related('student', 'term')
        
        fixes = []
        total_old = Decimal('0.00')
        total_new = Decimal('0.00')
        
        self.stdout.write('Analyzing invoices...')
        self.stdout.write('-' * 80)
        
        for invoice in invoices:
            current_bf_original = invoice.balance_bf_original or Decimal('0.00')
            
            # Calculate what balance_bf_original SHOULD be
            # Get allocations to invoice items
            allocations_to_items = InvoiceService._sum_allocations_for_invoice(invoice)
            
            # Calculate payments to balance_bf
            # If amount_paid > allocations_to_items, the difference is balance_bf payments
            balance_bf_paid = Decimal('0.00')
            if invoice.balance_bf > 0 and invoice.amount_paid > allocations_to_items:
                balance_bf_paid = invoice.amount_paid - allocations_to_items
                # Can't exceed current balance_bf (since balance_bf decreases as payments are made)
                balance_bf_paid = min(balance_bf_paid, invoice.balance_bf)
            
            # Original balance_bf = current balance_bf + what was paid to it
            calculated_bf_original = invoice.balance_bf + balance_bf_paid
            
            # Only fix if there's a difference
            if abs(current_bf_original - calculated_bf_original) > Decimal('0.01'):
                fixes.append({
                    'invoice': invoice,
                    'old_value': current_bf_original,
                    'new_value': calculated_bf_original,
                    'current_balance_bf': invoice.balance_bf,
                    'balance_bf_paid': balance_bf_paid,
                    'allocations_to_items': allocations_to_items,
                })
                total_old += current_bf_original
                total_new += calculated_bf_original
                
                if verbose:
                    self.stdout.write(
                        f'  {invoice.invoice_number} ({invoice.student.admission_number}): '
                        f'{current_bf_original:,.2f} -> {calculated_bf_original:,.2f} '
                        f'(bf={invoice.balance_bf:,.2f}, paid={balance_bf_paid:,.2f})'
                    )
        
        self.stdout.write('')
        self.stdout.write(f'Found {len(fixes)} invoices that need fixing')
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

