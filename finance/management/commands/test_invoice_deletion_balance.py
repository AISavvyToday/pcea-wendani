"""
Test script to verify invoice deletion properly adjusts student outstanding balance.
Scenario: Student with bal_bf 10500, invoice created then deleted - verify outstanding balance shows only 10500.
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum, Q
from decimal import Decimal

from finance.models import Invoice
from students.models import Student
from core.models import InvoiceStatus


class Command(BaseCommand):
    help = 'Test invoice deletion balance adjustment scenario'

    def add_arguments(self, parser):
        parser.add_argument(
            '--student-id',
            type=str,
            help='Student admission number to test (optional)',
        )

    def handle(self, *args, **options):
        student_id = options.get('student_id')
        
        self.stdout.write('=' * 80)
        self.stdout.write('INVOICE DELETION BALANCE TEST')
        self.stdout.write('=' * 80)
        self.stdout.write('')
        
        if student_id:
            try:
                student = Student.objects.get(admission_number=student_id)
            except Student.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Student with admission number {student_id} not found'))
                return
            students = [student]
        else:
            # Find students with deleted invoices that had balance_bf
            # This helps identify test cases
            deleted_invoices_with_bf = Invoice.objects.filter(
                is_active=False,
                balance_bf__gt=0
            ).select_related('student').distinct('student')
            
            if deleted_invoices_with_bf.count() == 0:
                self.stdout.write(self.style.WARNING('No deleted invoices with balance_bf found for testing'))
                self.stdout.write('')
                self.stdout.write('To test manually:')
                self.stdout.write('  1. Find a student with balance_bf > 0')
                self.stdout.write('  2. Create an invoice for that student')
                self.stdout.write('  3. Delete the invoice')
                self.stdout.write('  4. Verify student outstanding balance = original balance_bf')
                return
            
            students = [inv.student for inv in deleted_invoices_with_bf[:5]]  # Test up to 5 students
            self.stdout.write(f'Found {deleted_invoices_with_bf.count()} student(s) with deleted invoices that had balance_bf')
            self.stdout.write(f'Testing first {len(students)} student(s)')
            self.stdout.write('')
        
        for student in students:
            self.test_student_balance(student)
            self.stdout.write('')

    def test_student_balance(self, student):
        """Test balance calculation for a specific student"""
        self.stdout.write(f'Student: {student.admission_number} - {student.full_name}')
        self.stdout.write('-' * 80)
        
        # Get active invoices
        active_invoices = Invoice.objects.filter(
            student=student,
            is_active=True
        ).exclude(status=InvoiceStatus.CANCELLED)
        
        # Get deleted invoices
        deleted_invoices = Invoice.objects.filter(
            student=student,
            is_active=False
        )
        
        # Calculate outstanding from active invoices
        total_outstanding_active = active_invoices.aggregate(
            total=Sum('balance')
        )['total'] or Decimal('0.00')
        
        # Get student credit_balance
        student_credit = student.credit_balance or Decimal('0.00')
        
        # Check deleted invoices with balance_bf
        deleted_with_bf = deleted_invoices.filter(balance_bf__gt=0)
        
        self.stdout.write(f'  Active invoices count:            {active_invoices.count()}')
        self.stdout.write(f'  Total outstanding (active):       {total_outstanding_active:>20,.2f}')
        self.stdout.write(f'  Student credit_balance:           {student_credit:>20,.2f}')
        self.stdout.write(f'  Deleted invoices count:            {deleted_invoices.count()}')
        
        if deleted_with_bf.count() > 0:
            self.stdout.write('')
            self.stdout.write('  Deleted invoices with balance_bf:')
            for inv in deleted_with_bf:
                self.stdout.write(
                    f'    - {inv.invoice_number}: balance_bf={inv.balance_bf:,.2f}, '
                    f'prepayment={inv.prepayment:,.2f}'
                )
            
            # Expected outstanding should be:
            # - Outstanding from active invoices (if any)
            # - Plus student credit_balance (which should include restored balance_bf from deleted invoices)
            expected_outstanding = total_outstanding_active + student_credit
            
            self.stdout.write('')
            self.stdout.write(f'  Expected outstanding balance:    {expected_outstanding:>20,.2f}')
            
            # Verify: If there are no active invoices, outstanding should equal student credit_balance
            # which should include the balance_bf from deleted invoices
            if active_invoices.count() == 0:
                if abs(student_credit - sum(inv.balance_bf for inv in deleted_with_bf)) < Decimal('0.01'):
                    self.stdout.write(self.style.SUCCESS('  ✓ Balance correctly restored to student credit_balance'))
                else:
                    self.stdout.write(self.style.ERROR('  ✗ Balance not correctly restored'))
                    self.stdout.write(f'     Expected credit_balance to include balance_bf from deleted invoices')
            else:
                self.stdout.write('  Note: Student has active invoices, so outstanding includes both')
        else:
            self.stdout.write('  No deleted invoices with balance_bf found')
        
        # Show all invoices for reference
        if active_invoices.count() > 0:
            self.stdout.write('')
            self.stdout.write('  Active invoices:')
            for inv in active_invoices:
                self.stdout.write(
                    f'    - {inv.invoice_number}: billed={inv.total_amount:,.2f}, '
                    f'paid={inv.amount_paid:,.2f}, balance={inv.balance:,.2f}, '
                    f'balance_bf={inv.balance_bf:,.2f}'
                )

