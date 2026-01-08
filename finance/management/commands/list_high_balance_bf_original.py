"""
List invoices with highest balance_bf_original values to identify potential sources
of the 154,456 discrepancy.
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from decimal import Decimal

from finance.models import Invoice
from core.models import InvoiceStatus
from portal.views import _get_current_term, _invoice_base_qs


class Command(BaseCommand):
    help = 'List invoices with highest balance_bf_original values'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Number of invoices to show (default: 50)',
        )
        parser.add_argument(
            '--min-amount',
            type=Decimal,
            default=Decimal('0'),
            help='Minimum balance_bf_original to show (default: 0)',
        )

    def handle(self, *args, **options):
        limit = options.get('limit')
        min_amount = options.get('min_amount')
        
        term = _get_current_term()
        if not term:
            self.stdout.write(self.style.ERROR('No current term found'))
            return
        
        self.stdout.write('=' * 80)
        self.stdout.write('INVOICES WITH HIGHEST balance_bf_original VALUES')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Term: {term}')
        self.stdout.write('')
        
        base = _invoice_base_qs()
        term_invoices = base.filter(term=term)
        
        # Get invoices with balance_bf_original >= min_amount
        invoices = term_invoices.filter(
            Q(balance_bf_original__gte=min_amount) | 
            Q(balance_bf_original__isnull=False, balance_bf__gte=min_amount)
        ).select_related('student', 'term').order_by(
            '-balance_bf_original', 'student__admission_number'
        )[:limit]
        
        total_bf_original = Decimal('0.00')
        
        self.stdout.write(f'Showing top {limit} invoices by balance_bf_original:')
        self.stdout.write('-' * 80)
        self.stdout.write(f'{"Invoice":<20} {"Student":<15} {"Balance B/F Orig":>18} {"Balance B/F":>15} {"Billed":>15}')
        self.stdout.write('-' * 80)
        
        for invoice in invoices:
            bf_original = invoice.balance_bf_original or invoice.balance_bf
            total_bf_original += bf_original
            
            self.stdout.write(
                f"{invoice.invoice_number:<20} "
                f"{invoice.student.admission_number:<15} "
                f"{bf_original:>18,.2f} "
                f"{invoice.balance_bf:>15,.2f} "
                f"{invoice.total_amount:>15,.2f}"
            )
        
        # Get total from all invoices
        all_invoices = term_invoices
        total_all = all_invoices.aggregate(
            total=Sum(Coalesce('balance_bf_original', 'balance_bf'))
        )['total'] or 0
        
        self.stdout.write('-' * 80)
        self.stdout.write(f'Total balance_bf_original (shown): {total_bf_original:,.2f}')
        self.stdout.write(f'Total balance_bf_original (all):    {total_all:,.2f}')
        self.stdout.write('')
        
        # Expected total based on manual calculation
        # Expected = (Bal B/F + Billed) - Prepayments
        # 17,038,697 = (Bal B/F + 16,335,500) - (-77,228)
        # Bal B/F = 17,038,697 - 16,335,500 - 77,228 = 625,969
        expected_bf = Decimal('625969')
        difference = Decimal(str(total_all)) - expected_bf
        
        self.stdout.write(f'Expected total balance_bf_original: {expected_bf:,.2f}')
        self.stdout.write(f'Actual total balance_bf_original:    {total_all:,.2f}')
        self.stdout.write(f'Difference:                          {difference:,.2f}')
        self.stdout.write('')
        
        if abs(difference - Decimal('154456')) < Decimal('1'):
            self.stdout.write(self.style.SUCCESS(
                '✓ Difference matches the 154,456 discrepancy'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'⚠ Difference ({difference:,.2f}) does not match expected (154,456.00)'
            ))

