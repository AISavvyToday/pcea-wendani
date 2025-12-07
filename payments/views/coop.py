# File: payments/views/coop.py
# ============================================================
# RATIONALE: Handle Co-operative Bank IPN endpoint
# - Receives CBS event notifications
# - Only processes CREDIT events
# - Extracts admission number from narration fields
# - Creates payment if student found, otherwise marks for manual matching
# ============================================================

import logging
from decimal import Decimal
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction as db_transaction

from payments.authentication import CoopBasicAuthentication
from payments.serializers import (
    CoopIPNRequestSerializer,
    CoopIPNResponseSerializer,
)
from payments.services import (
    BankTransactionService,
    ResolutionService,
    PaymentService,
    InvoiceService,
    NotificationService,
)
from payments.exceptions import (
    DuplicateTransactionError,
    InvalidAccountError,
    InvalidEventTypeError,
    PaymentProcessingError,
)

logger = logging.getLogger(__name__)


class CoopIPNView(APIView):
    """
    Co-operative Bank IPN (Instant Payment Notification) Endpoint.
    
    POST /api/payments/coop/ipn/
    
    Receives CBS event notifications and:
    1. Validates account number matches school account
    2. Only processes CREDIT events
    3. Creates BankTransaction record
    4. Extracts admission number from narration
    5. If found: Creates Payment, updates Invoice, sends receipt
    6. If not found: Marks for manual matching
    
    Returns:
    - MessageCode: "200" for success, "4XX" for failure
    - Message: Description of result
    """
    authentication_classes = [CoopBasicAuthentication]
    permission_classes = []
    
    @db_transaction.atomic
    def post(self, request):
        logger.info(f"Coop IPN request from {request.META.get('REMOTE_ADDR')}")
        logger.debug(f"Request data: {request.data}")
        
        # Validate request
        serializer = CoopIPNRequestSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Coop IPN: Invalid request - {serializer.errors}")
            return Response({
                'MessageCode': '400',
                'Message': f"Invalid request: {serializer.errors}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        validated_data = serializer.validated_data
        account_no = validated_data['AcctNo']
        event_type = validated_data['EventType']
        transaction_id = validated_data['TransactionId']
        
        # Step 1: Validate account number
        school_account = settings.SCHOOL_COOP_ACCOUNT_NO
        if school_account and account_no != school_account:
            logger.warning(f"Coop IPN: Account mismatch - received {account_no}, expected {school_account}")
            return Response({
                'MessageCode': '400',
                'Message': 'Invalid account number'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Step 2: Only process CREDIT events
        if event_type.upper() != 'CREDIT':
            logger.info(f"Coop IPN: Ignoring {event_type} event for transaction {transaction_id}")
            return Response({
                'MessageCode': '200',
                'Message': f'{event_type} event acknowledged'
            }, status=status.HTTP_200_OK)
        
        try:
            # Step 3: Create BankTransaction (checks for duplicates)
            bank_tx = BankTransactionService.create_coop_transaction(
                payload=validated_data,
                request_data=request.data
            )
            
            # Step 4: Extract admission number from narration
            admission_number = ResolutionService.extract_admission_from_narration({
                "Narration": validated_data.get("CustMemo", ""),
                "CustMemoLine1": validated_data.get("Narration1", ""),
                "CustMemoLine2": validated_data.get("Narration2", ""),
                "CustMemoLine3": validated_data.get("Narration3", ""),
            })
            
            if not admission_number:
                # No admission number found - mark for manual matching
                BankTransactionService.update_status(
                    bank_tx,
                    'received',
                    'No admission number found in narration - requires manual matching'
                )
                logger.warning(f"Coop IPN: No admission number in narration for {transaction_id}")
                return Response({
                    'MessageCode': '200',
                    'Message': 'Payment received, pending manual matching'
                }, status=status.HTTP_200_OK)
            
            # Step 5: Resolve student
            student = ResolutionService.get_student_by_admission(admission_number)
            
            if not student:
                # Admission number found but student doesn't exist
                BankTransactionService.update_status(
                    bank_tx,
                    'received',
                    f'Student not found for admission number: {admission_number}'
                )
                logger.warning(f"Coop IPN: Student not found for {admission_number}")
                return Response({
                    'MessageCode': '200',
                    'Message': 'Payment received, student not found - pending manual matching'
                }, status=status.HTTP_200_OK)
            
            # Get active invoice for student
            invoice = ResolutionService.get_active_invoice(student)
            
            # Step 6: Create Payment record
            # Extract payer name from narration
            payer_name = ' '.join(filter(None, [
                validated_data.get('CustMemoLine1', ''),
                validated_data.get('CustMemoLine2', ''),
            ]))[:100]
            
            payment = PaymentService.create_payment_from_bank_transaction(
                bank_tx=bank_tx,
                student=student,
                invoice=invoice,
                payer_name=payer_name,
            )
            
            # Step 7: Update Invoice
            if invoice:
                InvoiceService.apply_payment_to_invoice(payment, invoice)
                InvoiceService.allocate_payment_to_items(payment, invoice)
            
            # Step 8: Send receipt notification
            try:
                NotificationService.send_payment_receipt(payment)
            except Exception as e:
                logger.error(f"Failed to send receipt: {e}")
                # Don't fail the transaction for notification errors
            
            logger.info(
                f"Coop IPN success: {transaction_id} -> "
                f"Payment {payment.payment_reference} for {student.admission_number}"
            )
            
            return Response({
                'MessageCode': '200',
                'Message': 'Successfully received data'
            }, status=status.HTTP_200_OK)
            
        except DuplicateTransactionError:
            logger.warning(f"Coop IPN: Duplicate transaction - {transaction_id}")
            return Response({
                'MessageCode': '409',
                'Message': 'Duplicate transaction'
            }, status=status.HTTP_409_CONFLICT)
            
        except PaymentProcessingError as e:
            logger.error(f"Coop IPN: Processing error - {e}")
            return Response({
                'MessageCode': '500',
                'Message': str(e.detail)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.error(f"Coop IPN error: {e}", exc_info=True)
            return Response({
                'MessageCode': '500',
                'Message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)