# File: payments/serializers.py
# ============================================================
# RATIONALE: Request/Response serializers for payment integration
# - Validates incoming payloads from Equity and Co-op
# - Formats responses according to bank specifications
#
# PRODUCTION NOTE (CO-OP):
# The attached Co-op CBS Event Specification uses fields like:
#   Amount, TransactionDate, PaymentRef, Narration, CustMemoLine1/2/3, BookedBalance, ClearedBalance
# Your current implementation/tests use:
#   TxnAmount, TxnDate, MessageReference, CustMemo, Narration1/2/3, Balance, DrCr
#
# This file makes CoopIPNRequestSerializer accept BOTH formats safely by
# normalizing the official CBS keys -> your internal keys before validation.
# ============================================================

from decimal import Decimal
import re
from datetime import date

from rest_framework import serializers
from django.utils.dateparse import parse_date, parse_datetime


# ============================================================
# EQUITY BANK SERIALIZERS
# ============================================================

class EquityValidationRequestSerializer(serializers.Serializer):
    """Validates incoming Equity bill validation requests"""
    billNumber = serializers.CharField(
        max_length=50,
        required=True,
        help_text="Student admission number or invoice number"
    )
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        help_text="Optional amount for validation"
    )


class EquityValidationResponseSerializer(serializers.Serializer):
    """Formats Equity validation response"""
    billNumber = serializers.CharField()
    customerName = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    description = serializers.CharField()
    responseCode = serializers.CharField(default='00')
    responseMessage = serializers.CharField(default='Success')


class EquityNotificationRequestSerializer(serializers.Serializer):
    """Validates incoming Equity payment notification"""
    billNumber = serializers.CharField(
        max_length=50,
        required=True,
        help_text="Student admission number or invoice number"
    )
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=True,
        help_text="Payment amount"
    )
    bankReference = serializers.CharField(
        max_length=100,
        required=True,
        help_text="Unique bank transaction reference"
    )
    transactionDate = serializers.DateTimeField(
        required=True,
        help_text="Transaction date and time"
    )
    customerName = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default=''
    )
    phoneNumber = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        default=''
    )
    paymentChannel = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        default=''
    )


class EquityNotificationResponseSerializer(serializers.Serializer):
    """Formats Equity notification response"""
    responseCode = serializers.CharField()
    responseMessage = serializers.CharField()
    receiptNumber = serializers.CharField(required=False)


# ============================================================
# CO-OP BANK SERIALIZERS
# ============================================================

