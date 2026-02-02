"""
Investigate what happened to student 2374 between the morning audit and now.

This command will:
1. Check student status history
2. Check invoice status and when it was modified
3. Check payment allocations and when they were created
4. Check if term transition ran
5. Check if any bulk operations affected this student
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from students.models import Student
from finance.models import Invoice
from payments.models import Payment, PaymentAllocation
from academics.models import Term
from core.models import InvoiceStatus, PaymentStatus
from django.db.models import Q


class Command(BaseCommand):
    help = 'Investigate what happened to student 2374'

    def handle(self, *args, **options):
        admission_number = '2374'
        
        try:
            student = Student.objects.get(admission_number=admission_number)
        except Student.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Student {admission_number} not found'))
            return

        self.stdout.write('=' * 80)
        self.stdout.write(f'INVESTIGATION: Student {admission_number} - {student.full_name}')
        self.stdout.write('=' * 80)
        
        # 1. Student current state
        self.stdout.write('\n1. CURRENT STUDENT STATE:')
        self.stdout.write(f'   Status: {student.status}')
        self.stdout.write(f'   Status Date: {student.status_date}')
        self.stdout.write(f'   Status Reason: {student.status_reason[:200] if student.status_reason else "None"}')
        self.stdout.write(f'   Updated At: {student.updated_at}')
        self.stdout.write(f'   Created At: {student.created_at}')
        self.stdout.write(f'   balance_bf_original: {student.balance_bf_original}')
        self.stdout.write(f'   prepayment_original: {student.prepayment_original}')
        self.stdout.write(f'   credit_balance: {student.credit_balance}')
        self.stdout.write(f'   outstanding_balance: {student.outstanding_balance}')
        
        # 2. Check all invoices
        self.stdout.write('\n2. INVOICES:')
        invoices = student.invoices.all().order_by('-created_at')
        for inv in invoices:
            self.stdout.write(f'\n   Invoice: {inv.invoice_number}')
            self.stdout.write(f'   Term: {inv.term}')
            self.stdout.write(f'   Created: {inv.created_at}')
            self.stdout.write(f'   Updated: {inv.updated_at}')
            self.stdout.write(f'   is_active: {inv.is_active}')
            self.stdout.write(f'   status: {inv.status}')
            self.stdout.write(f'   balance_bf: {inv.balance_bf}')
            self.stdout.write(f'   balance_bf_original: {inv.balance_bf_original}')
            self.stdout.write(f'   total_amount: {inv.total_amount}')
            self.stdout.write(f'   amount_paid: {inv.amount_paid}')
            self.stdout.write(f'   balance: {inv.balance}')
            self.stdout.write(f'   prepayment: {inv.prepayment}')
            
        # 3. Check payments
        self.stdout.write('\n3. PAYMENTS:')
        payments = student.payments.filter(is_active=True).order_by('-payment_date')
        for p in payments:
            self.stdout.write(f'\n   Payment: {p.payment_reference}')
            self.stdout.write(f'   Amount: {p.amount}')
            self.stdout.write(f'   Date: {p.payment_date}')
            self.stdout.write(f'   Status: {p.status}')
            self.stdout.write(f'   Created: {p.created_at}')
            self.stdout.write(f'   Updated: {p.updated_at}')
            self.stdout.write(f'   Notes: {p.notes[:200] if p.notes else "None"}')
            
            # Check allocations
            allocs = p.allocations.filter(is_active=True)
            if allocs.exists():
                self.stdout.write(f'   Allocations ({allocs.count()}):')
                for a in allocs:
                    self.stdout.write(f'     - {a.invoice_item.category} ({a.invoice_item.invoice.invoice_number}): {a.amount}')
                    self.stdout.write(f'       Created: {a.created_at}, Updated: {a.updated_at}')
            else:
                self.stdout.write(f'   Allocations: None')
        
        # 4. Check if term transition could have run
        self.stdout.write('\n4. TERM TRANSITION CHECK:')
        current_term = Term.objects.filter(is_current=True).first()
        if current_term:
            self.stdout.write(f'   Current Term: {current_term}')
            self.stdout.write(f'   Current Term Start: {current_term.start_date}')
            self.stdout.write(f'   Current Term Created: {current_term.created_at}')
            self.stdout.write(f'   Current Term Updated: {current_term.updated_at}')
            
            # Find previous term
            previous_term = Term.objects.filter(
                start_date__lt=current_term.start_date
            ).exclude(pk=current_term.pk).order_by('-start_date').first()
            
            if previous_term:
                self.stdout.write(f'   Previous Term: {previous_term}')
                self.stdout.write(f'   Previous Term Start: {previous_term.start_date}')
                
                # Check if student has invoice in previous term
                prev_invoice = Invoice.objects.filter(
                    student=student,
                    term=previous_term
                ).first()
                
                if prev_invoice:
                    self.stdout.write(f'   Previous Term Invoice: {prev_invoice.invoice_number}')
                    self.stdout.write(f'     is_active: {prev_invoice.is_active}')
                    self.stdout.write(f'     balance: {prev_invoice.balance}')
                    self.stdout.write(f'     updated_at: {prev_invoice.updated_at}')
                    
                    # Check if term transition would have processed this student
                    if student.status == 'active' and student.is_active:
                        self.stdout.write(f'   ⚠️  STUDENT WAS ACTIVE - Term transition WOULD have processed this student!')
                        self.stdout.write(f'   Term transition would have:')
                        self.stdout.write(f'     - Set balance_bf_original = {prev_invoice.balance}')
                        self.stdout.write(f'     - Set credit_balance = 0 (if balance > 0)')
                        self.stdout.write(f'     - Deactivated previous term invoice')
                    else:
                        self.stdout.write(f'   ✓ Student status is {student.status} - Term transition would NOT process')
                else:
                    self.stdout.write(f'   No invoice found in previous term')
        else:
            self.stdout.write('   No current term found')
        
        # 5. Check for recent term changes
        self.stdout.write('\n5. RECENT TERM CHANGES:')
        recent_terms = Term.objects.filter(
            updated_at__gte=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        ).order_by('-updated_at')
        
        if recent_terms.exists():
            for term in recent_terms[:5]:
                self.stdout.write(f'   Term: {term} (Updated: {term.updated_at}, is_current: {term.is_current})')
        else:
            self.stdout.write('   No terms updated today')
        
        # 6. Check if student was recently updated by someone
        self.stdout.write('\n6. STUDENT UPDATE HISTORY:')
        if student.updated_at:
            hours_ago = (timezone.now() - student.updated_at).total_seconds() / 3600
            self.stdout.write(f'   Last updated: {student.updated_at} ({hours_ago:.1f} hours ago)')
            
            # Check if updated around 11:33 today
            today_1133 = timezone.now().replace(hour=11, minute=33, second=0, microsecond=0)
            if abs((student.updated_at - today_1133).total_seconds()) < 3600:  # Within 1 hour
                self.stdout.write(f'   ⚠️  Student was updated around 11:33 today!')
        
        # 7. Check invoice update times
        self.stdout.write('\n7. INVOICE UPDATE TIMES:')
        for inv in invoices:
            if inv.updated_at:
                hours_ago = (timezone.now() - inv.updated_at).total_seconds() / 3600
                self.stdout.write(f'   {inv.invoice_number}: Updated {hours_ago:.1f} hours ago ({inv.updated_at})')
        
        # 8. Check payment allocation times
        self.stdout.write('\n8. PAYMENT ALLOCATION TIMES:')
        all_allocs = PaymentAllocation.objects.filter(
            payment__student=student,
            is_active=True
        ).select_related('payment', 'invoice_item__invoice').order_by('-created_at')
        
        for alloc in all_allocs:
            hours_ago = (timezone.now() - alloc.created_at).total_seconds() / 3600
            self.stdout.write(f'   {alloc.payment.payment_reference} -> {alloc.invoice_item.category}: '
                            f'Created {hours_ago:.1f} hours ago ({alloc.created_at})')
        
        # 9. Summary and hypothesis
        self.stdout.write('\n' + '=' * 80)
        self.stdout.write('HYPOTHESIS:')
        self.stdout.write('=' * 80)
        
        # Check if student was active when term transition might have run
        if student.status == 'transferred':
            self.stdout.write('\n✓ Student is currently TRANSFERRED')
            
            # Check if there's an active invoice (shouldn't be)
            active_invoice = student.invoices.filter(is_active=True).exclude(
                status=InvoiceStatus.CANCELLED
            ).first()
            
            if active_invoice:
                self.stdout.write(f'\n⚠️  PROBLEM: Student is transferred but has ACTIVE invoice: {active_invoice.invoice_number}')
                self.stdout.write(f'   This invoice should be inactive!')
                
                # Check when invoice was created vs when student was transferred
                if student.status_date and active_invoice.created_at:
                    if active_invoice.created_at < student.status_date:
                        self.stdout.write(f'   Invoice created BEFORE student was transferred')
                        self.stdout.write(f'   Invoice created: {active_invoice.created_at}')
                        self.stdout.write(f'   Student transferred: {student.status_date}')
                        self.stdout.write(f'   ⚠️  Invoice should have been deactivated when student was transferred!')
                    else:
                        self.stdout.write(f'   Invoice created AFTER student was transferred (unusual!)')
                        self.stdout.write(f'   Invoice created: {active_invoice.created_at}')
                        self.stdout.write(f'   Student transferred: {student.status_date}')
            
            # Check if payment was allocated to invoice
            payment = payments.first()
            if payment:
                allocs = payment.allocations.filter(is_active=True)
                if allocs.exists():
                    self.stdout.write(f'\n⚠️  PROBLEM: Payment {payment.payment_reference} has allocations to invoice items!')
                    self.stdout.write(f'   Payment was made on: {payment.payment_date}')
                    self.stdout.write(f'   Student was transferred on: {student.status_date}')
                    
                    if student.status_date and payment.payment_date:
                        if payment.payment_date < student.status_date:
                            self.stdout.write(f'   ⚠️  Payment was made BEFORE student was transferred')
                            self.stdout.write(f'   This is OK - payment should have been allocated normally')
                        else:
                            self.stdout.write(f'   ⚠️  Payment was made AFTER student was transferred')
                            self.stdout.write(f'   This is WRONG - payment should NOT have been allocated to invoice!')
        
        self.stdout.write('\n' + '=' * 80)

