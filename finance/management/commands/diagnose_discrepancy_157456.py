"""
Comprehensive diagnostic script to investigate the 157,456 discrepancy in expected amount.
This script analyzes:
1. Deleted invoices and their impact
2. Payment allocations to deleted invoices
3. Students with deleted invoices and credit_balance restoration
4. Double-counting issues
5. Payment impact on calculations
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum, Q, Count, F
from django.db.models.functions import Coalesce
from decimal import Decimal

from finance.models import Invoice
from students.models import Student
from payments.models import Payment, PaymentAllocation
from core.models import InvoiceStatus, PaymentStatus
from portal.views import _get_current_term, _invoice_base_qs


class Command(BaseCommand):
    help = 'Comprehensive diagnostic for 157,456 discrepancy investigation'

    def add_arguments(self, parser):
        parser.add_argument(
            '--expected',
            type=Decimal,
            default=Decimal('17038697'),
            help='Expected manual calculation result (default: 17038697)',
        )
        parser.add_argument(
            '--dashboard-expected',
            type=Decimal,
            help='Current dashboard expected amount (e.g., 17109603)',
        )

    def handle(self, *args, **options):
        expected_manual = options.get('expected')
        dashboard_expected = options.get('dashboard_expected')
        
        term = _get_current_term()
        if not term:
            self.stdout.write(self.style.ERROR('No current term found'))
            return
        
        self.stdout.write('=' * 80)
        self.stdout.write('COMPREHENSIVE DISCREPANCY DIAGNOSTIC')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Term: {term}')
        self.stdout.write(f'Expected (Manual): {expected_manual:,.2f}')
        if dashboard_expected:
            self.stdout.write(f'Dashboard Expected: {dashboard_expected:,.2f}')
        self.stdout.write('')
        
        # ========================================================================
        # 1. ACTIVE INVOICES ANALYSIS
        # ========================================================================
        self.stdout.write('1. ACTIVE INVOICES ANALYSIS')
        self.stdout.write('-' * 80)
        
        base = _invoice_base_qs()
        term_invoices = base.filter(term=term)
        invoices = term_invoices.select_related('student', 'term', 'term__academic_year')
        
        invoice_count = invoices.count()
        self.stdout.write(f'   Active invoices: {invoice_count}')
        
        # Calculate components
        billed = invoices.aggregate(total=Sum('total_amount'))['total'] or 0
        billed = Decimal(str(billed))
        
        balances_bf_from_invoices = invoices.aggregate(
            total=Sum(Coalesce('balance_bf_original', 'balance_bf'))
        )['total'] or 0
        balances_bf_from_invoices = Decimal(str(balances_bf_from_invoices))
        
        prepayments_from_invoices = invoices.aggregate(total=Sum('prepayment'))['total'] or 0
        prepayments_from_invoices = Decimal(str(prepayments_from_invoices))
        
        # Check for NULL balance_bf_original
        null_bf_original = invoices.filter(
            balance_bf__gt=0
        ).filter(
            Q(balance_bf_original__isnull=True) | Q(balance_bf_original=0)
        )
        null_count = null_bf_original.count()
        if null_count > 0:
            total_bf_missing = null_bf_original.aggregate(total=Sum('balance_bf'))['total'] or 0
            self.stdout.write(self.style.WARNING(
                f'   ⚠ {null_count} invoices with balance_bf > 0 but balance_bf_original is NULL/0'
            ))
            self.stdout.write(f'   Total balance_bf missing: {total_bf_missing:,.2f}')
        
        self.stdout.write(f'   Billed: {billed:,.2f}')
        self.stdout.write(f'   Balance B/F (from invoices): {balances_bf_from_invoices:,.2f}')
        self.stdout.write(f'   Prepayments (from invoices): {prepayments_from_invoices:,.2f}')
        self.stdout.write('')
        
        # ========================================================================
        # 2. DELETED INVOICES DETAILED ANALYSIS
        # ========================================================================
        self.stdout.write('2. DELETED INVOICES DETAILED ANALYSIS')
        self.stdout.write('-' * 80)
        
        deleted_invoices = Invoice.objects.filter(
            term=term,
            is_active=False
        ).exclude(status=InvoiceStatus.CANCELLED).select_related('student')
        
        deleted_count = deleted_invoices.count()
        self.stdout.write(f'   Deleted invoices count: {deleted_count}')
        
        deleted_bf_original = Decimal('0')
        deleted_billed = Decimal('0')
        deleted_amount_paid = Decimal('0')
        deleted_balance = Decimal('0')
        
        if deleted_count > 0:
            # Get deleted invoice details
            deleted_bf_original = deleted_invoices.aggregate(
                total=Sum(Coalesce('balance_bf_original', 'balance_bf'))
            )['total'] or 0
            deleted_bf_original = Decimal(str(deleted_bf_original))
            
            deleted_billed = deleted_invoices.aggregate(total=Sum('total_amount'))['total'] or 0
            deleted_billed = Decimal(str(deleted_billed))
            
            deleted_amount_paid = deleted_invoices.aggregate(total=Sum('amount_paid'))['total'] or 0
            deleted_amount_paid = Decimal(str(deleted_amount_paid))
            
            deleted_balance = deleted_invoices.aggregate(total=Sum('balance'))['total'] or 0
            deleted_balance = Decimal(str(deleted_balance))
            
            self.stdout.write(f'   Total balance_bf_original: {deleted_bf_original:,.2f}')
            self.stdout.write(f'   Total billed: {deleted_billed:,.2f}')
            self.stdout.write(f'   Total amount_paid: {deleted_amount_paid:,.2f}')
            self.stdout.write(f'   Total balance: {deleted_balance:,.2f}')
            self.stdout.write('')
            
            # Check payments to deleted invoices
            self.stdout.write('   Checking payments to deleted invoices...')
            deleted_invoice_ids = list(deleted_invoices.values_list('id', flat=True))
            
            if deleted_invoice_ids:
                # Get payment allocations to deleted invoices
                allocations_to_deleted = PaymentAllocation.objects.filter(
                    invoice_item__invoice_id__in=deleted_invoice_ids,
                    is_active=True,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED
                )
                
                total_allocated_to_deleted = allocations_to_deleted.aggregate(
                    total=Sum('amount')
                )['total'] or 0
                total_allocated_to_deleted = Decimal(str(total_allocated_to_deleted))
                
                # Get payments that were allocated to deleted invoices
                payments_to_deleted = Payment.objects.filter(
                    allocations__invoice_item__invoice_id__in=deleted_invoice_ids,
                    is_active=True,
                    status=PaymentStatus.COMPLETED
                ).distinct()
                
                payment_count = payments_to_deleted.count()
                total_payment_amount = payments_to_deleted.aggregate(
                    total=Sum('amount')
                )['total'] or 0
                total_payment_amount = Decimal(str(total_payment_amount))
                
                self.stdout.write(f'   Payments to deleted invoices: {payment_count}')
                self.stdout.write(f'   Total payment amount: {total_payment_amount:,.2f}')
                self.stdout.write(f'   Total allocated to deleted invoices: {total_allocated_to_deleted:,.2f}')
                
                # Show individual deleted invoices with payments
                if payment_count > 0:
                    self.stdout.write('')
                    self.stdout.write('   Deleted invoices with payments:')
                    for inv in deleted_invoices.filter(amount_paid__gt=0):
                        inv_allocations = PaymentAllocation.objects.filter(
                            invoice_item__invoice=inv,
                            is_active=True,
                            payment__is_active=True,
                            payment__status=PaymentStatus.COMPLETED
                        ).aggregate(total=Sum('amount'))['total'] or 0
                        
                        self.stdout.write(
                            f'     {inv.invoice_number} - {inv.student.admission_number}: '
                            f'bf_original={inv.balance_bf_original or 0:,.2f}, '
                            f'paid={inv.amount_paid:,.2f}, '
                            f'allocated={inv_allocations:,.2f}'
                        )
        else:
            self.stdout.write('   No deleted invoices found')
        
        self.stdout.write('')
        
        # ========================================================================
        # 3. STUDENTS WITHOUT INVOICES ANALYSIS
        # ========================================================================
        self.stdout.write('3. STUDENTS WITHOUT INVOICES ANALYSIS')
        self.stdout.write('-' * 80)
        
        students_without_invoices = Student.objects.filter(
            status__in=['active', 'transferred', 'graduated']
        ).exclude(
            invoices__term=term
        ).exclude(
            invoices__status=InvoiceStatus.CANCELLED
        ).distinct()
        
        student_count = students_without_invoices.count()
        self.stdout.write(f'   Students without invoices: {student_count}')
        
        # Check how many have deleted invoices
        students_with_deleted = Student.objects.filter(
            status__in=['active', 'transferred', 'graduated'],
            invoices__term=term,
            invoices__is_active=False
        ).exclude(
            invoices__status=InvoiceStatus.CANCELLED
        ).distinct().count()
        
        total_restored_credit = Decimal('0')
        count_in_students_without = 0
        credit_in_students_without = Decimal('0')
        
        if students_with_deleted > 0:
            self.stdout.write(self.style.WARNING(
                f'   ⚠ {students_with_deleted} students have DELETED invoices for this term'
            ))
            
            # Get students with deleted invoices and their credit_balance
            students_with_deleted_invoices = Student.objects.filter(
                status__in=['active', 'transferred', 'graduated'],
                invoices__term=term,
                invoices__is_active=False
            ).exclude(
                invoices__status=InvoiceStatus.CANCELLED
            ).distinct()
            
            total_restored_credit = students_with_deleted_invoices.aggregate(
                total=Sum('credit_balance', filter=Q(credit_balance__gt=0))
            )['total'] or 0
            total_restored_credit = Decimal(str(total_restored_credit))
            
            # Check if they're also in "students without invoices"
            students_with_deleted_and_no_active = students_with_deleted_invoices.exclude(
                invoices__term=term,
                invoices__is_active=True
            ).exclude(
                invoices__status=InvoiceStatus.CANCELLED
            ).distinct()
            
            count_in_students_without = students_with_deleted_and_no_active.count()
            credit_in_students_without = students_with_deleted_and_no_active.aggregate(
                total=Sum('credit_balance', filter=Q(credit_balance__gt=0))
            )['total'] or 0
            credit_in_students_without = Decimal(str(credit_in_students_without))
            
            self.stdout.write(f'   Total credit_balance from students with deleted invoices: {total_restored_credit:,.2f}')
            self.stdout.write(f'   Students with deleted invoices AND no active invoices: {count_in_students_without}')
            self.stdout.write(f'   Credit_balance from these students: {credit_in_students_without:,.2f}')
            
            # Compare with deleted invoices' balance_bf_original
            if deleted_count > 0:
                mismatch = abs(total_restored_credit - deleted_bf_original)
                if mismatch > Decimal('0.01'):
                    self.stdout.write(self.style.ERROR(
                        f'   ✗ MISMATCH: Restored credit ({total_restored_credit:,.2f}) != '
                        f'deleted bf_original ({deleted_bf_original:,.2f})'
                    ))
                    self.stdout.write(f'   Difference: {mismatch:,.2f}')
                else:
                    self.stdout.write(self.style.SUCCESS(
                        '   ✓ Restored credit matches deleted balance_bf_original'
                    ))
        
        # Calculate balances from students without invoices
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
        # 4. DASHBOARD CALCULATION
        # ========================================================================
        self.stdout.write('4. DASHBOARD CALCULATION')
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
        self.stdout.write(f'   Total Prepayments:         {prepayments:>20,.2f}')
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write(f'   CALCULATED EXPECTED:        {total_expected:>20,.2f}')
        self.stdout.write(f'   EXPECTED (MANUAL):          {expected_manual:>20,.2f}')
        if dashboard_expected:
            self.stdout.write(f'   DASHBOARD EXPECTED:         {dashboard_expected:>20,.2f}')
        self.stdout.write('=' * 80)
        
        difference = total_expected - expected_manual
        self.stdout.write(f'   DIFFERENCE:                 {difference:>20,.2f}')
        self.stdout.write('')
        
        # ========================================================================
        # 5. ROOT CAUSE ANALYSIS
        # ========================================================================
        self.stdout.write('5. ROOT CAUSE ANALYSIS')
        self.stdout.write('-' * 80)
        
        if abs(difference) > Decimal('0.01'):
            self.stdout.write(self.style.ERROR(f'   ✗ Discrepancy of {abs(difference):,.2f}'))
            self.stdout.write('')
            
            # Analyze potential causes
            potential_causes = []
            
            # Cause 1: Double counting deleted invoices
            if deleted_count > 0 and students_with_deleted > 0:
                if credit_in_students_without > 0:
                    potential_causes.append({
                        'issue': 'Double counting deleted invoices',
                        'description': (
                            f'Deleted invoices have balance_bf_original={deleted_bf_original:,.2f} '
                            f'(excluded from dashboard), but students have credit_balance='
                            f'{credit_in_students_without:,.2f} (included in dashboard). '
                            f'If these match, it\'s correct. If not, there\'s a mismatch.'
                        ),
                        'impact': abs(credit_in_students_without - deleted_bf_original)
                    })
            
            # Cause 2: Payments to deleted invoices affecting calculations
            if deleted_count > 0 and deleted_amount_paid > 0:
                potential_causes.append({
                    'issue': 'Payments to deleted invoices',
                    'description': (
                        f'Deleted invoices had {deleted_amount_paid:,.2f} in payments. '
                        f'These payments are still counted in "collected" but the deleted invoice '
                        f'balance_bf_original is excluded. This creates a mismatch.'
                    ),
                    'impact': deleted_amount_paid
                })
            
            # Cause 3: NULL balance_bf_original
            if null_count > 0:
                potential_causes.append({
                    'issue': 'NULL balance_bf_original values',
                    'description': (
                        f'{null_count} invoices have balance_bf > 0 but balance_bf_original is NULL/0. '
                        f'These will use balance_bf instead, which may be incorrect if payments were made.'
                    ),
                    'impact': total_bf_missing
                })
            
            # Cause 4: Students with deleted invoices but also active invoices
            if deleted_count > 0:
                students_with_both = Student.objects.filter(
                    status__in=['active', 'transferred', 'graduated'],
                    invoices__term=term,
                    invoices__is_active=False
                ).exclude(
                    invoices__status=InvoiceStatus.CANCELLED
                ).filter(
                    invoices__term=term,
                    invoices__is_active=True
                ).exclude(
                    invoices__status=InvoiceStatus.CANCELLED
                ).distinct().count()
                
                if students_with_both > 0:
                    potential_causes.append({
                        'issue': 'Students with both deleted and active invoices',
                        'description': (
                            f'{students_with_both} students have both deleted and active invoices. '
                            f'Their credit_balance restoration might be incorrect.'
                        ),
                        'impact': Decimal('0')  # Unknown impact
                    })
            
            # Print potential causes
            for i, cause in enumerate(potential_causes, 1):
                self.stdout.write(f'   {i}. {cause["issue"]}')
                self.stdout.write(f'      {cause["description"]}')
                if cause['impact'] > 0:
                    self.stdout.write(f'      Potential impact: {cause["impact"]:,.2f}')
                self.stdout.write('')
            
            # ========================================================================
            # 6. RECOMMENDATIONS
            # ========================================================================
            self.stdout.write('6. RECOMMENDATIONS')
            self.stdout.write('-' * 80)
            
            recommendations = []
            
            if deleted_count > 0:
                recommendations.append(
                    'Review invoice deletion logic: Ensure credit_balance restoration matches '
                    'balance_bf_original exactly, accounting for any payments made.'
                )
                
                if deleted_amount_paid > 0:
                    recommendations.append(
                        'Handle payments to deleted invoices: Consider reversing payment allocations '
                        'or adjusting calculations to account for payments to deleted invoices.'
                    )
            
            if null_count > 0:
                recommendations.append(
                    f'Populate balance_bf_original: Run populate_balance_bf_original command '
                    f'to fix {null_count} invoices with NULL values.'
                )
            
            recommendations.append(
                'Verify students without invoices: Ensure students with deleted invoices are '
                'correctly excluded from "students without invoices" if they have active invoices.'
            )
            
            recommendations.append(
                'Check payment allocations: Verify that payments allocated to deleted invoices '
                'are not causing double-counting in collected amounts.'
            )
            
            for i, rec in enumerate(recommendations, 1):
                self.stdout.write(f'   {i}. {rec}')
            
        else:
            self.stdout.write(self.style.SUCCESS('   ✓ Calculations match!'))
        
        self.stdout.write('')
        self.stdout.write('=' * 80)