def _parse_flexible_date(value) -> date:
    """
    Accept common date inputs from Co-op payloads and map to a python date:
    - "YYYY-MM-DD"
    - "YYYY-MM-DD+03:00" / "YYYY-MM-DD-03:00"   (as seen in CBS spec sample)
    - full ISO datetimes (will be converted to date)
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value

    s = str(value).strip()

    # 1) plain date
    d = parse_date(s)
    if d:
        return d

    # 2) handle "YYYY-MM-DD+03:00"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})([+-]\d{2}:\d{2})$", s)
    if m:
        d = parse_date(m.group(1))
        if d:
            return d

    # 3) datetime -> date
    dt = parse_datetime(s)
    if dt:
        return dt.date()

    raise serializers.ValidationError(f"Invalid date format: {value}")


class CoopIPNRequestSerializer(serializers.Serializer):
    """
    Validates incoming Co-op IPN (Instant Payment Notification).

    This serializer accepts BOTH:
      A) Your current/internal format:
         MessageReference, TransactionId, AcctNo, TxnAmount, TxnDate, CustMemo, Narration1/2/3, EventType, ...

      B) The official Co-op CBS Event Spec format:
         AcctNo, Amount, TransactionDate, TransactionId, PaymentRef, Narration, CustMemoLine1/2/3, EventType,
         BookedBalance, ClearedBalance, PostingDate, ValueDate, Currency, ExchangeRate, ...

    We normalize spec keys -> internal keys in to_internal_value() before validation.
    """

    # --- Internal/canonical fields your services expect ---
    MessageReference = serializers.CharField(
        max_length=100,
        required=True,
        help_text="Unique message reference from Co-op (mapped from PaymentRef if provided)"
    )
    TransactionId = serializers.CharField(
        max_length=100,
        required=True,
        help_text="Unique transaction ID"
    )
    AcctNo = serializers.CharField(
        max_length=20,
        required=True,
        help_text="School's Co-op account number"
    )

    TxnAmount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=True,
        help_text="Transaction amount (mapped from Amount if provided)"
    )
    TxnDate = serializers.DateField(
        required=True,
        help_text="Transaction date (mapped from TransactionDate if provided)"
    )

    Currency = serializers.CharField(
        max_length=3,
        required=False,
        default='KES',
        help_text="Currency code"
    )

    # DrCr is not part of the CBS spec sample; make optional for compatibility
    DrCr = serializers.CharField(
        max_length=1,
        required=False,
        allow_blank=True,
        default='',
        help_text="Optional: D=Debit, C=Credit"
    )

    CustMemo = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
        help_text="Customer memo/reference (mapped from Narration if provided)"
    )
    Narration1 = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
        help_text="First narration field (mapped from CustMemoLine1 if provided)"
    )
    Narration2 = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
        help_text="Second narration field (mapped from CustMemoLine2 if provided)"
    )
    Narration3 = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
        help_text="Third narration field (mapped from CustMemoLine3 if provided)"
    )

    EventType = serializers.CharField(
        max_length=20,
        required=True,
        help_text="CREDIT or DEBIT"
    )

    # Your current format has Balance; spec has BookedBalance & ClearedBalance.
    # We'll map ClearedBalance/BookedBalance -> Balance if Balance missing.
    Balance = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Account balance after transaction (mapped from ClearedBalance/BookedBalance if provided)"
    )

    ValueDate = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Value date"
    )
    PostingDate = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Posting date"
    )
    BranchCode = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
        default='',
        help_text="Branch code"
    )

    def to_internal_value(self, data):
        """
        Normalize official CBS spec keys -> internal keys used by services.
        This runs before field validation.
        """
        data = dict(data)

        # Amount -> TxnAmount
        if "TxnAmount" not in data and "Amount" in data:
            data["TxnAmount"] = data.get("Amount")

        # TransactionDate -> TxnDate
        if "TxnDate" not in data and "TransactionDate" in data:
            data["TxnDate"] = data.get("TransactionDate")

        # PaymentRef -> MessageReference (closest internal equivalent)
        if "MessageReference" not in data and "PaymentRef" in data:
            data["MessageReference"] = data.get("PaymentRef")

        # CustMemoLine1/2/3 -> Narration1/2/3
        if "Narration1" not in data and "CustMemoLine1" in data:
            data["Narration1"] = data.get("CustMemoLine1", "")
        if "Narration2" not in data and "CustMemoLine2" in data:
            data["Narration2"] = data.get("CustMemoLine2", "")
        if "Narration3" not in data and "CustMemoLine3" in data:
            data["Narration3"] = data.get("CustMemoLine3", "")

        # Narration -> CustMemo so your ResolutionService sees it as "Narration" input
        if "CustMemo" not in data and "Narration" in data:
            data["CustMemo"] = data.get("Narration", "")

        # ClearedBalance/BookedBalance -> Balance if Balance missing
        if "Balance" not in data:
            if "ClearedBalance" in data:
                data["Balance"] = data.get("ClearedBalance")
            elif "BookedBalance" in data:
                data["Balance"] = data.get("BookedBalance")

        return super().to_internal_value(data)

    # --- Flexible date parsing (spec sample includes YYYY-MM-DD+03:00) ---
    def validate_TxnDate(self, value):
        return _parse_flexible_date(value)

    def validate_PostingDate(self, value):
        return _parse_flexible_date(value) if value is not None else None

    def validate_ValueDate(self, value):
        return _parse_flexible_date(value) if value is not None else None

    # --- Field validators ---
    def validate_DrCr(self, value):
        """Validate DrCr is either D or C (if provided)"""
        if value is None:
            return ''
        value = str(value).strip()
        if value == '':
            return ''
        if value.upper() not in ['D', 'C']:
            raise serializers.ValidationError("DrCr must be 'D' or 'C'")
        return value.upper()

    def validate_EventType(self, value):
        """Validate EventType"""
        valid_types = ['CREDIT', 'DEBIT']
        if value.upper() not in valid_types:
            raise serializers.ValidationError(f"EventType must be one of: {valid_types}")
        return value.upper()


class CoopIPNResponseSerializer(serializers.Serializer):
    """Formats Co-op IPN response"""
    MessageCode = serializers.CharField()
    Message = serializers.CharField()
    TransactionId = serializers.CharField(required=False)


# ============================================================
# INTERNAL SERIALIZERS (for admin/dashboard use)
# ============================================================

class PaymentSummarySerializer(serializers.Serializer):
    """Summary of a payment for internal use"""
    id = serializers.IntegerField()
    receipt_number = serializers.CharField()
    student_name = serializers.CharField()
    admission_number = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_method = serializers.CharField()
    payment_date = serializers.DateField()
    status = serializers.CharField()


class BankTransactionSummarySerializer(serializers.Serializer):
    """Summary of a bank transaction for internal use"""
    id = serializers.IntegerField()
    transaction_reference = serializers.CharField()
    source_bank = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    customer_name = serializers.CharField()
    transaction_date = serializers.DateTimeField()
    is_matched = serializers.BooleanField()
    processing_status = serializers.CharField()
    matching_status = serializers.CharField()