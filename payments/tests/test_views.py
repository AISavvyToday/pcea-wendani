# File: payments/tests/test_views.py

import base64
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import AcademicYear, Class, Term
from core.models import GradeLevel, Organization, StreamChoices, TermChoices, UserRole
from finance.models import Invoice, InvoiceItem
from payments.models import BankTransaction, Payment
from students.models import Student


class PaymentTestDataMixin:
    def create_common_school_data(self, admission_number="PWA1001", first_name="Test", last_name="Student"):
        self.organization = Organization.objects.create(name="Test School", code=f"org-{admission_number.lower()}")
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
            name="Grade 3 East",
            grade_level=GradeLevel.GRADE_3,
            stream=StreamChoices.EAST,
            academic_year=self.academic_year,
        )
        self.student = Student.objects.create(
            organization=self.organization,
            admission_number=admission_number,
            admission_date=date(2025, 1, 10),
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date(2017, 5, 15),
            gender="M",
            current_class=self.classroom,
            status="active",
        )
        self.invoice = Invoice.objects.create(
            organization=self.organization,
            student=self.student,
            term=self.term,
            invoice_number=f"INV-{admission_number}",
            total_amount=Decimal("50000.00"),
            amount_paid=Decimal("10000.00"),
            balance=Decimal("40000.00"),
            status="partially_paid",
            issue_date=date(2025, 1, 10),
            due_date=date(2025, 2, 15),
        )
        self.invoice_item = InvoiceItem.objects.create(
            invoice=self.invoice,
            description="Tuition",
            category="tuition",
            amount=self.invoice.total_amount,
            net_amount=self.invoice.total_amount,
        )

    @staticmethod
    def basic_auth(username, password):
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
        return {"HTTP_AUTHORIZATION": f"Basic {token}"}


