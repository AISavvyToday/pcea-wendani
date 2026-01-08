"""
Find invoices with incorrect balance_bf_original values that are causing the 154,456 discrepancy.
This script will identify invoices where balance_bf_original doesn't match the expected value
based on previous term outstanding balances.
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
    help = 'Find invoices with incorrect balance_bf_original values'

    def add_arguments(self, parser):
        parser.add_argument(
            '--threshold',
            type=Decimal,
            default=Decimal('1000'),
            help='Minimum difference to report (default: 1000)',
        )
        parser.add_argument(
            '--show-all',
            action='store_true',
            help='Show all invoices, not just those with discrepancies',
        )

    def handle(self, *args, **options):
        threshold = options.get('threshold')
        show_all = options.get('show_all', False)
        
        term = _get_current_term()
        if not term:
            self.stdout.write(self.style.ERROR('No current term found'))
            return
        
        self.stdout.write('=' * 80)
        self.stdout.write('FINDING INCORRECT balance_bf_original VALUES')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Term: {term}')
        self.stdout.write('')
        
        base = _invoice_base_qs()
        term_invoices = base.filter(term=term)
        invoices = term_invoices.select_related('student', 'term').order_by('student__admission_number')
        
        total_discrepancy = Decimal('0.00')
        issues_found = []
        
        self.stdout.write('Analyzing invoices...')
        self.stdout.write('-' * 80)
        
        for invoice in invoices:
            if invoice.balance_bf_original is None or invoice.balance_bf_original == 0:
                continue
            
            # Calculate what balance_bf_original SHOULD be based on previous term balances
            previous_invoices = Invoice.objects.filter(
                student=invoice.student,
                is_active=True
            ).exclude(status=InvoiceStatus.CANCELLED).exclude(term=term)
            
            # Get outstanding from previous terms
            total_outstanding_previous = previous_invoices.aggregate(
                total=Sum('balance')
            )['total'] or Decimal('0.00')
            
            # Also check student credit_balance that existed before this invoice was created
            # Since invoice creation consumes credit_balance, we need to check if there
            # were any other sources of balance_bf
            
            # The balance_bf_original should equal:
            # - total_outstanding_previous (if > 0), OR
            # - student.credit_balance that existed before invoice creation (if no previous invoices)
            # But we can't know the historical credit_balance, so we'll check against previous invoices
            
            expected_balance_bf = total_outstanding_previous
            
            # If there are no previous invoices, we can't verify against historical credit_balance
            # But we can check if balance_bf_original seems reasonable
            
            difference = invoice.balance_bf_original - expected_balance_bf
            
            if abs(difference) >= threshold or show_all:
                issues_found.append({
                    'invoice': invoice,
                    'expected': expected_balance_bf,
                    'actual': invoice.balance_bf_original,
                    'difference': difference,
                    'previous_outstanding': total_outstanding_previous,
                    'previous_invoice_count': previous_invoices.count()
                })
                total_discrepancy += difference
        
        if not issues_found:
            self.stdout.write(self.style.SUCCESS('No invoices found with significant discrepancies.'))
            return
        
        # Sort by absolute difference (largest first)
        issues_found.sort(key=lambda x: abs(x['difference']), reverse=True)
        
        self.stdout.write('')
        self.stdout.write(f'Found {len(issues_found)} invoice(s) with discrepancies >= {threshold:,.2f}')
        self.stdout.write('')
        
        # Show top discrepancies
        self.stdout.write('TOP DISCREPANCIES:')
        self.stdout.write('-' * 80)
        self.stdout.write(f'{"Invoice":<20} {"Student":<15} {"Expected":>15} {"Actual":>15} {"Difference":>15}')
        self.stdout.write('-' * 80)
        
        for issue in issues_found[:20]:  # Show top 20
            inv = issue['invoice']
            self.stdout.write(
                f"{inv.invoice_number:<20} "
                f"{inv.student.admission_number:<15} "
                f"{issue['expected']:>15,.2f} "
                f"{issue['actual']:>15,.2f} "
                f"{issue['difference']:>15,.2f}"
            )
        
        self.stdout.write('')
        self.stdout.write(f'Total discrepancy from analyzed invoices: {total_discrepancy:,.2f}')
        self.stdout.write('')
        
        # Check if total matches the 154,456
        if abs(total_discrepancy - Decimal('154456')) < Decimal('100'):
            self.stdout.write(self.style.SUCCESS(
                f'✓ Total discrepancy ({total_discrepancy:,.2f}) matches expected difference (154,456.00)'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'⚠ Total discrepancy ({total_discrepancy:,.2f}) does not match expected difference (154,456.00)'
            ))
            self.stdout.write('   May need to check all invoices or look for other sources')
        
        # Show summary by student
        self.stdout.write('')
        self.stdout.write('SUMMARY BY STUDENT (top 10 by discrepancy):')
        self.stdout.write('-' * 80)
        
        student_totals = {}
        for issue in issues_found:
            student_id = issue['invoice'].student.admission_number
            if student_id not in student_totals:
                student_totals[student_id] = Decimal('0.00')
            student_totals[student_id] += issue['difference']
        
        sorted_students = sorted(student_totals.items(), key=lambda x: abs(x[1]), reverse=True)
        
        for student_id, total_diff in sorted_students[:10]:
            self.stdout.write(f'  {student_id}: {total_diff:>15,.2f}')

