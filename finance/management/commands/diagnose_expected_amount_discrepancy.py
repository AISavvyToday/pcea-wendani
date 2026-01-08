"""
Diagnostic script to identify the source of the 154,456 discrepancy in expected amount calculation.
This will help identify exactly where the issue is coming from.
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum, Q, Count, F
from django.db.models.functions import Coalesce
from decimal import Decimal

from finance.models import Invoice
from students.models import Student
from core.models import InvoiceStatus
from portal.views import _get_current_term, _invoice_base_qs


class Command(BaseCommand):
    help = 'Diagnose the 154,456 discrepancy in expected amount calculation'

    def add_arguments(self, parser):
        parser.add_argument(
            '--expected',
            type=Decimal,
            default=Decimal('17038697'),
            help='Expected manual calculation result (default: 17038697)',
        )

    def handle(self, *args, **options):
        expected_manual = options.get('expected')
        
        term = _get_current_term()
        if not term:
            self.stdout.write(self.style.ERROR('No current term found'))
            return
        
        self.stdout.write('=' * 80)
        self.stdout.write('DIAGNOSTIC: Expected Amount Discrepancy Investigation')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Term: {term}')
        self.stdout.write(f'Expected (Manual): {expected_manual:,.2f}')
        self.stdout.write('')
        
        # ========================================================================
        # 1. Check active invoices
        # ========================================================================
        self.stdout.write('1. ACTIVE INVOICES ANALYSIS')
        self.stdout.write('-' * 80)
        
        base = _invoice_base_qs()
        term_invoices = base.filter(term=term)
        invoices = term_invoices.select_related('student', 'term', 'term__academic_year')
        
        # Count invoices
        invoice_count = invoices.count()
        self.stdout.write(f'   Active invoices count: {invoice_count}')
        
        # Check for NULL balance_bf_original
        null_bf_original = invoices.filter(
            balance_bf__gt=0
        ).filter(
            Q(balance_bf_original__isnull=True) | Q(balance_bf_original=0)
        )
        null_count = null_bf_original.count()
        if null_count > 0:
            self.stdout.write(self.style.WARNING(
                f'   ⚠ Found {null_count} invoices with balance_bf > 0 but balance_bf_original is NULL/0'
            ))
            total_bf_missing = null_bf_original.aggregate(total=Sum('balance_bf'))['total'] or 0
            self.stdout.write(f'   Total balance_bf in these invoices: {total_bf_missing:,.2f}')
        
        # Calculate from active invoices
        billed = invoices.aggregate(total=Sum('total_amount'))['total'] or 0
        billed = Decimal(str(billed))
        
        balances_bf_from_invoices = invoices.aggregate(
            total=Sum(Coalesce('balance_bf_original', 'balance_bf'))
        )['total'] or 0
        balances_bf_from_invoices = Decimal(str(balances_bf_from_invoices))
        
        prepayments_from_invoices = invoices.aggregate(total=Sum('prepayment'))['total'] or 0
        prepayments_from_invoices = Decimal(str(prepayments_from_invoices))
        
        self.stdout.write(f'   Billed: {billed:,.2f}')
        self.stdout.write(f'   Balance B/F (from invoices): {balances_bf_from_invoices:,.2f}')
        self.stdout.write(f'   Prepayments (from invoices): {prepayments_from_invoices:,.2f}')
        self.stdout.write('')
        
        # ========================================================================
        # 2. Check deleted invoices for this term
        # ========================================================================
        self.stdout.write('2. DELETED INVOICES ANALYSIS')
        self.stdout.write('-' * 80)
        
        deleted_invoices = Invoice.objects.filter(
            term=term,
            is_active=False,
            student__status='active'
        ).exclude(status=InvoiceStatus.CANCELLED)
        
        deleted_count = deleted_invoices.count()
        self.stdout.write(f'   Deleted invoices count: {deleted_count}')
        
        if deleted_count > 0:
            # Check if deleted invoices have balance_bf_original that might be counted
            deleted_bf_original = deleted_invoices.aggregate(
                total=Sum(Coalesce('balance_bf_original', 'balance_bf'))
            )['total'] or 0
            deleted_bf_original = Decimal(str(deleted_bf_original))
            
            deleted_billed = deleted_invoices.aggregate(total=Sum('total_amount'))['total'] or 0
            deleted_billed = Decimal(str(deleted_billed))
            
            self.stdout.write(f'   Total balance_bf_original in deleted invoices: {deleted_bf_original:,.2f}')
            self.stdout.write(f'   Total billed in deleted invoices: {deleted_billed:,.2f}')
            self.stdout.write(self.style.WARNING(
                '   ⚠ These should NOT be counted in dashboard (deleted invoices are excluded)'
            ))
        self.stdout.write('')
        
        # ========================================================================
        # 3. Check students without invoices
        # ========================================================================
        self.stdout.write('3. STUDENTS WITHOUT INVOICES ANALYSIS')
        self.stdout.write('-' * 80)
        
        students_without_invoices = Student.objects.filter(
            status='active'
        ).exclude(
            invoices__term=term,
            invoices__is_active=True
        ).exclude(
            invoices__status=InvoiceStatus.CANCELLED
        ).distinct()
        
        student_count = students_without_invoices.count()
        self.stdout.write(f'   Students without active invoices: {student_count}')
        
        # Check how many of these have deleted invoices
        students_with_deleted = students_without_invoices.filter(
            invoices__term=term,
            invoices__is_active=False
        ).distinct().count()
        
        if students_with_deleted > 0:
            self.stdout.write(self.style.WARNING(
                f'   ⚠ {students_with_deleted} of these students have DELETED invoices for this term'
            ))
            self.stdout.write('   These students will have their credit_balance counted')
        
        balances_bf_from_students = students_without_invoices.aggregate(
            total=Sum('credit_balance', filter=Q(credit_balance__gt=0))
        )['total'] or 0
        balances_bf_from_students = Decimal(str(balances_bf_from_students))
        
        prepayments_from_students_raw = students_without_invoices.aggregate(
            total=Sum('credit_balance', filter=Q(credit_balance__lt=0))
        )['total'] or 0
        prepayments_from_students = abs(Decimal(str(prepayments_from_students_raw))) if prepayments_from_students_raw else Decimal('0')
        
        self.stdout.write(f'   Balance B/F (from students): {balances_bf_from_students:,.2f}')
        self.stdout.write(f'   Prepayments (from students): {prepayments_from_students:,.2f}')
        self.stdout.write('')
        
        # ========================================================================
        # 4. Calculate totals and compare
        # ========================================================================
        self.stdout.write('4. CALCULATION SUMMARY')
        self.stdout.write('-' * 80)
        
        balances_bf = balances_bf_from_invoices + balances_bf_from_students
        prepayments = prepayments_from_invoices + prepayments_from_students
        
        total_expected = (balances_bf + billed) - prepayments
        
        self.stdout.write(f'   Balance B/F (invoices):     {balances_bf_from_invoices:>20,.2f}')
        self.stdout.write(f'   Balance B/F (students):     {balances_bf_from_students:>20,.2f}')
        self.stdout.write(f'   Total Balance B/F:          {balances_bf:>20,.2f}')
        self.stdout.write('')
        self.stdout.write(f'   Billed:                     {billed:>20,.2f}')
        self.stdout.write('')
        self.stdout.write(f'   Prepayments (invoices):     {prepayments_from_invoices:>20,.2f}')
        self.stdout.write(f'   Prepayments (students):     {prepayments_from_students:>20,.2f}')
        self.stdout.write(f'   Total Prepayments:          {prepayments:>20,.2f}')
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write(f'   CALCULATED EXPECTED:        {total_expected:>20,.2f}')
        self.stdout.write(f'   EXPECTED (MANUAL):          {expected_manual:>20,.2f}')
        self.stdout.write('=' * 80)
        
        difference = total_expected - expected_manual
        self.stdout.write(f'   DIFFERENCE:                 {difference:>20,.2f}')
        self.stdout.write('')
        
        if abs(difference) < Decimal('0.01'):
            self.stdout.write(self.style.SUCCESS('   ✓ Calculations match!'))
        else:
            self.stdout.write(self.style.ERROR(f'   ✗ Discrepancy of {abs(difference):,.2f}'))
            self.stdout.write('')
            
            # ========================================================================
            # 5. Potential issues analysis
            # ========================================================================
            self.stdout.write('5. POTENTIAL ISSUES IDENTIFIED')
            self.stdout.write('-' * 80)
            
            # Check if deleted invoices' balance_bf_original matches students' credit_balance
            if deleted_count > 0 and students_with_deleted > 0:
                self.stdout.write('   Checking if deleted invoices are causing double-counting...')
                
                # Get students with deleted invoices and their credit_balance
                students_with_deleted_invoices = students_without_invoices.filter(
                    invoices__term=term,
                    invoices__is_active=False
                ).distinct()
                
                total_restored_credit = students_with_deleted_invoices.aggregate(
                    total=Sum('credit_balance', filter=Q(credit_balance__gt=0))
                )['total'] or 0
                total_restored_credit = Decimal(str(total_restored_credit))
                
                self.stdout.write(f'   Total credit_balance from students with deleted invoices: {total_restored_credit:,.2f}')
                self.stdout.write(f'   Total balance_bf_original from deleted invoices: {deleted_bf_original:,.2f}')
                
                if abs(total_restored_credit - deleted_bf_original) > Decimal('0.01'):
                    self.stdout.write(self.style.WARNING(
                        f'   ⚠ MISMATCH: Restored credit_balance ({total_restored_credit:,.2f}) != '
                        f'deleted invoices balance_bf_original ({deleted_bf_original:,.2f})'
                    ))
                    self.stdout.write('   This could indicate incorrect restoration during invoice deletion')
            
            # Check for invoices with balance_bf != balance_bf_original (shouldn't happen)
            mismatched = invoices.filter(
                balance_bf__gt=0
            ).exclude(
                Q(balance_bf_original__isnull=True) | Q(balance_bf_original=0)
            ).exclude(
                balance_bf=F('balance_bf_original')
            )
            
            if mismatched.exists():
                mismatch_count = mismatched.count()
                self.stdout.write(self.style.WARNING(
                    f'   ⚠ Found {mismatch_count} invoices where balance_bf != balance_bf_original'
                ))
                self.stdout.write('   This is normal if payments have been made to balance_bf')
            
            self.stdout.write('')
            self.stdout.write('RECOMMENDATIONS:')
            self.stdout.write('  1. Verify deleted invoices are properly excluded from calculations')
            self.stdout.write('  2. Check if students with deleted invoices have correct credit_balance')
            self.stdout.write('  3. Ensure balance_bf_original is populated for all invoices')
            self.stdout.write('  4. Review invoice deletion logic to ensure proper balance restoration')

