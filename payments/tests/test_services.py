# File: payments/tests/test_services.py

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from academics.models import AcademicYear, Class, Term
from core.models import (
    GradeLevel,
    Organization,
    PaymentMethod,
    PaymentSource,
    PaymentStatus,
    StreamChoices,
    TermChoices,
    UserRole,
)
from finance.models import Invoice, InvoiceItem
from payments.exceptions import BillNotFoundError, DuplicateTransactionError
from payments.models import BankTransaction, Payment
from payments.services.bank_transaction import BankTransactionService
from payments.services.notifications import NotificationService
from payments.services.payment import PaymentService
from payments.services.resolution import ResolutionService
from students.models import Student


class PaymentServiceFixtureMixin:
    def setUp_school(self, admission_number="PWA1001", first_name="Jane", last_name="Doe"):
        self.organization = Organization.objects.create(name="Fixture School", code=f"fixture-{admission_number.lower()}")
        self.user = User.objects.create_user(
            email=f"{admission_number.lower()}@example.com",
            password="pass123",
            first_name="Admin",
            last_name="User",
            role=UserRole.SCHOOL_ADMIN,
            is_staff=True,
            organization=self.organization,
        )
        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2025,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term=TermChoices.TERM_1,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 4, 30),
            is_current=True,
            fee_deadline=date(2025, 1, 31),
        )
        self.classroom = Class.objects.create(
            organization=self.organization,
            name="Grade 5 East",
            grade_level=GradeLevel.GRADE_5,
            stream=StreamChoices.EAST,
            academic_year=self.academic_year,
        )
        self.student = Student.objects.create(
            organization=self.organization,
            admission_number=admission_number,
            admission_date=date(2025, 1, 5),
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date(2015, 5, 10),
            gender="F",
            current_class=self.classroom,
            status="active",
        )
        self.invoice = Invoice.objects.create(
            organization=self.organization,
            student=self.student,
            term=self.term,
            invoice_number=f"INV-{admission_number}",
            total_amount=Decimal("50000.00"),
            amount_paid=Decimal("0.00"),
            balance=Decimal("50000.00"),
            status="overdue",
            issue_date=date(2025, 1, 10),
            due_date=date(2025, 2, 15),
        )
        self.invoice_item = InvoiceItem.objects.create(
            invoice=self.invoice,
            description="Tuition",
            category="tuition",
            amount=Decimal("50000.00"),
            net_amount=Decimal("50000.00"),
        )


class BankTransactionServiceTests(PaymentServiceFixtureMixin, TestCase):
    def setUp(self):
        self.setUp_school()
        self.equity_payload = {
            "billNumber": self.student.admission_number,
            "amount": Decimal("15000.00"),
            "bankReference": "EQ123456789",
            "transactionDate": timezone.make_aware(datetime(2025, 1, 15, 10, 30)),
            "phoneNumber": "254712345678",
            "paymentChannel": "MOBILE",
        }
        self.coop_payload = {
            "MessageReference": "COOP-REF-001",
            "TransactionId": "TXN123456",
            "AcctNo": "01234567890100",
            "TxnAmount": Decimal("25000.00"),
            "TxnDate": date(2025, 1, 15),
            "Currency": "KES",
            "DrCr": "C",
            "CustMemo": "School fees",
            "Narration1": "FT from John Doe",
            "Narration2": "PWA1001 Term 1 fees",
            "Narration3": "",
            "EventType": "CREDIT",
            "Balance": "500000.00",
            "ValueDate": date(2025, 1, 15),
            "PostingDate": date(2025, 1, 15),
            "BranchCode": "001",
        }

    def test_create_equity_transaction_success(self):
        request_data = {
            "billNumber": self.student.admission_number,
            "amount": "15000.00",
            "bankReference": "EQ123456789",
            "transactionDate": "2025-01-15T10:30:00",
            "phoneNumber": "254712345678",
            "paymentChannel": "MOBILE",
        }
        txn = BankTransactionService.create_equity_transaction(self.equity_payload, request_data)
        self.assertEqual(txn.gateway, "equity")
        self.assertEqual(txn.transaction_id, "EQ123456789")
        self.assertEqual(txn.amount, Decimal("15000.00"))
        self.assertEqual(txn.processing_status, "received")

    def test_create_coop_transaction_success(self):
        request_data = {
            "MessageReference": "COOP-REF-001",
            "TransactionId": "TXN123456",
            "AcctNo": "01234567890100",
            "TxnAmount": "25000.00",
            "TxnDate": "2025-01-15",
            "Currency": "KES",
            "DrCr": "C",
            "CustMemo": "School fees",
            "Narration1": "FT from John Doe",
            "Narration2": "PWA1001 Term 1 fees",
            "Narration3": "",
            "EventType": "CREDIT",
            "Balance": "500000.00",
            "ValueDate": "2025-01-15",
            "PostingDate": "2025-01-15",
            "BranchCode": "001",
        }
        txn = BankTransactionService.create_coop_transaction(self.coop_payload, request_data)
        self.assertEqual(txn.gateway, "coop")
        self.assertEqual(txn.transaction_id, "TXN123456")
        self.assertEqual(txn.amount, Decimal("25000.00"))
        self.assertIn("PWA1001", txn.bank_status_description)

    def test_duplicate_detection_raises(self):
        request_data = {
            "billNumber": self.student.admission_number,
            "amount": "15000.00",
            "bankReference": "EQ123456789",
            "transactionDate": "2025-01-15T10:30:00",
            "phoneNumber": "254712345678",
            "paymentChannel": "MOBILE",
        }
        BankTransactionService.create_equity_transaction(self.equity_payload, request_data)
        with self.assertRaises(DuplicateTransactionError):
            BankTransactionService.create_equity_transaction(self.equity_payload, request_data)


