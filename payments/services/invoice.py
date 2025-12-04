# File: payments/services/invoice.py
# ============================================================
# RATIONALE: Handle invoice updates when payments are received
# - Updates amount_paid and balance
# - Updates invoice status
# - Optionally allocates payment to specific fee items
# ============================================================

import logging
from decimal import Decimal
from django.db import transaction as db_transaction
from django.db.models import Sum

from payments.models import Payment, PaymentAllocation
from finance.models import Invoice, InvoiceItem
from core.models import InvoiceStatus

logger = logging.getLogger(__name__)


class InvoiceService:
    """Service for managing invoice updates from payments."""
    
    @staticmethod
    @db_transaction.atomic
    def apply_payment_to_invoice(payment: Payment, invoice: Invoice) -> Invoice:
        """
        Apply a payment to an invoice, updating amounts and status.
        
        Args:
            payment: The Payment record
            invoice: The Invoice to update
        
        Returns:
            Updated Invoice instance
        """
        if not invoice:
            logger.warning(f"No invoice provided for payment {payment.payment_reference}")
            return None
        
        # Calculate total payments for this invoice
        total_paid = Payment.objects.filter(
            invoice=invoice,
            status=PaymentStatus.COMPLETED,
            is_active=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        # Update invoice
        invoice.amount_paid = total_paid
        invoice.balance = invoice.total_amount + invoice.balance_bf - invoice.prepayment - invoice.amount_paid
        
        # Update status based on balance
        if invoice.balance <= 0:
            invoice.status = InvoiceStatus.PAID
            # If overpaid, the negative balance becomes prepayment for next term
            if invoice.balance < 0:
                logger.info(f"Invoice {invoice.invoice_number} overpaid by {abs(invoice.balance)}")
        elif invoice.amount_paid > 0:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        
        invoice.save()
        
        logger.info(
            f"Updated invoice {invoice.invoice_number}: "
            f"paid={invoice.amount_paid}, balance={invoice.balance}, status={invoice.status}"
        )
        
        return invoice
    
    @staticmethod
    @db_transaction.atomic
    def allocate_payment_to_items(payment: Payment, invoice: Invoice) -> list:
        """
        Allocate payment amount to invoice items by priority.
        
        Priority order (based on FeeCategory):
        1. Tuition
        2. Examination
        3. Meals
        4. Transport
        5. Other categories
        
        Args:
            payment: The Payment record
            invoice: The Invoice containing items
        
        Returns:
            List of PaymentAllocation records created
        """
        if not invoice:
            return []
        
        # Define priority order for fee categories
        PRIORITY_ORDER = [
            'tuition',
            'examination',
            'meals',
            'boarding',
            'transport',
            'books',
            'uniform',
            'activity',
            'development',
            'other',
        ]
        
        # Get invoice items ordered by priority
        items = list(invoice.items.filter(is_active=True).order_by('category'))
        items.sort(key=lambda x: PRIORITY_ORDER.index(x.category) if x.category in PRIORITY_ORDER else 999)
        
        allocations = []
        remaining_amount = payment.amount
        
        for item in items:
            if remaining_amount <= 0:
                break
            
            # Calculate how much is already allocated to this item
            already_allocated = PaymentAllocation.objects.filter(
                invoice_item=item,
                payment__status=PaymentStatus.COMPLETED,
                payment__is_active=True
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            
            # Calculate remaining balance for this item
            item_balance = item.net_amount - already_allocated
            
            if item_balance > 0:
                # Allocate up to the item balance
                allocation_amount = min(remaining_amount, item_balance)
                
                allocation = PaymentAllocation.objects.create(
                    payment=payment,
                    invoice_item=item,
                    amount=allocation_amount
                )
                allocations.append(allocation)
                remaining_amount -= allocation_amount
                
                logger.debug(f"Allocated {allocation_amount} to {item.description}")
        
        logger.info(f"Created {len(allocations)} payment allocations for payment {payment.payment_reference}")
        return allocations


# Import PaymentStatus for the queries
from core.models import PaymentStatus