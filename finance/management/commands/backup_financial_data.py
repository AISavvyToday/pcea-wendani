"""
Backup financial data before making critical changes.
Exports invoices, payments, and student balances to CSV files.
"""
import csv
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db.models import Sum
from decimal import Decimal

from finance.models import Invoice
from payments.models import Payment, PaymentAllocation
from students.models import Student
from core.models import InvoiceStatus


class Command(BaseCommand):
    help = 'Backup financial data (invoices, payments, student balances) to CSV files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            default='financial_backups',
            help='Directory to save backup files (default: financial_backups)'
        )

    def handle(self, *args, **options):
        output_dir = options['output_dir']
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        self.stdout.write(self.style.SUCCESS(f'Starting financial data backup at {timestamp}'))
        
        # Backup invoices
        self.backup_invoices(output_dir, timestamp)
        
        # Backup payments
        self.backup_payments(output_dir, timestamp)
        
        # Backup student balances
        self.backup_student_balances(output_dir, timestamp)
        
        # Backup summary statistics
        self.backup_summary_stats(output_dir, timestamp)
        
        self.stdout.write(self.style.SUCCESS(f'\nBackup completed successfully!'))
        self.stdout.write(self.style.SUCCESS(f'Files saved to: {output_dir}'))

    def backup_invoices(self, output_dir, timestamp):
        """Backup all invoices"""
        filename = f'{output_dir}/invoices_backup_{timestamp}.csv'
        
        invoices = Invoice.objects.all().select_related('student', 'term')
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Invoice ID', 'Invoice Number', 'Student Admission Number', 'Student Name',
                'Term', 'Subtotal', 'Discount Amount', 'Total Amount', 'Amount Paid',
                'Balance', 'Balance BF', 'Balance BF Original', 'Prepayment',
                'Status', 'Is Active', 'Issue Date', 'Due Date', 'Created At'
            ])
            
            for inv in invoices:
                writer.writerow([
                    inv.id,
                    inv.invoice_number,
                    inv.student.admission_number if inv.student else '',
                    inv.student.full_name if inv.student else '',
                    str(inv.term) if inv.term else '',
                    inv.subtotal,
                    inv.discount_amount,
                    inv.total_amount,
                    inv.amount_paid,
                    inv.balance,
                    inv.balance_bf,
                    inv.balance_bf_original,
                    inv.prepayment,
                    inv.status,
                    inv.is_active,
                    inv.issue_date,
                    inv.due_date,
                    inv.created_at,
                ])
        
        self.stdout.write(f'  - Backed up {invoices.count()} invoices to {filename}')

    def backup_payments(self, output_dir, timestamp):
        """Backup all payments"""
        filename = f'{output_dir}/payments_backup_{timestamp}.csv'
        
        payments = Payment.objects.all().select_related('student', 'invoice')
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Payment ID', 'Student Admission Number', 'Student Name',
                'Invoice Number', 'Amount', 'Payment Date', 'Payment Method',
                'Status', 'Is Active', 'Reference Number', 'Created At'
            ])
            
            for pmt in payments:
                writer.writerow([
                    pmt.id,
                    pmt.student.admission_number if pmt.student else '',
                    pmt.student.full_name if pmt.student else '',
                    pmt.invoice.invoice_number if pmt.invoice else '',
                    pmt.amount,
                    pmt.payment_date,
                    pmt.payment_method,
                    pmt.status,
                    pmt.is_active,
                    pmt.reference_number,
                    pmt.created_at,
                ])
        
        self.stdout.write(f'  - Backed up {payments.count()} payments to {filename}')

    def backup_student_balances(self, output_dir, timestamp):
        """Backup student balances and outstanding amounts"""
        filename = f'{output_dir}/student_balances_backup_{timestamp}.csv'
        
        students = Student.objects.filter(status='active').select_related('current_class')
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Student ID', 'Admission Number', 'Student Name', 'Class',
                'Credit Balance', 'Status', 'Active Invoices Count',
                'Total Outstanding (from invoices)', 'Created At'
            ])
            
            for student in students:
                # Get active invoices for this student
                active_invoices = Invoice.objects.filter(
                    student=student,
                    is_active=True
                ).exclude(status=InvoiceStatus.CANCELLED)
                
                total_outstanding = active_invoices.aggregate(
                    total=Sum('balance')
                )['total'] or Decimal('0.00')
                
                writer.writerow([
                    student.id,
                    student.admission_number,
                    student.full_name,
                    str(student.current_class) if student.current_class else '',
                    student.credit_balance,
                    student.status,
                    active_invoices.count(),
                    total_outstanding,
                    student.created_at,
                ])
        
        self.stdout.write(f'  - Backed up {students.count()} student balances to {filename}')

    def backup_summary_stats(self, output_dir, timestamp):
        """Backup summary statistics"""
        filename = f'{output_dir}/summary_stats_backup_{timestamp}.csv'
        
        from portal.views import _finance_kpis, _get_current_term
        
        term = _get_current_term()
        kpis = _finance_kpis(term)
        term_stats = kpis.get('term_stats', {})
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['Term', str(term) if term else 'None'])
            writer.writerow(['Billed', term_stats.get('billed', 0)])
            writer.writerow(['Collected', term_stats.get('collected', 0)])
            writer.writerow(['Outstanding', term_stats.get('outstanding', 0)])
            writer.writerow(['Balances BF', term_stats.get('balances_bf', 0)])
            writer.writerow(['Prepayments', term_stats.get('prepayments', 0)])
            writer.writerow(['Invoice Count', term_stats.get('invoice_count', 0)])
            
            # Calculate expected amount
            balances_bf = Decimal(str(term_stats.get('balances_bf', 0)))
            billed = Decimal(str(term_stats.get('billed', 0)))
            prepayments = Decimal(str(term_stats.get('prepayments', 0)))
            expected = (balances_bf + billed) - prepayments
            writer.writerow(['Total Expected (calculated)', expected])
        
        self.stdout.write(f'  - Backed up summary statistics to {filename}')

