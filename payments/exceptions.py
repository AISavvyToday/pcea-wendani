# File: payments/exceptions.py
# ============================================================
# RATIONALE: Define custom exceptions for payment processing
# These provide clear error messages and appropriate HTTP status codes
# for bank API responses
# ============================================================

from rest_framework.exceptions import APIException
from rest_framework import status


class BillNotFoundError(APIException):
    """Raised when the bill/admission number is not found."""
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'Bill number not found'
    default_code = 'bill_not_found'


class StudentNotFoundError(APIException):
    """Raised when student cannot be resolved from bill number."""
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'Student not found'
    default_code = 'student_not_found'


class DuplicateTransactionError(APIException):
    """Raised when a duplicate transaction is detected."""
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Duplicate transaction'
    default_code = 'duplicate_transaction'


class InvalidAccountError(APIException):
    """Raised when the account number doesn't match school account."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Invalid account number'
    default_code = 'invalid_account'


class PaymentProcessingError(APIException):
    """Raised when payment processing fails."""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = 'Payment processing failed'
    default_code = 'processing_error'


class InvalidEventTypeError(APIException):
    """Raised when event type is not CREDIT (for Co-op IPN)."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Only CREDIT events are processed'
    default_code = 'invalid_event_type'


class AuthenticationFailedError(APIException):
    """Raised when API authentication fails."""
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = 'Authentication failed'
    default_code = 'authentication_failed'