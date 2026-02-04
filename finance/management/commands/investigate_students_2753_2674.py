"""
Investigate and fix issues for students 2753 and 2674.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from decimal import Decimal
from students.models import Student
from finance.models import Invoice
from payments.models import Payment, PaymentAllocation
from core.models import InvoiceStatus, PaymentStatus


class Command(BaseCommand):
    help = 'Investigate and fix students 2753 and 2674'

    def handle(self, *args, **options):
        # Investigate student 2753
        self.stdout.write('=' * 80)
        self.stdout.write('INVESTIGATING STUDENT 2753 (Active)')
        self.stdout.write('=' * 80)
        
        try:
            student_2753 = Student.objects.get(admission_number='2753')
        except Student.DoesNotExist:
            self.stdout.write(self.style.ERROR('Student 2753 not found'))
        else:
            self._investigate_student_2753(student_2753)
        
        # Investigate student 2674
        self.stdout.write('\n' + '=' * 80)
        self.stdout.write('INVESTIGATING STUDENT 2674 (Transferred)')
        self.stdout.write('=' * 80)
        
        try:
            student_2674 = Student.objects.get(admission_number='2674')
        except Student.DoesNotExist:
            self.stdout.write(self.style.ERROR('Student 2674 not found'))
        else:
            self._investigate_student_2674(student_2674)

    def _investigate_student_2753(self, student):
        self.stdout.write(f'\nStudent: {student.full_name}')
        self.stdout.write(f'Status: {student.status}')
        self.stdout.write(f'balance_bf_original: {student.balance_bf_original}')
        self.stdout.write(f'outstanding_balance: {student.outstanding_balance}')
        self.stdout.write(f'credit_balance: {student.credit_balance}')
        
        # Get invoices
        invoices = student.invoices.filter(is_active=True).exclude(
            status=InvoiceStatus.CANCELLED
        )
        self.stdout.write(f'\nActive Invoices: {invoices.count()}')
        for inv in invoices:
            self.stdout.write(f'  Invoice: {inv.invoice_number}')
            self.stdout.write(f'    balance_bf: {inv.balance_bf}')
            self.stdout.write(f'    total_amount: {inv.total_amount}')
            self.stdout.write(f'    amount_paid: {inv.amount_paid}')
            self.stdout.write(f'    balance: {inv.balance}')
            self.stdout.write(f'    status: {inv.status}')
        
        # Get payments
        payments = student.payments.filter(
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).order_by('payment_date')
        
        total_paid = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        self.stdout.write(f'\nTotal Payments: {total_paid}')
        self.stdout.write(f'Payments ({payments.count()}):')
        for p in payments:
            self.stdout.write(f'  {p.payment_reference}: {p.amount} on {p.payment_date}')
            allocs = p.allocations.filter(is_active=True)
            if allocs.exists():
                total_alloc = allocs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                self.stdout.write(f'    Allocated: {total_alloc}')
                for a in allocs:
                    self.stdout.write(f'      - {a.invoice_item.category}: {a.amount}')
            else:
                self.stdout.write(f'    Allocated: 0.00 (NOT ALLOCATED!)')
        
        # Check allocations
        all_allocs = PaymentAllocation.objects.filter(
            payment__student=student,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED
        ).select_related('payment', 'invoice_item__invoice')
        
        total_allocated = all_allocs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        self.stdout.write(f'\nTotal Allocated: {total_allocated}')
        self.stdout.write(f'Total Paid: {total_paid}')
        self.stdout.write(f'Unallocated (should be credit): {total_paid - total_allocated}')
        self.stdout.write(f'Actual credit_balance: {student.credit_balance}')
        
        # Check invoice balance
        if invoices.exists():
            invoice = invoices.first()
            self.stdout.write(f'\nInvoice Analysis:')
            self.stdout.write(f'  Invoice balance: {invoice.balance}')
            self.stdout.write(f'  Invoice amount_paid: {invoice.amount_paid}')
            self.stdout.write(f'  Total allocated to invoice: {total_allocated}')
            self.stdout.write(f'  Expected invoice balance: {invoice.total_amount + invoice.balance_bf - invoice.prepayment - total_allocated}')
            
            if invoice.balance > 0 and student.credit_balance > 0:
                self.stdout.write(self.style.ERROR(
                    f'\n⚠️  PROBLEM: Invoice has balance {invoice.balance} but student has credit {student.credit_balance}!'
                ))
                self.stdout.write('  Payments should fully clear invoice before going to credit_balance.')

    def _investigate_student_2674(self, student):
        self.stdout.write(f'\nStudent: {student.full_name}')
        self.stdout.write(f'Status: {student.status}')
        self.stdout.write(f'balance_bf_original: {student.balance_bf_original}')
        self.stdout.write(f'outstanding_balance: {student.outstanding_balance}')
        self.stdout.write(f'credit_balance: {student.credit_balance}')
        
        # Get invoices
        invoices = student.invoices.filter(is_active=True).exclude(
            status=InvoiceStatus.CANCELLED
        )
        self.stdout.write(f'\nActive Invoices: {invoices.count()}')
        
        # Get payments
        payments = student.payments.filter(
            is_active=True,
            status=PaymentStatus.COMPLETED
        )
        total_paid = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        self.stdout.write(f'Total Paid: {total_paid}')
        
        # Check if outstanding matches balance_bf_original
        if student.outstanding_balance == student.balance_bf_original:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ Outstanding balance ({student.outstanding_balance}) matches balance_bf_original ({student.balance_bf_original})'
            ))
            self.stdout.write('  This is correct for a transferred student with no invoices.')
        else:
            self.stdout.write(self.style.WARNING(
                f'\n⚠️  Outstanding balance ({student.outstanding_balance}) does NOT match balance_bf_original ({student.balance_bf_original})'
            ))

