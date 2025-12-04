# File: payments/services/payment.py
# ============================================================
# RATIONALE: Handle creation of Payment records from bank transactions
# - Creates Payment linked to Student and Invoice
# - Generates payment reference and receipt number
# - Links BankTransaction to Payment
# ============================================================

import logging
from decimal import Decimal
from django.utils import timezone
from django.db import transaction as db_transaction

from payments.models import Payment, BankTransaction
from students.models import Student
from finance.models import Invoice
from core.models import PaymentMethod, PaymentStatus
from payments.exceptions import PaymentProcessingError

logger = logging.getLogger(__name__)


class PaymentService:
    """Service for creating and managing payment records."""
    
    GATEWAY_TO_METHOD = {
        'equity': PaymentMethod.EQUITY_BANK,
        'coop': PaymentMethod.COOP_BANK,
        'mpesa': PaymentMethod.MPESA,
    }
    
    @staticmethod
    @db_transaction.atomic
    def create_payment_from_bank_transaction(
        bank_tx: BankTransaction,
        student: Student,
        invoice: Invoice = None,
        payer_name: str = '',
        payer_phone: str = ''
    ) -> Payment:
        """
        Create a Payment record from a BankTransaction.
        
        Args:
            bank_tx: The BankTransaction record
            student: The Student the payment is for
            invoice: Optional Invoice to link (can be None for prepayment)
            payer_name: Name of the payer
            payer_phone: Phone number of the payer
        
        Returns:
            Payment instance
        """
        try:
            # Determine payment method from gateway
            payment_method = PaymentService.GATEWAY_TO_METHOD.get(
                bank_tx.gateway, 
                PaymentMethod.BANK_TRANSFER
            )
            
            # Create payment record
            payment = Payment.objects.create(
                student=student,
                invoice=invoice,
                amount=bank_tx.amount,
                payment_method=payment_method,
                status=PaymentStatus.COMPLETED,
                payment_date=bank_tx.bank_timestamp or timezone.now(),
                payer_name=payer_name or bank_tx.payer_name or '',
                payer_phone=payer_phone,
                transaction_reference=bank_tx.transaction_id,
                notes=f"Auto-created from {bank_tx.gateway.upper()} transaction {bank_tx.transaction_id}",
                is_reconciled=True,  # Bank payments are auto-reconciled
                reconciled_at=timezone.now(),
            )
            
            # Link bank transaction to payment
            bank_tx.payment = payment
            bank_tx.processing_status = 'matched'
            bank_tx.processing_notes = f"Matched to payment {payment.payment_reference}"
            bank_tx.save(update_fields=['payment', 'processing_status', 'processing_notes', 'updated_at'])
            
            logger.info(
                f"Created Payment {payment.payment_reference} for student {student.admission_number} "
                f"from {bank_tx.gateway} transaction {bank_tx.transaction_id}"
            )
            
            return payment
            
        except Exception as e:
            logger.error(f"Failed to create payment from bank transaction: {e}")
            raise PaymentProcessingError(f"Failed to create payment: {str(e)}")
    
    @staticmethod
    def get_payment_by_transaction_reference(reference: str) -> Payment:
        """Get payment by transaction reference."""
        return Payment.objects.filter(
            transaction_reference=reference
        ).first()