class ResolutionServiceTests(PaymentServiceFixtureMixin, TestCase):
    def setUp(self):
        self.setUp_school()

    def test_resolve_bill_number_by_admission(self):
        student, invoice = ResolutionService.resolve_bill_number(self.student.admission_number)
        self.assertEqual(student, self.student)
        self.assertEqual(invoice, self.invoice)

    def test_resolve_bill_number_by_invoice_number(self):
        student, invoice = ResolutionService.resolve_bill_number(self.invoice.invoice_number)
        self.assertEqual(student, self.student)
        self.assertEqual(invoice, self.invoice)

    def test_resolve_bill_number_not_found(self):
        with self.assertRaises(BillNotFoundError):
            ResolutionService.resolve_bill_number("INVALID123")

    def test_extract_admission_from_narration(self):
        admission = ResolutionService.extract_admission_from_narration(
            {
                "Narration": "School fees",
                "CustMemoLine1": "Parent transfer",
                "CustMemoLine2": "PWA1001 Term 1 fees",
                "CustMemoLine3": "",
            }
        )
        self.assertEqual(admission, "1001")

    def test_calculate_outstanding_amount(self):
        amount, description = ResolutionService.calculate_outstanding_amount(self.student)
        self.assertEqual(amount, 50000.0)
        self.assertIn("current term", description.lower())


class PaymentCreationServiceTests(PaymentServiceFixtureMixin, TestCase):
    def setUp(self):
        self.setUp_school(admission_number="PWA2001")
        self.bank_tx = BankTransaction.objects.create(
            gateway="equity",
            transaction_id="EQ-REF-001",
            transaction_reference=self.student.admission_number,
            amount=Decimal("20000.00"),
            currency="KES",
            payer_account="254700000000",
            payer_name="",
            bank_status="SUCCESS",
            bank_status_description="Payment received",
            bank_timestamp=timezone.now(),
            raw_request={},
            raw_response={},
            processing_status="received",
        )

    def test_create_payment_from_bank_transaction_updates_invoice(self):
        payment = PaymentService.create_payment_from_bank_transaction(
            bank_tx=self.bank_tx,
            student=self.student,
            payment_source=PaymentSource.EQUITY_BANK,
        )
        self.assertEqual(payment.status, PaymentStatus.COMPLETED)
        self.assertEqual(payment.payment_method, PaymentMethod.BANK_DEPOSIT)
        self.assertEqual(payment.transaction_reference, "EQ-REF-001")

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("20000.00"))
        self.assertEqual(self.invoice.balance, Decimal("30000.00"))

        self.bank_tx.refresh_from_db()
        self.assertEqual(self.bank_tx.processing_status, "matched")
        self.assertEqual(self.bank_tx.payment, payment)

    def test_create_payment_full_amount_marks_invoice_paid(self):
        self.bank_tx.amount = Decimal("50000.00")
        self.bank_tx.save(update_fields=["amount"])
        PaymentService.create_payment_from_bank_transaction(
            bank_tx=self.bank_tx,
            student=self.student,
            payment_source=PaymentSource.EQUITY_BANK,
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance, Decimal("0.00"))
        self.assertEqual(self.invoice.status, "paid")

    def test_reconcile_bank_transaction_uses_bank_transaction_matched_at_as_canonical_timestamp(self):
        payments = PaymentService.reconcile_bank_transaction(
            bank_tx=self.bank_tx,
            allocations=[
                {
                    "student": self.student,
                    "invoice": self.invoice,
                    "amount": Decimal("20000.00"),
                }
            ],
            matched_by=self.user,
            notes="Operator reconciliation",
        )

        self.assertEqual(len(payments), 1)
        payment = payments[0]
        self.bank_tx.refresh_from_db()
        reconciliation = self.bank_tx.reconciliations.get()

        self.assertIsNotNone(self.bank_tx.matched_at)
        self.assertEqual(payment.reconciled_at, self.bank_tx.matched_at)
        self.assertEqual(reconciliation.matched_at, self.bank_tx.matched_at)


class NotificationServiceTests(PaymentServiceFixtureMixin, TestCase):
    def setUp(self):
        self.setUp_school(admission_number="PWA3001")
        self.payment = Payment.objects.create(
            organization=self.organization,
            student=self.student,
            invoice=self.invoice,
            amount=Decimal("10000.00"),
            payment_method=PaymentMethod.BANK_DEPOSIT,
            payment_source=PaymentSource.EQUITY_BANK,
            status=PaymentStatus.COMPLETED,
            payment_date=timezone.now(),
            payer_name="Parent",
            payer_phone="254700000000",
            transaction_reference="EQ-NOTIFY-001",
        )

    def test_format_sms_receipt(self):
        message = NotificationService.format_sms_receipt(self.payment)
        self.assertIn(self.payment.receipt_number, message)
        self.assertIn(self.student.admission_number, message)
        self.assertIn("PCEA Wendani Academy", message)

    @patch("payments.services.notifications.NotificationService.send_sms", return_value=True)
    @patch("payments.services.notifications.NotificationService.send_email_receipt", return_value=False)
    def test_send_payment_receipt_updates_flags(self, _mock_email, _mock_sms):
        sent = NotificationService.send_payment_receipt(self.payment)
        self.assertTrue(sent)
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.receipt_sent)
        self.assertIsNotNone(self.payment.receipt_sent_at)
