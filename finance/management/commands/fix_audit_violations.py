"""
Fix audit violations for students with credit_balance issues and mismatched balances.
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
    help = 'Fix audit violations for students with credit_balance and outstanding_balance issues'

    def add_arguments(self, parser):
        parser.add_argument(
            '--admission-numbers',
            type=str,
            help='Comma-separated admission numbers to fix (e.g., 2775,2982,2894,3050,3101,3194)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        admission_numbers = options.get('admission_numbers', '').split(',') if options.get('admission_numbers') else []
        dry_run = options.get('dry_run', False)
        
        # Students with credit_balance violations
        credit_violations = ['2775', '2982']
        # Students without invoices but mismatched balances
        no_invoice_mismatches = ['2894', '3050', '3101', '3194']
        
        all_students = list(set(credit_violations + no_invoice_mismatches + admission_numbers))
        all_students = [s.strip() for s in all_students if s.strip()]
        
        if not all_students:
            self.stdout.write(self.style.ERROR('No students specified'))
            return
        
        for adm_num in all_students:
            try:
                student = Student.objects.get(admission_number=adm_num)
            except Student.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Student {adm_num} not found'))
                continue
            
            self.stdout.write(f'\n{"="*80}')
            self.stdout.write(f'FIXING STUDENT {adm_num}: {student.full_name}')
            self.stdout.write(f'{"="*80}')
            
            # Check if student has active invoices
            active_invoices = student.invoices.filter(is_active=True).exclude(
                status=InvoiceStatus.CANCELLED
            )
            
            if active_invoices.exists():
                self._fix_student_with_invoices(student, active_invoices, dry_run)
            else:
                self._fix_student_without_invoices(student, dry_run)
    
    def _fix_student_with_invoices(self, student, invoices, dry_run):
        """Fix student with invoices - ensure credit_balance only exists when outstanding=0"""
        self.stdout.write(f'\nStudent has {invoices.count()} active invoice(s)')
        
        # Calculate invoice balances
        total_invoice_balance = invoices.aggregate(
            total=Sum('balance')
        )['total'] or Decimal('0.00')
        
        current_outstanding = student.outstanding_balance or Decimal('0.00')
        current_credit = student.credit_balance or Decimal('0.00')
        
        self.stdout.write(f'  Current outstanding_balance: {current_outstanding}')
        self.stdout.write(f'  Current credit_balance: {current_credit}')
        self.stdout.write(f'  Total invoice balance: {total_invoice_balance}')
        
        # Fix outstanding_balance to match invoice balances
        if current_outstanding != total_invoice_balance:
            self.stdout.write(f'\n  Fixing outstanding_balance: {current_outstanding} → {total_invoice_balance}')
            if not dry_run:
                student.outstanding_balance = total_invoice_balance
                student.save(update_fields=['outstanding_balance', 'updated_at'])
        
        # If outstanding > 0, credit_balance should be 0
        if total_invoice_balance > 0 and current_credit > 0:
            self.stdout.write(f'\n  ⚠️  VIOLATION: Outstanding balance > 0 but credit_balance > 0')
            self.stdout.write(f'     Reallocating credit_balance to clear invoices...')
            
            if not dry_run:
                # Reallocate credit to invoices by finding a payment that went to credit
                # and creating allocations from it
                credit_to_use = min(current_credit, total_invoice_balance)
                
                # Find the oldest invoice with balance
                invoice = invoices.filter(balance__gt=0).order_by('issue_date').first()
                if invoice:
                    # Find a payment that has unallocated amount (went to credit)
                    # We'll use the most recent payment that has credit
                    payments = Payment.objects.filter(
                        student=student,
                        is_active=True,
                        status=PaymentStatus.COMPLETED
                    ).order_by('-payment_date', '-created_at')
                    
                    # Find payment with unallocated amount
                    payment_to_use = None
                    for payment in payments:
                        total_allocated = PaymentAllocation.objects.filter(
                            payment=payment,
                            is_active=True
                        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                        unallocated = payment.amount - total_allocated
                        if unallocated > 0:
                            payment_to_use = payment
                            break
                    
                    if payment_to_use:
                        # Allocate the credit amount from this payment to the invoice
                        # Find invoice items that need payment (by priority)
                        from payments.services.invoice import InvoiceService
                        
                        # Allocate to invoice items
                        allocated = InvoiceService._allocate_amount_to_invoice_items(
                            payment=payment_to_use,
                            invoice=invoice,
                            amount_to_apply=credit_to_use,
                        )
                        
                        # Recalculate invoice
                        InvoiceService._recalculate_invoice_fields(invoice)
                        
                        # Reduce credit_balance
                        student.credit_balance = current_credit - allocated
                        student.save(update_fields=['credit_balance', 'updated_at'])
                        
                        # Recompute outstanding
                        student.recompute_outstanding_balance()
                        
                        self.stdout.write(f'     ✓ Reallocated {allocated} from credit to invoice {invoice.invoice_number} via payment {payment_to_use.payment_reference}')
                    else:
                        # No payment found - just adjust balances manually
                        # This shouldn't happen, but handle it gracefully
                        self.stdout.write(f'     ⚠️  No payment found with unallocated amount. Adjusting invoice manually...')
                        invoice.amount_paid = (invoice.amount_paid or Decimal('0.00')) + credit_to_use
                        invoice.save()
                        
                        student.credit_balance = current_credit - credit_to_use
                        student.save(update_fields=['credit_balance', 'updated_at'])
                        student.recompute_outstanding_balance()
                        
                        self.stdout.write(f'     ✓ Adjusted invoice {invoice.invoice_number} amount_paid (no allocation created)')
        
        # Final state
        student.refresh_from_db()
        self.stdout.write(f'\n  Final state:')
        self.stdout.write(f'    outstanding_balance: {student.outstanding_balance}')
        self.stdout.write(f'    credit_balance: {student.credit_balance}')
    
    def _fix_student_without_invoices(self, student, dry_run):
        """Fix student without invoices - set outstanding_balance = balance_bf_original - total_paid"""
        self.stdout.write(f'\nStudent has NO active invoices')
        
        balance_bf_original = student.balance_bf_original or Decimal('0.00')
        prepayment_original = student.prepayment_original or Decimal('0.00')
        
        total_paid = Payment.objects.filter(
            student=student,
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Expected outstanding = balance_bf_original - total_paid
        expected_outstanding = max(Decimal('0.00'), balance_bf_original - total_paid)
        
        # Expected credit = prepayment_original + overpayment
        overpayment = max(Decimal('0.00'), total_paid - balance_bf_original)
        expected_credit = prepayment_original + overpayment
        
        current_outstanding = student.outstanding_balance or Decimal('0.00')
        current_credit = student.credit_balance or Decimal('0.00')
        
        self.stdout.write(f'  balance_bf_original: {balance_bf_original}')
        self.stdout.write(f'  total_paid: {total_paid}')
        self.stdout.write(f'  Current outstanding: {current_outstanding}')
        self.stdout.write(f'  Expected outstanding: {expected_outstanding}')
        self.stdout.write(f'  Current credit: {current_credit}')
        self.stdout.write(f'  Expected credit: {expected_credit}')
        
        if current_outstanding != expected_outstanding or current_credit != expected_credit:
            self.stdout.write(f'\n  Fixing balances...')
            if not dry_run:
                student.outstanding_balance = expected_outstanding
                student.credit_balance = expected_credit
                student.save(update_fields=['outstanding_balance', 'credit_balance', 'updated_at'])
                self.stdout.write(f'     ✓ Updated outstanding_balance to {expected_outstanding}')
                self.stdout.write(f'     ✓ Updated credit_balance to {expected_credit}')
        else:
            self.stdout.write(f'\n  ✓ Balances are already correct')

