# File: payments/views/equity.py
# ============================================================
# RATIONALE: Handle Equity Bank API endpoints
# - Validation: Validates bill number and returns student info + amount
# - Notification: Receives payment notification and creates payment record
# Both endpoints use API Key authentication per Equity spec
#
# IMPORTANT (Equity spec alignment):
# - Equity notification expects HTTP 200 responses (even on failure),
#   with business outcome communicated via responseCode/responseMessage.
# - Same approach is applied to validation for safer bank integration.
# ============================================================

import logging
from decimal import Decimal  # kept (may be used elsewhere / future)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction as db_transaction

from payments.authentication import EquityAPIKeyAuthentication
from payments.serializers import (
    EquityValidationRequestSerializer,
    EquityValidationResponseSerializer,  # imported for completeness
    EquityNotificationRequestSerializer,
    EquityNotificationResponseSerializer,  # imported for completeness
)
from payments.services import (
    BankTransactionService,
    ResolutionService,
    PaymentService,
    InvoiceService,
    NotificationService,
)
from payments.exceptions import (
    BillNotFoundError,
    StudentNotFoundError,
    DuplicateTransactionError,
    PaymentProcessingError,
)

logger = logging.getLogger(__name__)


class EquityValidationView(APIView):
    """
    Equity Bank Biller Validation Endpoint.

    POST /api/payments/equity/validation/

    Validates a bill number (student admission number) and returns:
    - billNumber: The validated bill number
    - customerName: Student's full name
    - amount: Outstanding balance
    - description: Validation result description
    """
    authentication_classes = [EquityAPIKeyAuthentication]
    permission_classes = []  # No additional permissions needed after auth

    def post(self, request):
        logger.info(f"Equity Validation request from {request.META.get('REMOTE_ADDR')}")
        logger.debug(f"Request data: {request.data}")

        serializer = EquityValidationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Equity Validation: Invalid request - {serializer.errors}")

            # Equity-friendly: return HTTP 200 with description indicating failure
            return Response(
                {
                    "billNumber": request.data.get("billNumber", ""),
                    "customerName": "",
                    "amount": "0",
                    "description": f"Validation failed: {serializer.errors}",
                },
                status=status.HTTP_200_OK,
            )

        bill_number = serializer.validated_data["billNumber"]

        try:
            # Resolve bill number to student
            student, invoice = ResolutionService.resolve_bill_number(bill_number)

            customer_name = f"{student.first_name} {student.last_name}"

            # Calculate outstanding amount
            outstanding_amount, description = ResolutionService.calculate_outstanding_amount(student)

            # Build response per Equity spec
            response_data = {
                "billNumber": student.admission_number,
                "customerName": customer_name,
                "amount": str(int(outstanding_amount)),  # Equity expects string (integer-like)
                "description": "Success",
            }

            logger.info(
                f"Equity Validation success: {bill_number} -> {customer_name}, "
                f"Amount: {outstanding_amount}"
            )

            return Response(response_data, status=status.HTTP_200_OK)

        except (BillNotFoundError, StudentNotFoundError) as e:
            logger.warning(f"Equity Validation: Bill not found - {bill_number}")

            # Equity-friendly: return HTTP 200 with amount 0 and description
            return Response(
                {
                    "billNumber": bill_number,
                    "customerName": "",
                    "amount": "0",
                    "description": str(e.detail),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Equity Validation error: {e}", exc_info=True)

            # Equity-friendly: return HTTP 200 with generic error description
            return Response(
                {
                    "billNumber": bill_number,
                    "customerName": "",
                    "amount": "0",
                    "description": "Internal server error",
                },
                status=status.HTTP_200_OK,
            )


class EquityNotificationView(APIView):
    """
    Equity Bank Biller Notification Endpoint.

    POST /api/payments/equity/notification/

    Receives payment notification from Equity Bank and:
    1. Creates BankTransaction record
    2. Resolves student from bill number
    3. Creates Payment record
    4. Updates Invoice
    5. Sends receipt notification

    Returns:
    - responseCode: "200" for success, "400"/"500" for failure
    - responseMessage: Description of result

    IMPORTANT:
    - Always respond with HTTP 200 to avoid bank retries / integration failures.
    - Use responseCode in JSON to signal business outcome.
    """
    authentication_classes = [EquityAPIKeyAuthentication]
    permission_classes = []

    @db_transaction.atomic
    def post(self, request):
        logger.info(f"Equity Notification request from {request.META.get('REMOTE_ADDR')}")
        logger.debug(f"Request data: {request.data}")

        serializer = EquityNotificationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Equity Notification: Invalid request - {serializer.errors}")
            return Response(
                {
                    "responseCode": "400",
                    "responseMessage": f"Invalid request: {serializer.errors}",
                },
                status=status.HTTP_200_OK,
            )

        validated_data = serializer.validated_data
        bill_number = validated_data["billNumber"]
        bank_reference = validated_data["bankReference"]

        try:
            # Step 1: Create BankTransaction (checks for duplicates)
            bank_tx = BankTransactionService.create_equity_transaction(
                payload=validated_data,
                request_data=request.data,
            )

            # Step 2: Resolve student from bill number
            try:
                student, invoice = ResolutionService.resolve_bill_number(bill_number)
            except (BillNotFoundError, StudentNotFoundError) as e:
                # Payment received but student not found - mark for manual matching
                BankTransactionService.update_status(
                    bank_tx,
                    "received",
                    f"Student not found for bill number: {bill_number}",
                )
                logger.warning(f"Equity Notification: Student not found for {bill_number}")

                # Still return success to bank - we received the payment payload
                return Response(
                    {
                        "responseCode": "200",
                        "responseMessage": "Payment received, pending manual matching",
                    },
                    status=status.HTTP_200_OK,
                )

            # Step 3: Create Payment record (store payer details)
            payment = PaymentService.create_payment_from_bank_transaction(
                bank_tx=bank_tx,
                student=student,
                invoice=invoice,
                payer_name=validated_data.get("customerName", ""),
                payer_phone=validated_data.get("phoneNumber", ""),
            )

            # Step 4: Update Invoice
            if invoice:
                InvoiceService.apply_payment_to_invoice(payment, invoice)
                InvoiceService.allocate_payment_to_items(payment, invoice)

            # Step 5: Send receipt notification (async in production)
            try:
                NotificationService.send_payment_receipt(payment)
            except Exception as e:
                logger.error(f"Failed to send receipt: {e}", exc_info=True)
                # Do not fail the transaction for notification errors

            logger.info(
                f"Equity Notification success: {bank_reference} -> "
                f"Payment {payment.payment_reference} for {student.admission_number}"
            )

            return Response(
                {
                    "responseCode": "200",
                    "responseMessage": "Success",
                },
                status=status.HTTP_200_OK,
            )

        except DuplicateTransactionError:
            logger.warning(f"Equity Notification: Duplicate transaction - {bank_reference}")

            # Equity-friendly: HTTP 200, indicate duplicate in body
            return Response(
                {
                    "responseCode": "400",
                    "responseMessage": "Duplicate transaction",
                },
                status=status.HTTP_200_OK,
            )

        except PaymentProcessingError as e:
            logger.error(f"Equity Notification: Processing error - {e}", exc_info=True)

            # Equity-friendly: HTTP 200, indicate server-side processing issue
            return Response(
                {
                    "responseCode": "500",
                    "responseMessage": str(e.detail),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Equity Notification error: {e}", exc_info=True)

            # Equity-friendly: HTTP 200, generic internal error
            return Response(
                {
                    "responseCode": "500",
                    "responseMessage": "Internal server error",
                },
                status=status.HTTP_200_OK,
            )