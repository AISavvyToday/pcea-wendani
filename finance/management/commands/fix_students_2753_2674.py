"""
Fix issues for students 2753 and 2674.
- 2753: Reallocate unallocated payment to clear invoice before credit_balance
- 2674: Set balance_bf_original to match outstanding_balance
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from decimal import Decimal
from students.models import Student
from finance.models import Invoice
from payments.models import Payment, PaymentAllocation
from payments.services.invoice import InvoiceService
from core.models import InvoiceStatus, PaymentStatus


class Command(BaseCommand):
    help = 'Fix students 2753 and 2674'

    @transaction.atomic
    def handle(self, *args, **options):
        # Fix student 2753
        self.stdout.write('=' * 80)
        self.stdout.write('FIXING STUDENT 2753 (Active)')
        self.stdout.write('=' * 80)
        
        try:
            student_2753 = Student.objects.get(admission_number='2753')
        except Student.DoesNotExist:
            self.stdout.write(self.style.ERROR('Student 2753 not found'))
        else:
            self._fix_student_2753(student_2753)
        
        # Fix student 2674
        self.stdout.write('\n' + '=' * 80)
        self.stdout.write('FIXING STUDENT 2674 (Transferred)')
        self.stdout.write('=' * 80)
        
        try:
            student_2674 = Student.objects.get(admission_number='2674')
        except Student.DoesNotExist:
            self.stdout.write(self.style.ERROR('Student 2674 not found'))
        else:
            self._fix_student_2674(student_2674)

    def _fix_student_2753(self, student):
        self.stdout.write(f'\nStudent: {student.full_name}')
        
        # Get active invoice
        invoice = student.invoices.filter(is_active=True).exclude(
            status=InvoiceStatus.CANCELLED
        ).first()
        
        if not invoice:
            self.stdout.write(self.style.ERROR('No active invoice found'))
            return
        
        self.stdout.write(f'Invoice: {invoice.invoice_number}')
        self.stdout.write(f'  Current balance: {invoice.balance}')
        self.stdout.write(f'  Current amount_paid: {invoice.amount_paid}')
        self.stdout.write(f'  Current credit_balance: {student.credit_balance}')
        
        # Find unallocated payment
        payments = student.payments.filter(
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).order_by('payment_date')
        
        unallocated_payment = None
        for payment in payments:
            allocs = payment.allocations.filter(is_active=True)
            total_alloc = allocs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            unallocated = payment.amount - total_alloc
            if unallocated > 0:
                unallocated_payment = payment
                self.stdout.write(f'\nFound unallocated payment: {payment.payment_reference}')
                self.stdout.write(f'  Amount: {payment.amount}')
                self.stdout.write(f'  Allocated: {total_alloc}')
                self.stdout.write(f'  Unallocated: {unallocated}')
                break
        
        if not unallocated_payment:
            self.stdout.write(self.style.WARNING('No unallocated payment found'))
            return
        
        # Check if invoice still has balance
        InvoiceService._recalculate_invoice_fields(invoice)
        if invoice.balance <= 0:
            self.stdout.write(self.style.SUCCESS('Invoice is already fully paid'))
            return
        
        # Allocate unallocated amount to invoice
        unallocated = unallocated_payment.amount - (
            unallocated_payment.allocations.filter(is_active=True).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')
        )
        
        amount_to_allocate = min(unallocated, invoice.balance)
        
        self.stdout.write(f'\nAllocating {amount_to_allocate} to invoice...')
        
        # Allocate to invoice items
        allocated = InvoiceService._allocate_amount_to_invoice_items(
            payment=unallocated_payment,
            invoice=invoice,
            amount_to_apply=amount_to_allocate,
        )
        
        # Recalculate invoice
        InvoiceService._recalculate_invoice_fields(invoice)
        
        # Update credit_balance - reduce by the amount that was allocated
        if allocated > 0:
            student.credit_balance = max(
                Decimal('0.00'),
                (student.credit_balance or Decimal('0.00')) - allocated
            )
            student.save(update_fields=['credit_balance', 'updated_at'])
        
        # Recompute outstanding balance
        student.recompute_outstanding_balance()
        
        self.stdout.write(self.style.SUCCESS(f'\n✓ Fixed student 2753:'))
        self.stdout.write(f'  Invoice balance: {invoice.balance}')
        self.stdout.write(f'  Invoice amount_paid: {invoice.amount_paid}')
        self.stdout.write(f'  Credit balance: {student.credit_balance}')
        self.stdout.write(f'  Outstanding balance: {student.outstanding_balance}')

    def _fix_student_2674(self, student):
        self.stdout.write(f'\nStudent: {student.full_name}')
        self.stdout.write(f'Status: {student.status}')
        self.stdout.write(f'Current balance_bf_original: {student.balance_bf_original}')
        self.stdout.write(f'Current outstanding_balance: {student.outstanding_balance}')
        
        # For transferred student with no invoices, outstanding_balance should match balance_bf_original
        if student.outstanding_balance != student.balance_bf_original:
            self.stdout.write(f'\nSetting balance_bf_original to {student.outstanding_balance}...')
            student.balance_bf_original = student.outstanding_balance
            student.save(update_fields=['balance_bf_original', 'updated_at'])
            self.stdout.write(self.style.SUCCESS(f'✓ Updated balance_bf_original to {student.balance_bf_original}'))
        else:
            self.stdout.write(self.style.SUCCESS('✓ balance_bf_original already matches outstanding_balance'))

