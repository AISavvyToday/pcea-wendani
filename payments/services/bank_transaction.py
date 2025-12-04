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
        
        Args:
            payload: Validated request data containing billNumber, amount, bankReference, transactionDate
            request_data: Raw request data for audit
        
        Returns:
            BankTransaction instance
        """
        transaction_id = payload['bankReference']
        
        # Check for duplicate
        if BankTransactionService.check_duplicate('equity', transaction_id):
            existing = BankTransactionService.get_existing_transaction('equity', transaction_id)
            if existing:
                existing.processing_status = 'duplicate'
                existing.save(update_fields=['processing_status', 'updated_at'])
            raise DuplicateTransactionError("Duplicate transaction")
        
        # Parse transaction date
        try:
            # Format: "2025-01-09 12:23:23"
            bank_timestamp = datetime.strptime(
                payload['transactionDate'], 
                '%Y-%m-%d %H:%M:%S'
            )
            bank_timestamp = timezone.make_aware(bank_timestamp)
        except (ValueError, KeyError):
            bank_timestamp = timezone.now()
        
        # Create transaction record
        bank_tx = BankTransaction.objects.create(
            gateway='equity',
            transaction_id=transaction_id,
            transaction_reference=payload.get('billNumber', ''),
            amount=Decimal(payload['amount']),
            currency='KES',
            payer_account='',  # Equity doesn't provide payer account in notification
            payer_name='',  # Will be updated if we can resolve student
            bank_status='SUCCESS',
            bank_status_description='Payment notification received',
            bank_timestamp=bank_timestamp,
            raw_request=request_data,
            raw_response={},
            processing_status='received',
        )
        
        logger.info(f"Created Equity BankTransaction: {bank_tx.transaction_id} - KES {bank_tx.amount}")
        return bank_tx
    
    @staticmethod
    @db_transaction.atomic
    def create_coop_transaction(payload: dict, request_data: dict) -> BankTransaction:
        """
        Create BankTransaction from Co-op Bank IPN payload.
        
        Args:
            payload: Validated request data with all 16 CBS fields
            request_data: Raw request data for audit
        
        Returns:
            BankTransaction instance
        """
        transaction_id = payload['TransactionId']
        
        # Check for duplicate
        if BankTransactionService.check_duplicate('coop', transaction_id):
            existing = BankTransactionService.get_existing_transaction('coop', transaction_id)
            if existing:
                existing.processing_status = 'duplicate'
                existing.save(update_fields=['processing_status', 'updated_at'])
            raise DuplicateTransactionError("Duplicate transaction")
        
        # Parse transaction date
        try:
            # Format: "2023-11-06+03:00"
            date_str = payload.get('TransactionDate', '')
            if date_str:
                # Remove timezone offset for parsing
                date_str = date_str.split('+')[0]
                bank_timestamp = datetime.strptime(date_str, '%Y-%m-%d')
                bank_timestamp = timezone.make_aware(bank_timestamp)
            else:
                bank_timestamp = timezone.now()
        except (ValueError, KeyError):
            bank_timestamp = timezone.now()
        
        # Parse amount (remove commas, handle decimal)
        amount_str = payload.get('Amount', '0').replace(',', '')
        amount = Decimal(amount_str)
        
        # Combine narration fields for reference
        narration_parts = [
            payload.get('Narration', ''),
            payload.get('CustMemoLine1', ''),
            payload.get('CustMemoLine2', ''),
            payload.get('CustMemoLine3', ''),
        ]
        combined_narration = ' | '.join([n for n in narration_parts if n])
        
        # Create transaction record
        bank_tx = BankTransaction.objects.create(
            gateway='coop',
            transaction_id=transaction_id,
            transaction_reference=payload.get('PaymentRef', ''),
            amount=amount,
            currency=payload.get('Currency', 'KES'),
            payer_account='',  # Co-op doesn't provide sender account
            payer_name=combined_narration[:100] if combined_narration else '',
            bank_status=payload.get('EventType', 'CREDIT'),
            bank_status_description=combined_narration,
            bank_timestamp=bank_timestamp,
            raw_request=request_data,
            raw_response={},
            processing_status='received',
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