# File: payments/services/bank_transaction.py
# ============================================================
# RATIONALE: Handle creation and management of BankTransaction records
# - Creates records from Equity and Co-op payloads
# - Checks for duplicate transactions (idempotency)
# - Stores raw request data for audit purposes
# ============================================================

import logging
from decimal import Decimal
from django.utils import timezone
from django.db import transaction as db_transaction
from datetime import datetime

from payments.models import BankTransaction
from payments.exceptions import DuplicateTransactionError
from datetime import datetime, date
logger = logging.getLogger(__name__)


class BankTransactionService:
    """Service for managing bank transaction records."""
    
    @staticmethod
    def check_duplicate(gateway: str, transaction_id: str) -> bool:
        """
        Check if a transaction already exists.
        Returns True if duplicate exists.
        """
        exists = BankTransaction.objects.filter(
            gateway=gateway,
            transaction_id=transaction_id
        ).exists()
        
        if exists:
            logger.warning(f"Duplicate transaction detected: {gateway} - {transaction_id}")
        
        return exists
    
    @staticmethod
    def get_existing_transaction(gateway: str, transaction_id: str):
        """Get existing transaction if it exists."""
        return BankTransaction.objects.filter(
            gateway=gateway,
            transaction_id=transaction_id
        ).first()

    @staticmethod
    @db_transaction.atomic
    def create_equity_transaction(payload: dict, request_data: dict) -> BankTransaction:
        """
        Create BankTransaction from Equity Bank notification payload.

        payload comes from EquityNotificationRequestSerializer.validated_data:
        - billNumber: str
        - amount: Decimal
        - bankReference: str
        - transactionDate: datetime
        """
        transaction_id = payload["bankReference"]

        # Check for duplicate
        if BankTransactionService.check_duplicate("equity", transaction_id):
            existing = BankTransactionService.get_existing_transaction("equity", transaction_id)
            if existing:
                existing.processing_status = "duplicate"
                existing.save(update_fields=["processing_status", "updated_at"])
            raise DuplicateTransactionError("Duplicate transaction")

        # Use the datetime object we already have
        tx_dt = payload.get("transactionDate")
        if isinstance(tx_dt, datetime):
            bank_timestamp = timezone.make_aware(tx_dt) if timezone.is_naive(tx_dt) else tx_dt
        else:
            # Fallback if for some reason it’s not a datetime
            try:
                bank_timestamp = datetime.strptime(str(tx_dt), "%Y-%m-%d %H:%M:%S")
                bank_timestamp = timezone.make_aware(bank_timestamp)
            except Exception:
                bank_timestamp = timezone.now()

        # amount is already a Decimal from the serializer
        amount = payload["amount"]
        
        # Extract payer info from validated payload
        # The serializer normalizes: debitcustname -> customerName, debitaccount -> debitAccount
        payer_name = payload.get("customerName", "") or ""
        payer_account = payload.get("debitAccount", "") or ""
        payment_channel = payload.get("paymentChannel", "") or ""
        
        # Build a description from available info
        description_parts = []
        if payment_channel:
            description_parts.append(f"Channel: {payment_channel}")
        if payload.get("tranParticular"):
            description_parts.append(payload.get("tranParticular"))
        bank_description = " | ".join(description_parts) if description_parts else "Payment notification received"

        bank_tx = BankTransaction.objects.create(
            gateway="equity",
            transaction_id=transaction_id,
            transaction_reference=payload.get("billNumber", ""),
            amount=amount,
            currency="KES",
            payer_account=payer_account[:50] if payer_account else "",
            payer_name=payer_name[:100] if payer_name else "",
            bank_status="SUCCESS",
            bank_status_description=bank_description,
            bank_timestamp=bank_timestamp,
            raw_request=request_data,
            raw_response={},
            processing_status="received",
        )

        logger.info(f"Created Equity BankTransaction: {bank_tx.transaction_id} - KES {bank_tx.amount}")
        return bank_tx

    @staticmethod
    @db_transaction.atomic
    def create_coop_transaction(payload: dict, request_data: dict) -> BankTransaction:
        """
        Create BankTransaction from Co-op Bank IPN payload.

        payload comes from CoopIPNRequestSerializer.validated_data:
        - MessageReference, TransactionId, AcctNo, TxnAmount, TxnDate, Currency,
          DrCr, CustMemo, Narration1-3, EventType, Balance, ValueDate, PostingDate, BranchCode
        """
        transaction_id = payload["TransactionId"]

        # Check for duplicate
        if BankTransactionService.check_duplicate("coop", transaction_id):
            existing = BankTransactionService.get_existing_transaction("coop", transaction_id)
            if existing:
                existing.processing_status = "duplicate"
                existing.save(update_fields=["processing_status", "updated_at"])
            raise DuplicateTransactionError("Duplicate transaction")

        # TxnDate is a date object from serializer (or None)
        txn_date = payload.get("TxnDate")
        if isinstance(txn_date, date):
            bank_timestamp = timezone.make_aware(
                datetime.combine(txn_date, datetime.min.time())
            )
        else:
            bank_timestamp = timezone.now()

        # TxnAmount is already a Decimal
        amount = payload["TxnAmount"]

        # Combine narration fields
        narration_parts = [
            payload.get("CustMemo", ""),
            payload.get("Narration1", ""),
            payload.get("Narration2", ""),
            payload.get("Narration3", ""),
        ]
        combined_narration = " | ".join([n for n in narration_parts if n])

        bank_tx = BankTransaction.objects.create(
            gateway="coop",
            transaction_id=transaction_id,
            transaction_reference=payload.get("MessageReference", ""),
            amount=amount,
            currency=payload.get("Currency", "KES"),
            payer_account="",
            payer_name=combined_narration[:100] if combined_narration else "",
            bank_status=payload.get("EventType", "CREDIT"),
            bank_status_description=combined_narration,
            bank_timestamp=bank_timestamp,
            raw_request=request_data,
            raw_response={},
            processing_status="received",
        )

        logger.info(f"Created Coop BankTransaction: {bank_tx.transaction_id} - KES {bank_tx.amount}")
        return bank_tx
    
    @staticmethod
    def update_status(bank_tx: BankTransaction, status: str, notes: str = ''):
        """Update processing status of a bank transaction."""
        bank_tx.processing_status = status
        if notes:
            bank_tx.processing_notes = notes
        bank_tx.save(update_fields=['processing_status', 'processing_notes', 'updated_at'])
        logger.info(f"Updated BankTransaction {bank_tx.transaction_id} status to: {status}")