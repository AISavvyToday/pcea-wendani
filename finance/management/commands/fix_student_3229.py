"""
Fix script for student 3229 (Roberto Mwebi Njeru)
The payment PAY-20260127-00049 was never allocated to the invoice.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from students.models import Student
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from decimal import Decimal
from core.models import InvoiceStatus, PaymentStatus


class Command(BaseCommand):
    help = "Fix student 3229 payment allocation issue"
    
    def handle(self, *args, **options):
        # Get student and related records
        student = Student.objects.get(admission_number='3229')
        payment = Payment.objects.get(payment_reference='PAY-20260127-00049')
        invoice = Invoice.objects.get(student=student, is_active=True)

        self.stdout.write("=" * 80)
        self.stdout.write("BEFORE FIX")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Student credit_balance: {student.credit_balance}")
        self.stdout.write(f"Student outstanding_balance: {student.outstanding_balance}")
        self.stdout.write(f"Invoice amount_paid: {invoice.amount_paid}")
        self.stdout.write(f"Invoice balance: {invoice.balance}")
        self.stdout.write(f"Invoice status: {invoice.status}")
        self.stdout.write(f"Payment allocations count: {payment.allocations.count()}")

        # FIX: Allocate the payment to invoice items
        with transaction.atomic():
            PRIORITY_ORDER = ["balance_bf", "tuition", "meals", "examination", "activity", "admission", "transport"]
            
            def priority_key(category):
                try:
                    return PRIORITY_ORDER.index(category)
                except ValueError:
                    return 999
            
            items = list(invoice.items.filter(is_active=True))
            items.sort(key=lambda it: (priority_key(it.category), it.id))
            
            remaining = payment.amount
            total_allocated = Decimal('0.00')
            
            self.stdout.write("")
            self.stdout.write("=" * 80)
            self.stdout.write("ALLOCATING PAYMENT")
            self.stdout.write("=" * 80)
            
            for item in items:
                if remaining <= 0:
                    break
                
                already_allocated = PaymentAllocation.objects.filter(
                    invoice_item=item,
                    is_active=True,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                
                item_due = (item.net_amount or Decimal('0.00')) - already_allocated
                
                if item_due <= 0:
                    self.stdout.write(f"  {item.description}: Already fully allocated")
                    continue
                
                applied = min(item_due, remaining)
                
                PaymentAllocation.objects.create(
                    payment=payment,
                    invoice_item=item,
                    amount=applied
                )
                
                self.stdout.write(f"  {item.description}: Allocated {applied}")
                total_allocated += applied
                remaining -= applied
            
            self.stdout.write(f"\nTotal allocated: {total_allocated}")
            self.stdout.write(f"Remaining (credit): {remaining}")
            
            # Update invoice fields
            allocations_total = PaymentAllocation.objects.filter(
                invoice_item__invoice=invoice,
                is_active=True,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            
            invoice.amount_paid = allocations_total
            invoice.balance = (
                (invoice.total_amount or Decimal('0.00'))
                + (invoice.balance_bf or Decimal('0.00'))
                - (invoice.prepayment or Decimal('0.00'))
                - (invoice.amount_paid or Decimal('0.00'))
            )
            
            if invoice.balance <= 0:
                invoice.status = InvoiceStatus.PAID
            elif invoice.amount_paid > 0:
                invoice.status = InvoiceStatus.PARTIALLY_PAID
            else:
                invoice.status = InvoiceStatus.OVERDUE
            
            invoice.save(update_fields=['amount_paid', 'balance', 'status', 'updated_at'])
            
            # Update student credit_balance
            student.credit_balance = remaining
            
            # Update payment notes
            payment.notes = "PAYBILL | Fully allocated to invoice INV-2026-00608"
            payment.save(update_fields=['notes', 'updated_at'])
            
            # Recompute student outstanding balance
            student.recompute_outstanding_balance()

        # Refresh from DB
        student.refresh_from_db()
        invoice.refresh_from_db()

        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("AFTER FIX")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Student credit_balance: {student.credit_balance}")
        self.stdout.write(f"Student outstanding_balance: {student.outstanding_balance}")
        self.stdout.write(f"Invoice amount_paid: {invoice.amount_paid}")
        self.stdout.write(f"Invoice balance: {invoice.balance}")
        self.stdout.write(f"Invoice status: {invoice.status}")
        self.stdout.write(f"Payment allocations count: {payment.allocations.count()}")

        self.stdout.write("\nAllocations created:")
        for alloc in payment.allocations.all():
            self.stdout.write(f"  - {alloc.invoice_item.description}: {alloc.amount}")

        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("FIX COMPLETE!"))
        self.stdout.write("=" * 80)

