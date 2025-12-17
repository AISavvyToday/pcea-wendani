# File: payments/serializers.py
# ============================================================
# RATIONALE: Request/Response serializers for payment integration
# - Validates incoming payloads from Equity and Co-op
# - Formats responses according to bank specifications
#
# CO-OP NOTE:
# The Co-op CBS Event Spec uses fields like:
#   Amount, TransactionDate, PaymentRef, Narration, CustMemoLine1/2/3, BookedBalance, ClearedBalance
# Your internal tests/services use:
#   TxnAmount, TxnDate, MessageReference, CustMemo, Narration1/2/3, Balance, DrCr
#
# This serializer supports BOTH formats by mapping spec keys -> internal keys.
# Also includes a FlexibleDateField to accept "YYYY-MM-DD+03:00" values.
# ============================================================

from rest_framework import serializers
from decimal import Decimal  # kept (harmless even if not used directly)
import re
from datetime import date

from django.utils.dateparse import parse_date, parse_datetime


# ============================================================
# HELPERS
# ============================================================

def _parse_flexible_date(value) -> date:
    """
    Accept common date inputs and return a python date:
    - "YYYY-MM-DD"
    - "YYYY-MM-DD+03:00" / "YYYY-MM-DD-03:00"   (as seen in Co-op CBS spec sample)
    - full ISO datetimes (converted to date)
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value

    s = str(value).strip()
    if s == "":
        return None

    # 1) plain date
    d = parse_date(s)
    if d:
        return d

    # 2) "YYYY-MM-DD+03:00"
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


class FlexibleDateField(serializers.Field):
    """
    A date field that accepts:
    - YYYY-MM-DD
    - YYYY-MM-DD+03:00
    - ISO datetime strings
    Returns a python date.
    """

    def to_internal_value(self, data):
        if data is None:
            if getattr(self, "allow_null", False):
                return None
            raise serializers.ValidationError("This field may not be null.")

        parsed = _parse_flexible_date(data)
        if parsed is None:
            # Handles "" (empty string)
            if getattr(self, "allow_null", False):
                return None
            raise serializers.ValidationError("Date has wrong format. Use YYYY-MM-DD.")
        return parsed

    def to_representation(self, value):
        if value is None:
            return None
        if isinstance(value, date):
            return value.isoformat()
        # Fallback
        try:
            return str(value)
        except Exception:
            return None


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
        input_formats=['%Y-%m-%d %H:%M:%S', 'iso-8601'],
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

class CoopIPNRequestSerializer(serializers.Serializer):
    """
    Validates incoming Co-op IPN (Instant Payment Notification).

    Accepts BOTH:
      A) Internal/test format:
         MessageReference, TransactionId, AcctNo, TxnAmount, TxnDate, CustMemo, Narration1/2/3, EventType, ...

      B) Official CBS Event Spec format:
         AcctNo, Amount, TransactionDate, TransactionId, PaymentRef, Narration, CustMemoLine1/2/3, EventType,
         BookedBalance, ClearedBalance, PostingDate, ValueDate, Currency, ExchangeRate, ...
    """

    MessageReference = serializers.CharField(
        max_length=100,
        required=True,
        help_text="Unique message reference (mapped from PaymentRef if provided)"
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

    # IMPORTANT: use FlexibleDateField (not DateField), so "YYYY-MM-DD+03:00" works
    TxnDate = FlexibleDateField(
        required=True,
        help_text="Transaction date (mapped from TransactionDate if provided)"
    )

    Currency = serializers.CharField(
        max_length=3,
        required=False,
        default='KES',
        help_text="Currency code"
    )

    # Optional (CBS spec sample relies on EventType instead)
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

    Balance = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Account balance (mapped from ClearedBalance/BookedBalance if provided)"
    )

    ValueDate = FlexibleDateField(
        required=False,
        allow_null=True,
        help_text="Value date"
    )
    PostingDate = FlexibleDateField(
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
        Normalize official CBS spec keys -> internal keys used by your services.
        Runs BEFORE validation.
        """
        data = dict(data)

        # Amount -> TxnAmount
        if "TxnAmount" not in data and "Amount" in data:
            data["TxnAmount"] = data.get("Amount")

        # TransactionDate -> TxnDate
        if "TxnDate" not in data and "TransactionDate" in data:
            data["TxnDate"] = data.get("TransactionDate")

        # PaymentRef -> MessageReference
        if "MessageReference" not in data and "PaymentRef" in data:
            data["MessageReference"] = data.get("PaymentRef")

        # CustMemoLine1/2/3 -> Narration1/2/3
        if "Narration1" not in data and "CustMemoLine1" in data:
            data["Narration1"] = data.get("CustMemoLine1", "")
        if "Narration2" not in data and "CustMemoLine2" in data:
            data["Narration2"] = data.get("CustMemoLine2", "")
        if "Narration3" not in data and "CustMemoLine3" in data:
            data["Narration3"] = data.get("CustMemoLine3", "")

        # Narration -> CustMemo
        if "CustMemo" not in data and "Narration" in data:
            data["CustMemo"] = data.get("Narration", "")

        # ClearedBalance/BookedBalance -> Balance if Balance missing
        if "Balance" not in data:
            if "ClearedBalance" in data:
                data["Balance"] = data.get("ClearedBalance")
            elif "BookedBalance" in data:
                data["Balance"] = data.get("BookedBalance")

        return super().to_internal_value(data)

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