@override_settings(
    EQUITY_IPN_USERNAME="testuser",
    EQUITY_IPN_PASSWORD="testpass",
    COOP_IPN_USERNAME="testuser",
    COOP_IPN_PASSWORD="testpass",
    SCHOOL_COOP_ACCOUNT_NO="01234567890100",
)
class EquityValidationViewTests(PaymentTestDataMixin, TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("payments:equity-validation")
        self.create_common_school_data()

    def auth_headers(self):
        return self.basic_auth("testuser", "testpass")

    def test_validation_success(self):
        response = self.client.post(self.url, data={"billNumber": self.student.admission_number}, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["billNumber"], self.student.admission_number)
        self.assertEqual(data["customerName"], self.student.full_name)
        self.assertEqual(data["amount"], "40000")
        self.assertEqual(data["description"], "Success")

    def test_validation_invalid_bill_number_returns_equity_friendly_200(self):
        response = self.client.post(self.url, data={"billNumber": "INVALID999"}, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["billNumber"], "INVALID999")
        self.assertEqual(data["amount"], "0")
        self.assertIn("not found", data["description"].lower())

    def test_validation_by_invoice_number(self):
        response = self.client.post(self.url, data={"billNumber": self.invoice.invoice_number}, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["customerName"], self.student.full_name)

    def test_validation_missing_bill_number_returns_200_with_failure_description(self):
        response = self.client.post(self.url, data={}, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("validation failed", response.json()["description"].lower())

    def test_validation_no_auth(self):
        response = self.client.post(self.url, data={"billNumber": self.student.admission_number}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_validation_wrong_credentials(self):
        response = self.client.post(
            self.url,
            data={"billNumber": self.student.admission_number},
            format="json",
            **self.basic_auth("wronguser", "wrongpass"),
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(
    EQUITY_IPN_USERNAME="testuser",
    EQUITY_IPN_PASSWORD="testpass",
    COOP_IPN_USERNAME="testuser",
    COOP_IPN_PASSWORD="testpass",
    SCHOOL_COOP_ACCOUNT_NO="01234567890100",
)
class EquityNotificationViewTests(PaymentTestDataMixin, TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("payments:equity-notification")
        self.create_common_school_data(admission_number="PWA2001", first_name="Jane", last_name="Doe")
        self.invoice.amount_paid = Decimal("0.00")
        self.invoice.balance = Decimal("45000.00")
        self.invoice.total_amount = Decimal("45000.00")
        self.invoice.save(update_fields=["amount_paid", "balance", "total_amount", "updated_at"])
        self.invoice_item.amount = Decimal("45000.00")
        self.invoice_item.net_amount = Decimal("45000.00")
        self.invoice_item.save(update_fields=["amount", "net_amount", "updated_at"])

    def auth_headers(self):
        return self.basic_auth("testuser", "testpass")

    def payload(self):
        return {
            "billNumber": self.student.admission_number,
            "amount": "20000.00",
            "bankReference": "EQ-REF-123456",
            "transactionDate": "2025-01-15T14:30:00",
            "customerName": "Jane Doe Parent",
            "phoneNumber": "254712345678",
            "paymentChannel": "MOBILE",
        }

    @patch("payments.views.equity.NotificationService.send_payment_receipt", return_value=True)
    def test_notification_success(self, _mock_receipt):
        response = self.client.post(self.url, data=self.payload(), format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["responseCode"], "200")
        self.assertIn("successfully received", data["responseMessage"].lower())

        payment = Payment.objects.get(transaction_reference="EQ-REF-123456")
        self.assertEqual(payment.amount, Decimal("20000.00"))
        self.assertEqual(payment.student, self.student)

        bank_txn = BankTransaction.objects.get(transaction_id="EQ-REF-123456")
        self.assertEqual(bank_txn.processing_status, "matched")
        self.assertEqual(bank_txn.payment, payment)
        self.assertIsNotNone(bank_txn.matched_at)
        self.assertEqual(bank_txn.matched_at, payment.reconciled_at)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("20000.00"))
        self.assertEqual(self.invoice.balance, Decimal("25000.00"))
        self.assertEqual(self.invoice.status, "partially_paid")

    @patch("payments.views.equity.NotificationService.send_payment_receipt", return_value=True)
    def test_notification_idempotency(self, _mock_receipt):
        response1 = self.client.post(self.url, data=self.payload(), format="json", **self.auth_headers())
        response2 = self.client.post(self.url, data=self.payload(), format="json", **self.auth_headers())
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.json()["responseCode"], "400")
        self.assertEqual(Payment.objects.filter(transaction_reference="EQ-REF-123456").count(), 1)

    def test_notification_invalid_bill_returns_ack_without_payment(self):
        payload = self.payload()
        payload["billNumber"] = "INVALID999"
        response = self.client.post(self.url, data=payload, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["responseCode"], "200")
        self.assertFalse(Payment.objects.filter(transaction_reference="EQ-REF-123456").exists())

    def test_notification_missing_fields(self):
        response = self.client.post(self.url, data={"billNumber": self.student.admission_number}, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["responseCode"], "400")

    def test_notification_no_auth(self):
        response = self.client.post(self.url, data=self.payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("payments.views.equity.NotificationService.send_payment_receipt", return_value=True)
    def test_notification_full_payment(self, _mock_receipt):
        payload = self.payload()
        payload["amount"] = "45000.00"
        response = self.client.post(self.url, data=payload, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")
        self.assertEqual(self.invoice.balance, Decimal("0.00"))


@override_settings(
    COOP_IPN_USERNAME="testuser",
    COOP_IPN_PASSWORD="testpass",
    SCHOOL_COOP_ACCOUNT_NO="01234567890100",
)
class CoopIPNViewTests(PaymentTestDataMixin, TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("payments:coop-ipn")
        self.create_common_school_data(admission_number="PWA3001", first_name="Peter", last_name="Smith")
        self.invoice.amount_paid = Decimal("0.00")
        self.invoice.balance = Decimal("50000.00")
        self.invoice.total_amount = Decimal("50000.00")
        self.invoice.save(update_fields=["amount_paid", "balance", "total_amount", "updated_at"])

    def auth_headers(self):
        return self.basic_auth("testuser", "testpass")

    def payload(self):
        return {
            "MessageReference": "COOP-MSG-001",
            "TransactionId": "TXN-COOP-123456",
            "AcctNo": "01234567890100",
            "TxnAmount": "25000.00",
            "TxnDate": "2025-01-15",
            "Currency": "KES",
            "DrCr": "C",
            "CustMemo": "School fees payment",
            "Narration1": "FT from Peter Smith Parent",
            "Narration2": "PWA3001 Term 1 fees",
            "Narration3": "",
            "EventType": "CREDIT",
            "Balance": "1000000.00",
            "ValueDate": "2025-01-15",
            "PostingDate": "2025-01-15",
            "BranchCode": "001",
        }

    @patch("payments.views.coop.NotificationService.send_payment_receipt", return_value=True)
    def test_ipn_success_with_admission_in_narration(self, _mock_receipt):
        response = self.client.post(self.url, data=self.payload(), format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["MessageCode"], "200")

        payment = Payment.objects.get(transaction_reference="TXN-COOP-123456")
        self.assertEqual(payment.amount, Decimal("25000.00"))
        self.assertEqual(payment.student, self.student)

        bank_txn = BankTransaction.objects.get(transaction_id="TXN-COOP-123456")
        self.assertEqual(bank_txn.processing_status, "matched")
        self.assertEqual(bank_txn.payment, payment)
        self.assertIsNotNone(bank_txn.matched_at)
        self.assertEqual(bank_txn.matched_at, payment.reconciled_at)

    def test_ipn_without_admission_in_narration(self):
        payload = self.payload()
        payload["Narration1"] = "General payment"
        payload["Narration2"] = "No reference number"
        response = self.client.post(self.url, data=payload, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["MessageCode"], "200")

        bank_txn = BankTransaction.objects.get(transaction_id="TXN-COOP-123456")
        self.assertEqual(bank_txn.processing_status, "received")
        self.assertIsNone(bank_txn.payment)

    def test_ipn_wrong_account_number(self):
        payload = self.payload()
        payload["AcctNo"] = "99999999999999"
        response = self.client.post(self.url, data=payload, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("account", response.json()["Message"].lower())

    def test_ipn_debit_transaction_ignored(self):
        payload = self.payload()
        payload["EventType"] = "DEBIT"
        payload["DrCr"] = "D"
        response = self.client.post(self.url, data=payload, format="json", **self.auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["MessageCode"], "200")
        self.assertFalse(BankTransaction.objects.filter(transaction_id="TXN-COOP-123456").exists())

    @patch("payments.views.coop.NotificationService.send_payment_receipt", return_value=True)
    def test_ipn_idempotency(self, _mock_receipt):
        response1 = self.client.post(self.url, data=self.payload(), format="json", **self.auth_headers())
        response2 = self.client.post(self.url, data=self.payload(), format="json", **self.auth_headers())
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(BankTransaction.objects.filter(transaction_id="TXN-COOP-123456").count(), 1)

    def test_ipn_no_auth(self):
        response = self.client.post(self.url, data=self.payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ipn_wrong_credentials(self):
        response = self.client.post(self.url, data=self.payload(), format="json", **self.basic_auth("wrong", "wrong"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ipn_missing_fields(self):
        response = self.client.post(
            self.url,
            data={"TransactionId": "TXN-123", "AcctNo": "01234567890100"},
            format="json",
            **self.auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(EQUITY_IPN_USERNAME="correctuser", EQUITY_IPN_PASSWORD="correctpass")
    def test_equity_auth_header_formats(self):
        url = reverse("payments:equity-validation")
        response = self.client.post(url, data={"billNumber": "TEST"}, format="json", **PaymentTestDataMixin.basic_auth("correctuser", "correctpass"))
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.post(url, data={"billNumber": "TEST"}, format="json", HTTP_AUTHORIZATION="Bearer correct-key")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.post(url, data={"billNumber": "TEST"}, format="json", HTTP_AUTHORIZATION="Basic not-base64!")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(COOP_IPN_USERNAME="user", COOP_IPN_PASSWORD="pass")
    def test_coop_basic_auth_formats(self):
        url = reverse("payments:coop-ipn")
        response = self.client.post(url, data={"TransactionId": "TEST"}, format="json", **PaymentTestDataMixin.basic_auth("user", "pass"))
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.post(url, data={"TransactionId": "TEST"}, format="json", HTTP_AUTHORIZATION="Basic not-base64!")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ErrorHandlingTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(EQUITY_IPN_USERNAME="testuser", EQUITY_IPN_PASSWORD="testpass")
    @patch("payments.views.equity.logger")
    def test_errors_are_logged(self, mock_logger):
        url = reverse("payments:equity-validation")
        response = self.client.post(
            url,
            data={"billNumber": "NONEXISTENT"},
            format="json",
            **PaymentTestDataMixin.basic_auth("testuser", "testpass"),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(mock_logger.warning.called or mock_logger.error.called)

    @override_settings(EQUITY_IPN_USERNAME="testuser", EQUITY_IPN_PASSWORD="testpass")
    def test_error_response_format(self):
        url = reverse("payments:equity-validation")
        response = self.client.post(
            url,
            data={"billNumber": "INVALID"},
            format="json",
            **PaymentTestDataMixin.basic_auth("testuser", "testpass"),
        )
        data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(data.keys()), {"billNumber", "customerName", "amount", "description"})
        self.assertEqual(data["amount"], "0")
        self.assertIn("not found", data["description"].lower())
