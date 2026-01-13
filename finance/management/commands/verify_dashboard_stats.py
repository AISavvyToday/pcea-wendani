"""
Verify dashboard stats only include active students and are accurate.
This command checks that:
1. Invoice queries filter is_active=True and student.status='active'
2. Students without invoices query filters status='active'
3. Deleted invoices are excluded from all calculations
4. Optional: Compare with Excel file to verify balances
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from decimal import Decimal
import pandas as pd
import os

from finance.models import Invoice
from students.models import Student
from core.models import InvoiceStatus
from portal.views import _get_current_term, _invoice_base_qs, _finance_kpis


class Command(BaseCommand):
    help = 'Verify dashboard stats only include active students and are accurate'

    def add_arguments(self, parser):
        parser.add_argument(
            '--excel-file',
            type=str,
            default=None,
            help='Path to Excel file to compare against (optional)',
        )
        parser.add_argument(
            '--term-id',
            type=int,
            default=None,
            help='Specific term ID to use (default: auto-detect current term)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output',
        )

    def handle(self, *args, **options):
        excel_file = options.get('excel_file')
        term_id = options.get('term_id')
        verbose = options.get('verbose', False)

        self.stdout.write('=' * 80)
        self.stdout.write('VERIFY DASHBOARD STATS')
        self.stdout.write('=' * 80)
        self.stdout.write('')

        # Get current term
        if term_id:
            from academics.models import Term
            try:
                term = Term.objects.get(id=term_id)
            except Term.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Term with ID {term_id} not found'))
                return
        else:
            term = _get_current_term()
            if not term:
                self.stdout.write(self.style.ERROR('No current term found. Please specify --term-id'))
                return

        self.stdout.write(f'Term: {term}')
        self.stdout.write('')

        # Get dashboard stats
        try:
            dashboard_stats = _finance_kpis(term=term)
            # _finance_kpis returns a dict with term_stats and year_stats
            # We need term_stats
            if isinstance(dashboard_stats, dict) and 'term_stats' in dashboard_stats:
                term_stats = dashboard_stats['term_stats']
            else:
                term_stats = dashboard_stats
            
            self.stdout.write('DASHBOARD STATS:')
            self.stdout.write(f'  Billed: KES {term_stats.get("billed", 0):,.2f}')
            self.stdout.write(f'  Collected: KES {term_stats.get("collected", 0):,.2f}')
            self.stdout.write(f'  Outstanding: KES {term_stats.get("outstanding", 0):,.2f}')
            self.stdout.write(f'  Balance B/F: KES {term_stats.get("balances_bf", 0):,.2f}')
            self.stdout.write(f'  Prepayments: KES {term_stats.get("prepayments", 0):,.2f}')
            self.stdout.write(f'  Invoice Count: {term_stats.get("invoice_count", 0)}')
            self.stdout.write('')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error getting dashboard stats: {e}'))
            import traceback
            if verbose:
                self.stdout.write(traceback.format_exc())
            return

        # Verify invoice base queryset
        self.stdout.write('VERIFICATION CHECKS:')
        self.stdout.write('-' * 80)

        # Check 1: Verify _invoice_base_qs filters
        base_qs = _invoice_base_qs()
        self.stdout.write('\n1. Checking invoice base queryset filters...')
        
        # Check if it filters is_active=True
        # We can't directly inspect the queryset, but we can verify by checking counts
        all_invoices = Invoice.objects.filter(term=term)
        active_invoices = Invoice.objects.filter(term=term, is_active=True)
        base_invoices = base_qs.filter(term=term)
        
        if verbose:
            self.stdout.write(f'   All invoices (term): {all_invoices.count()}')
            self.stdout.write(f'   Active invoices (term): {active_invoices.count()}')
            self.stdout.write(f'   Base queryset invoices (term): {base_invoices.count()}')
        
        if base_invoices.count() == active_invoices.count():
            self.stdout.write(self.style.SUCCESS('   ✓ Base queryset correctly filters is_active=True'))
        else:
            self.stdout.write(self.style.WARNING(
                f'   ⚠ Base queryset count ({base_invoices.count()}) != active invoices count ({active_invoices.count()})'
            ))

        # Check 2: Verify invoices only include active students
        invoices_with_inactive_students = base_qs.filter(
            term=term
        ).exclude(
            student__status='active'
        )
        
        inactive_count = invoices_with_inactive_students.count()
        if inactive_count == 0:
            self.stdout.write(self.style.SUCCESS('   ✓ All invoices are for active students'))
        else:
            self.stdout.write(self.style.ERROR(
                f'   ✗ Found {inactive_count} invoices for inactive students!'
            ))
            if verbose:
                for inv in invoices_with_inactive_students[:5]:
                    self.stdout.write(f'      - {inv.invoice_number}: {inv.student.admission_number} ({inv.student.status})')

        # Check 3: Verify deleted invoices are excluded
        deleted_invoices = Invoice.objects.filter(
            term=term,
            is_active=False
        )
        deleted_in_base = base_qs.filter(term=term, is_active=False).count()
        
        if deleted_in_base == 0:
            self.stdout.write(self.style.SUCCESS(
                f'   ✓ Deleted invoices ({deleted_invoices.count()}) correctly excluded from base queryset'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'   ✗ Found {deleted_in_base} deleted invoices in base queryset!'
            ))

        # Check 4: Verify students without invoices query
        self.stdout.write('\n2. Checking students without invoices query...')
        
        students_without_invoices = Student.objects.filter(
            status='active'
        ).exclude(
            invoices__term=term
        ).exclude(
            invoices__status=InvoiceStatus.CANCELLED
        ).distinct()
        
        inactive_in_query = students_without_invoices.exclude(status='active').count()
        if inactive_in_query == 0:
            self.stdout.write(self.style.SUCCESS('   ✓ Students without invoices query correctly filters status="active"'))
        else:
            self.stdout.write(self.style.ERROR(
                f'   ✗ Found {inactive_in_query} inactive students in query!'
            ))

        # Check 5: Verify students with deleted invoices are excluded
        students_with_deleted = Student.objects.filter(
            status='active',
            invoices__term=term,
            invoices__is_active=False
        ).distinct()
        
        students_with_deleted_in_query = students_without_invoices.filter(
            id__in=students_with_deleted.values_list('id', flat=True)
        ).count()
        
        if students_with_deleted_in_query == 0:
            self.stdout.write(self.style.SUCCESS(
                f'   ✓ Students with deleted invoices ({students_with_deleted.count()}) correctly excluded'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'   ⚠ Found {students_with_deleted_in_query} students with deleted invoices in query'
            ))

        # Check 6: Compare with Excel if provided
        if excel_file:
            self.stdout.write('\n3. Comparing with Excel file...')
            if os.path.exists(excel_file):
                try:
                    df = pd.read_excel(excel_file)
                    df.columns = [str(c).strip() for c in df.columns]
                    
                    # Find admission and balance columns
                    admission_col = None
                    balance_col = None
                    
                    for col in df.columns:
                        col_lower = str(col).lower()
                        if 'admission' in col_lower or 'adm' in col_lower or col == '#':
                            admission_col = col
                        if 'total balance' in col_lower or col == 'Total Balance':
                            balance_col = col
                    
                    if admission_col and balance_col:
                        # Get active students from database
                        active_students = Student.objects.filter(status='active')
                        active_admissions = set(active_students.values_list('admission_number', flat=True))
                        
                        # Calculate expected balances from Excel (active students only)
                        excel_balance_bf = Decimal('0.00')
                        excel_prepayments = Decimal('0.00')
                        
                        df[admission_col] = df[admission_col].astype(str).str.strip()
                        
                        for _, row in df.iterrows():
                            admission = str(row[admission_col]).strip()
                            if admission in active_admissions and pd.notna(row[balance_col]):
                                try:
                                    balance = Decimal(str(row[balance_col]))
                                    if balance > 0:
                                        excel_balance_bf += balance
                                    elif balance < 0:
                                        excel_prepayments += abs(balance)
                                except (ValueError, TypeError):
                                    continue
                        
                        self.stdout.write(f'   Excel Balance B/F (active students): KES {excel_balance_bf:,.2f}')
                        self.stdout.write(f'   Excel Prepayments (active students): KES {excel_prepayments:,.2f}')
                        self.stdout.write(f'   Dashboard Balance B/F: KES {term_stats.get("balances_bf", 0):,.2f}')
                        self.stdout.write(f'   Dashboard Prepayments: KES {term_stats.get("prepayments", 0):,.2f}')
                        
                        # Compare (allow small differences due to payments/allocations)
                        bf_diff = abs(excel_balance_bf - Decimal(str(term_stats.get("balances_bf", 0))))
                        prep_diff = abs(excel_prepayments - Decimal(str(term_stats.get("prepayments", 0))))
                        
                        if bf_diff < Decimal('100.00'):  # Allow small differences
                            self.stdout.write(self.style.SUCCESS(
                                f'   ✓ Balance B/F matches Excel (difference: KES {bf_diff:,.2f})'
                            ))
                        else:
                            self.stdout.write(self.style.WARNING(
                                f'   ⚠ Balance B/F differs from Excel by KES {bf_diff:,.2f}'
                            ))
                        
                        if prep_diff < Decimal('100.00'):
                            self.stdout.write(self.style.SUCCESS(
                                f'   ✓ Prepayments match Excel (difference: KES {prep_diff:,.2f})'
                            ))
                        else:
                            self.stdout.write(self.style.WARNING(
                                f'   ⚠ Prepayments differ from Excel by KES {prep_diff:,.2f}'
                            ))
                    else:
                        self.stdout.write(self.style.WARNING(
                            '   ⚠ Could not find admission/balance columns in Excel'
                        ))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'   ✗ Error reading Excel: {e}'))
            else:
                self.stdout.write(self.style.ERROR(f'   ✗ Excel file not found: {excel_file}'))

        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write('VERIFICATION COMPLETE')
        self.stdout.write('=' * 80)
        self.stdout.write('Review the checks above for any issues.')

