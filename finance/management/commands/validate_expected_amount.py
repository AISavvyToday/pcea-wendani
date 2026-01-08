"""
Validation script to verify expected amount calculation matches manual calculation.
Expected amount = bal_bf + billed - prepayments
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from decimal import Decimal

from finance.models import Invoice
from students.models import Student
from core.models import InvoiceStatus
from portal.views import _get_current_term, _invoice_base_qs


class Command(BaseCommand):
    help = 'Validate expected amount calculation and compare with manual calculation'

    def add_arguments(self, parser):
        parser.add_argument(
            '--expected',
            type=Decimal,
            help='Expected manual calculation result (e.g., 17038697)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed breakdown of calculation',
        )

    def handle(self, *args, **options):
        expected_manual = options.get('expected')
        verbose = options.get('verbose', False)
        
        term = _get_current_term()
        if not term:
            self.stdout.write(self.style.ERROR('No current term found'))
            return
        
        self.stdout.write(f'Validating expected amount calculation for term: {term}')
        self.stdout.write('=' * 80)
        self.stdout.write('')
        
        # Get base invoice queryset (same as dashboard)
        base = _invoice_base_qs()
        term_invoices = base.filter(term=term)
        
        # Calculate billed
        invoices = term_invoices.select_related('student', 'term', 'term__academic_year')
        billed = invoices.aggregate(total=Sum('total_amount'))['total'] or 0
        billed = Decimal(str(billed))
        
        # Calculate balances_bf using Coalesce (same as fixed code)
        balances_bf_from_invoices = invoices.aggregate(
            total=Sum(Coalesce('balance_bf_original', 'balance_bf'))
        )['total'] or 0
        balances_bf_from_invoices = Decimal(str(balances_bf_from_invoices))
        
        # Calculate prepayments
        prepayments_from_invoices = invoices.aggregate(total=Sum('prepayment'))['total'] or 0
        prepayments_from_invoices = Decimal(str(prepayments_from_invoices))
        
        # Get balances from students without invoices
        students_without_invoices = Student.objects.filter(
            status='active'
        ).exclude(
            invoices__term=term,
            invoices__is_active=True
        ).exclude(
            invoices__status=InvoiceStatus.CANCELLED
        ).distinct()
        
        balances_bf_from_students = students_without_invoices.aggregate(
            total=Sum('credit_balance', filter=Q(credit_balance__gt=0))
        )['total'] or 0
        balances_bf_from_students = Decimal(str(balances_bf_from_students))
        
        prepayments_from_students_raw = students_without_invoices.aggregate(
            total=Sum('credit_balance', filter=Q(credit_balance__lt=0))
        )['total'] or 0
        prepayments_from_students = abs(Decimal(str(prepayments_from_students_raw))) if prepayments_from_students_raw else Decimal('0')
        
        # Combine
        balances_bf = balances_bf_from_invoices + balances_bf_from_students
        prepayments = prepayments_from_invoices + prepayments_from_students
        
        # Calculate expected amount
        total_expected = (balances_bf + billed) - prepayments
        
        # Display results
        self.stdout.write('CALCULATION BREAKDOWN:')
        self.stdout.write('-' * 80)
        self.stdout.write(f'  Balance B/F (from invoices):     {balances_bf_from_invoices:>20,.2f}')
        if verbose and balances_bf_from_students > 0:
            self.stdout.write(f'  Balance B/F (from students):     {balances_bf_from_students:>20,.2f}')
        self.stdout.write(f'  Total Balance B/F:                {balances_bf:>20,.2f}')
        self.stdout.write('')
        self.stdout.write(f'  Billed:                            {billed:>20,.2f}')
        self.stdout.write('')
        self.stdout.write(f'  Prepayments (from invoices):      {prepayments_from_invoices:>20,.2f}')
        if verbose and prepayments_from_students > 0:
            self.stdout.write(f'  Prepayments (from students):      {prepayments_from_students:>20,.2f}')
        self.stdout.write(f'  Total Prepayments:                 {prepayments:>20,.2f}')
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write(f'  EXPECTED AMOUNT:                   {total_expected:>20,.2f}')
        self.stdout.write('=' * 80)
        self.stdout.write('')
        
        # Check for NULL balance_bf_original values
        null_balance_bf_original = invoices.filter(
            balance_bf__gt=0
        ).filter(
            Q(balance_bf_original__isnull=True) | Q(balance_bf_original=0)
        ).count()
        
        if null_balance_bf_original > 0:
            self.stdout.write(self.style.WARNING(
                f'WARNING: Found {null_balance_bf_original} invoice(s) with balance_bf > 0 but balance_bf_original is NULL/0'
            ))
            self.stdout.write(self.style.WARNING(
                'Run: python manage.py populate_balance_bf_original to fix this'
            ))
            self.stdout.write('')
        
        # Compare with manual calculation if provided
        if expected_manual:
            difference = total_expected - expected_manual
            self.stdout.write(f'Manual calculation:                {expected_manual:>20,.2f}')
            self.stdout.write(f'System calculation:                {total_expected:>20,.2f}')
            self.stdout.write(f'Difference:                        {difference:>20,.2f}')
            self.stdout.write('')
            
            if abs(difference) < Decimal('0.01'):
                self.stdout.write(self.style.SUCCESS('✓ Calculations match!'))
            else:
                self.stdout.write(self.style.ERROR(f'✗ Calculations differ by {abs(difference):,.2f}'))
                self.stdout.write('')
                self.stdout.write('Investigation needed:')
                self.stdout.write('  1. Check for NULL balance_bf_original values')
                self.stdout.write('  2. Verify all invoices are included in calculation')
                self.stdout.write('  3. Check for deleted invoices that might affect calculation')
        else:
            self.stdout.write('To compare with manual calculation, use --expected option:')
            self.stdout.write('  python manage.py validate_expected_amount --expected=17038697')
        
        # Show invoice count
        invoice_count = invoices.count()
        self.stdout.write('')
        self.stdout.write(f'Total active invoices in term: {invoice_count}')

