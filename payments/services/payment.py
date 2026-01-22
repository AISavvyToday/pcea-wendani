"""
File: payments/services/payment.py

Single source of truth for:
- Creating payments from bank callbacks or manual entries
- Linking BankTransaction -> Payment
- Allocating payments oldest-invoice-first via payments.services.invoice.InvoiceService
"""

import logging
from decimal import Decimal
from uuid import uuid4
from core.models import InvoiceStatus
from django.utils import timezone
from django.db import transaction as db_transaction
from django.db import IntegrityError
from django.db.models import Q

from payments.models import Payment, BankTransaction
from students.models import Student
from finance.models import Invoice
from core.models import PaymentMethod, PaymentStatus, PaymentSource
from payments.exceptions import PaymentProcessingError
from payments.services.invoice import InvoiceService
logger = logging.getLogger(__name__)


class PaymentService:
    """Service for creating and managing payment records."""

    GATEWAY_TO_METHOD = {
        "mpesa": PaymentMethod.MOBILE_MONEY,
        "equity": PaymentMethod.BANK_DEPOSIT,
        "coop": PaymentMethod.BANK_DEPOSIT,
    }

    @staticmethod
    def process_completed_payment_against_invoices(payment: Payment):
        """
        Apply any COMPLETED payment:
        1. If student has invoices → allocate to invoices (existing logic)
        2. If student has NO invoices:
           - First reduce outstanding_balance (if any)
           - Any remainder → credit_balance
        """        
        student = payment.student
        
        # Check if student has any active invoices
        has_invoices = student.invoices.filter(is_active=True).exclude(
            status=InvoiceStatus.CANCELLED
        ).exists()
        
        if has_invoices:
            # Student has invoices → use existing invoice allocation logic
            return InvoiceService.apply_payment_to_student_arrears(payment)
        else:
            # Student has NO invoices → handle outstanding_balance directly
            remaining = payment.amount
            
            # First: Reduce outstanding_balance if any exists
            if student.outstanding_balance and student.outstanding_balance > 0:
                amount_to_reduce = min(remaining, student.outstanding_balance)
                student.outstanding_balance -= amount_to_reduce
                remaining -= amount_to_reduce
                
            
            # Second: Any remainder goes to credit_balance
            if remaining > 0:
                student.credit_balance = (student.credit_balance or Decimal("0.00")) + remaining
            
            # Save student
            student.save(update_fields=[
                "outstanding_balance", 
                "balance_bf_original", 
                "credit_balance", 
                "updated_at"
            ])
            
            # Add note to payment
            note = f" | Applied to outstanding balance (no invoices)"
            payment.notes = (payment.notes or "") + note
            payment.save(update_fields=["notes", "updated_at"])
            
            logger.info(
                f"Payment {payment.payment_reference} for student with NO invoices: "
                f"Reduced outstanding_balance by {payment.amount - remaining}, "
                f"Added to credit: {remaining}"
            )
            
            return remaining  # This is the amount added to credit_balance

    @staticmethod
    @db_transaction.atomic
    def create_payment_from_bank_transaction(
        bank_tx: BankTransaction,
        student: Student,
        invoice: Invoice = None,  # kept for compatibility; ignored by allocator
        payer_name: str = "",
        payer_phone: str = "",
        payment_source=None,
        reconciled_by=None,
    ) -> Payment:
        """
        Create a Payment record from a BankTransaction and allocate it oldest-invoice-first.
        """
        try:
            payment_method = PaymentService.GATEWAY_TO_METHOD.get(
                bank_tx.gateway,
                PaymentMethod.BANK_DEPOSIT,
            )
            
            # Map gateway to payment_source if not provided
            if payment_source is None:
                gateway_to_source = {
                    "equity": PaymentSource.EQUITY_BANK,
                    "coop": PaymentSource.COOP_BANK,
                    "mpesa": PaymentSource.MPESA,
                }
                payment_source = gateway_to_source.get(
                    bank_tx.gateway,
                    PaymentSource.MPESA,  # default fallback
                )

            payment = Payment.objects.create(
                student=student,
                invoice=None,  # payment may clear multiple invoices; don't pin to one invoice
                amount=bank_tx.amount,
                payment_method=payment_method,
                payment_source=payment_source,
                status=PaymentStatus.COMPLETED,
                payment_date=bank_tx.bank_timestamp or timezone.now(),
                payer_name=payer_name or bank_tx.payer_name or "",
                payer_phone=(payer_phone or bank_tx.payer_account or ""),
                transaction_reference=bank_tx.transaction_id,
                notes=f"Auto-created from {bank_tx.gateway.upper()} transaction {bank_tx.transaction_id}",
                is_reconciled=True,
                reconciled_by=reconciled_by,
                reconciled_at=timezone.now(),
            )

            bank_tx.payment = payment
            bank_tx.processing_status = "matched"
            bank_tx.processing_notes = f"Matched to payment {payment.payment_reference}"
            bank_tx.save(update_fields=["payment", "processing_status", "processing_notes", "updated_at"])

            PaymentService.process_completed_payment_against_invoices(payment)

            logger.info(
                f"Created Payment {payment.payment_reference} for student {student.admission_number} "
                f"from {bank_tx.gateway} transaction {bank_tx.transaction_id}"
            )
            return payment

        except Exception as e:
            logger.error(f"Failed to create payment from bank transaction: {e}", exc_info=True)
            raise PaymentProcessingError(f"Failed to create payment: {str(e)}")

    @staticmethod
    @db_transaction.atomic
    def create_manual_payment(
        student: Student,
        amount,
        payment_method: str,
        payment_source=None,
        received_by=None,
        payment_date=None,
        payer_name: str = "",
        payer_phone: str = "",
        notes: str = "",
        transaction_reference: str = "",
    ) -> Payment:
        """
        Manual payments follow the SAME allocation rules (oldest invoices first).
        """
        try:
            # Default payment_source if not provided
            if payment_source is None:
                payment_source = PaymentSource.MPESA  # default for manual payments
            
            payment = Payment.objects.create(
                student=student,
                invoice=None,
                amount=amount,
                payment_method=payment_method,
                payment_source=payment_source,
                status=PaymentStatus.COMPLETED,
                payment_date=payment_date or timezone.now(),
                payer_name=payer_name or "",
                payer_phone=payer_phone or "",
                transaction_reference=transaction_reference or "",
                received_by=received_by,
                notes=notes or "Manual payment",
                is_reconciled=True,
                reconciled_by=received_by,
                reconciled_at=timezone.now(),
            )

            PaymentService.process_completed_payment_against_invoices(payment)
            return payment

        except Exception as e:
            logger.error(f"Failed to create manual payment: {e}", exc_info=True)
            raise PaymentProcessingError(f"Failed to create manual payment: {str(e)}")

    @staticmethod
    def get_payment_by_transaction_reference(reference: str) -> Payment:
        return Payment.objects.filter(transaction_reference=reference).first()

    @staticmethod
    def _safe_decimal(value) -> Decimal:
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")

    @staticmethod
    def _extract_transaction_id(transaction_data: dict) -> str:
        """
        Best-effort extraction of a unique bank transaction id.
        Must be non-empty because BankTransaction.transaction_id is unique and required.
        """
        tx_id = (
            transaction_data.get("transaction_id")
            or transaction_data.get("transactionId")
            or transaction_data.get("reference")
            or transaction_data.get("TransID")
            or transaction_data.get("trans_id")
            or transaction_data.get("id")
        )
        tx_id = (str(tx_id).strip() if tx_id is not None else "")
        if not tx_id:
            tx_id = f"GEN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:10]}"
        return tx_id

    @staticmethod
    def _extract_student_reference(transaction_data: dict) -> str:
        """
        Our reference that identifies the student (usually admission number / bill ref).
        Store it in BankTransaction.transaction_reference and use it for matching.
        """
        ref = (
            transaction_data.get("account_reference")
            or transaction_data.get("accountReference")
            or transaction_data.get("BillRefNumber")
            or transaction_data.get("bill_ref")
            or transaction_data.get("transaction_reference")
            or ""
        )
        return str(ref).strip()

    @staticmethod
    @db_transaction.atomic
    def process_bank_callback(transaction_data: dict, gateway: str):
        """
        Creates/updates BankTransaction, matches student by admission number using our reference,
        creates Payment, allocates oldest-first.

        Returns: (payment_or_none, bank_txn)
        """
        tx_id = PaymentService._extract_transaction_id(transaction_data)
        our_ref = PaymentService._extract_student_reference(transaction_data)

        amount = PaymentService._safe_decimal(
            transaction_data.get("amount") or transaction_data.get("TransAmount") or 0
        )

        payer_name = (
            transaction_data.get("sender_name")
            or transaction_data.get("customerName")
            or transaction_data.get("FirstName")
            or transaction_data.get("payer_name")
            or ""
        )
        payer_phone = (
            transaction_data.get("sender_phone")
            or transaction_data.get("phoneNumber")
            or transaction_data.get("MSISDN")
            or transaction_data.get("payer_account")
            or ""
        )

        bank_status = (
            transaction_data.get("bank_status")
            or transaction_data.get("status")
            or transaction_data.get("ResultDesc")
            or "received"
        )
        bank_status_desc = (
            transaction_data.get("bank_status_description")
            or transaction_data.get("message")
            or ""
        )

        # Handle duplicates safely (transaction_id is unique)
        existing = BankTransaction.objects.filter(transaction_id=tx_id).first()
        if existing:
            # If already matched, just return payment
            if existing.payment_id:
                return existing.payment, existing
            existing.processing_status = "duplicate"
            existing.processing_notes = (existing.processing_notes or "") + " | Duplicate callback received"
            existing.save(update_fields=["processing_status", "processing_notes", "updated_at"])
            return None, existing

        try:
            bank_txn = BankTransaction.objects.create(
                gateway=gateway,
                transaction_id=tx_id,
                transaction_reference=our_ref,
                amount=amount,
                currency=str(transaction_data.get("currency") or "KES")[:3],
                payer_account=str(payer_phone or ""),
                payer_name=str(payer_name or ""),
                bank_status=str(bank_status or "")[:50],
                bank_status_description=str(bank_status_desc or ""),
                bank_timestamp=timezone.now(),
                raw_request=transaction_data or {},
                raw_response={},
                processing_status="received",
                processing_notes="",
            )
        except IntegrityError:
            # Rare race: created by another worker
            bank_txn = BankTransaction.objects.get(transaction_id=tx_id)

        # Match student by admission_number using our_ref
        ref = (our_ref or "").strip()
        student = None
        if ref:
            student = Student.objects.filter(
                Q(admission_number__iexact=ref) |
                Q(admission_number__iexact=ref.replace(" ", ""))
            ).first()

        if not student:
            bank_txn.processing_status = "failed"
            bank_txn.processing_notes = (bank_txn.processing_notes or "") + " | No student match for reference"
            bank_txn.save(update_fields=["processing_status", "processing_notes", "updated_at"])
            return None, bank_txn

        # Create payment and allocate oldest-first
        payment = PaymentService.create_payment_from_bank_transaction(
            bank_tx=bank_txn,
            student=student,
            invoice=None,
            payer_name=payer_name,
            payer_phone=payer_phone,
            reconciled_by=None,  # automated callback
        )

        return payment, bank_txn