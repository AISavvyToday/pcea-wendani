# File: payments/serializers.py
# ============================================================
# RATIONALE: Request/Response serializers for payment integration
# - Validates incoming payloads from Equity and Co-op
# - Formats responses according to bank specifications
# ============================================================

from rest_framework import serializers
from decimal import Decimal


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

class CoopIPNRequestSerializer(serializers.Serializer):
    """
    Validates incoming Co-op IPN (Instant Payment Notification).
    Field names match Co-op's API specification exactly.
    """
    MessageReference = serializers.CharField(
        max_length=100,
        required=True,
        help_text="Unique message reference from Co-op"
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
        help_text="Transaction amount"
    )
    TxnDate = serializers.DateField(
        required=True,
        help_text="Transaction date"
    )
    Currency = serializers.CharField(
        max_length=3,
        required=False,
        default='KES',
        help_text="Currency code"
    )
    DrCr = serializers.CharField(
        max_length=1,
        required=True,
        help_text="D=Debit, C=Credit"
    )
    CustMemo = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
        help_text="Customer memo/reference"
    )
    Narration1 = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
        help_text="First narration field"
    )
    Narration2 = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
        help_text="Second narration field"
    )
    Narration3 = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default='',
        help_text="Third narration field"
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
        help_text="Account balance after transaction"
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

    def validate_DrCr(self, value):
        """Validate DrCr is either D or C"""
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