# File: payments/tests/test_views.py
# ============================================================
# RATIONALE: Integration tests for payment API endpoints
# - Tests full request/response cycle
# - Tests authentication
# - Tests idempotency
# - Uses sample payloads from bank documentation
# ============================================================

import json
import base64
from decimal import Decimal
from datetime import date
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from students.models import Student, Grade
from fees.models import Invoice
from payments.models import BankTransaction, Payment


@override_settings(
    EQUITY_API_KEY='test-equity-api-key-12345',
    COOP_IPN_USERNAME='testuser',
    COOP_IPN_PASSWORD='testpass',
    SCHOOL_COOP_ACCOUNT_NO='01234567890100'
)
class EquityValidationViewTests(TestCase):
    """Integration tests for Equity validation endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('payments:equity-validation')

        # Create test data
        self.grade = Grade.objects.create(
            name='Grade 3',
            code='G3',
            level='primary'
        )

        self.student = Student.objects.create(
            admission_number='PWA1001',
            first_name='Test',
            last_name='Student',
            date_of_birth=date(2017, 5, 15),
            gender='M',
            current_grade=self.grade,
            status='active'
        )

        self.invoice = Invoice.objects.create(
            student=self.student,
            invoice_number='INV-2025-TEST',
            academic_year=2025,
            term=1,
            total_amount=Decimal('50000.00'),
            amount_paid=Decimal('10000.00'),
            balance=Decimal('40000.00'),
            status='partially_paid',
            due_date=date(2025, 2, 15)
        )

    def get_auth_header(self):
        return {'HTTP_AUTHORIZATION': 'Api-Key test-equity-api-key-12345'}

    def test_validation_success(self):
        """Test successful bill validation"""
        response = self.client.post(
            self.url,
            data={'billNumber': 'PWA1001'},
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['billNumber'], 'PWA1001')
        self.assertEqual(data['customerName'], 'Test Student')
        self.assertEqual(Decimal(data['amount']), Decimal('40000.00'))
        self.assertIn('description', data)

    def test_validation_invalid_bill_number(self):
        """Test validation with non-existent bill number"""
        response = self.client.post(
            self.url,
            data={'billNumber': 'INVALID999'},
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        data = response.json()
        self.assertIn('error', data)

    def test_validation_inactive_student(self):
        """Test validation for inactive student"""
        self.student.status = 'withdrawn'
        self.student.save()

        response = self.client.post(
            self.url,
            data={'billNumber': 'PWA1001'},
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_validation_missing_bill_number(self):
        """Test validation without bill number"""
        response = self.client.post(
            self.url,
            data={},
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_no_auth(self):
        """Test validation without authentication"""
        response = self.client.post(
            self.url,
            data={'billNumber': 'PWA1001'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_validation_wrong_api_key(self):
        """Test validation with wrong API key"""
        response = self.client.post(
            self.url,
            data={'billNumber': 'PWA1001'},
            format='json',
            HTTP_AUTHORIZATION='Api-Key wrong-key'
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_validation_by_invoice_number(self):
        """Test validation using invoice number"""
        response = self.client.post(
            self.url,
            data={'billNumber': 'INV-2025-TEST'},
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['customerName'], 'Test Student')


@override_settings(
    EQUITY_API_KEY='test-equity-api-key-12345',
    COOP_IPN_USERNAME='testuser',
    COOP_IPN_PASSWORD='testpass',
    SCHOOL_COOP_ACCOUNT_NO='01234567890100'
)
class EquityNotificationViewTests(TestCase):
    """Integration tests for Equity notification endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('payments:equity-notification')

        # Create test data
        self.grade = Grade.objects.create(
            name='Grade 4',
            code='G4',
            level='primary'
        )

        self.student = Student.objects.create(
            admission_number='PWA2001',
            first_name='Jane',
            last_name='Doe',
            date_of_birth=date(2016, 8, 20),
            gender='F',
            current_grade=self.grade,
            status='active',
            parent_phone='254712345678'
        )

        self.invoice = Invoice.objects.create(
            student=self.student,
            invoice_number='INV-2025-002',
            academic_year=2025,
            term=1,
            total_amount=Decimal('45000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('45000.00'),
            status='unpaid',
            due_date=date(2025, 2, 15)
        )

    def get_auth_header(self):
        return {'HTTP_AUTHORIZATION': 'Api-Key test-equity-api-key-12345'}

    def get_valid_payload(self):
        return {
            'billNumber': 'PWA2001',
            'amount': '20000.00',
            'bankReference': 'EQ-REF-123456',
            'transactionDate': '2025-01-15T14:30:00',
            'customerName': 'Jane Doe Parent',
            'phoneNumber': '254712345678',
            'paymentChannel': 'MOBILE'
        }

    @patch('payments.services.notifications.send_sms')
    @patch('payments.services.notifications.send_email')
    def test_notification_success(self, mock_email, mock_sms):
        """Test successful payment notification"""
        mock_sms.return_value = True
        mock_email.return_value = True

        response = self.client.post(
            self.url,
            data=self.get_valid_payload(),
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['responseCode'], '00')
        self.assertIn('success', data['responseMessage'].lower())

        # Verify payment created
        payment = Payment.objects.filter(
            transaction_reference='EQ-REF-123456'
        ).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('20000.00'))
        self.assertEqual(payment.student, self.student)

        # Verify invoice updated
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('20000.00'))
        self.assertEqual(self.invoice.balance, Decimal('25000.00'))
        self.assertEqual(self.invoice.status, 'partially_paid')

        # Verify bank transaction created
        bank_txn = BankTransaction.objects.filter(
            transaction_reference='EQ-REF-123456'
        ).first()
        self.assertIsNotNone(bank_txn)
        self.assertTrue(bank_txn.is_matched)

    @patch('payments.services.notifications.send_sms')
    @patch('payments.services.notifications.send_email')
    def test_notification_idempotency(self, mock_email, mock_sms):
        """Test duplicate notification is rejected"""
        mock_sms.return_value = True
        mock_email.return_value = True

        payload = self.get_valid_payload()

        # First request
        response1 = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # Duplicate request
        response2 = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response2.status_code, status.HTTP_409_CONFLICT)
        data = response2.json()
        self.assertIn('duplicate', data['responseMessage'].lower())

        # Verify only one payment created
        payments = Payment.objects.filter(
            transaction_reference='EQ-REF-123456'
        )
        self.assertEqual(payments.count(), 1)

    def test_notification_invalid_bill(self):
        """Test notification with invalid bill number"""
        payload = self.get_valid_payload()
        payload['billNumber'] = 'INVALID999'

        response = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_notification_missing_fields(self):
        """Test notification with missing required fields"""
        payload = {'billNumber': 'PWA2001'}  # Missing amount, bankReference, etc.

        response = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_notification_no_auth(self):
        """Test notification without authentication"""
        response = self.client.post(
            self.url,
            data=self.get_valid_payload(),
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('payments.services.notifications.send_sms')
    @patch('payments.services.notifications.send_email')
    def test_notification_full_payment(self, mock_email, mock_sms):
        """Test notification that fully pays invoice"""
        mock_sms.return_value = True
        mock_email.return_value = True

        payload = self.get_valid_payload()
        payload['amount'] = '45000.00'  # Full amount

        response = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')
        self.assertEqual(self.invoice.balance, Decimal('0.00'))


@override_settings(
    EQUITY_API_KEY='test-equity-api-key-12345',
    COOP_IPN_USERNAME='testuser',
    COOP_IPN_PASSWORD='testpass',
    SCHOOL_COOP_ACCOUNT_NO='01234567890100'
)
class CoopIPNViewTests(TestCase):
    """Integration tests for Co-op IPN endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('payments:coop-ipn')

        # Create test data
        self.grade = Grade.objects.create(
            name='Grade 5',
            code='G5',
            level='primary'
        )

        self.student = Student.objects.create(
            admission_number='PWA3001',
            first_name='Peter',
            last_name='Smith',
            date_of_birth=date(2015, 3, 10),
            gender='M',
            current_grade=self.grade,
            status='active',
            parent_phone='254723456789'
        )

        self.invoice = Invoice.objects.create(
            student=self.student,
            invoice_number='INV-2025-003',
            academic_year=2025,
            term=1,
            total_amount=Decimal('50000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('50000.00'),
            status='unpaid',
            due_date=date(2025, 2, 15)
        )

    def get_auth_header(self):
        credentials = base64.b64encode(b'testuser:testpass').decode('utf-8')
        return {'HTTP_AUTHORIZATION': f'Basic {credentials}'}

    def get_valid_payload(self):
        return {
            'MessageReference': 'COOP-MSG-001',
            'TransactionId': 'TXN-COOP-123456',
            'AcctNo': '01234567890100',
            'TxnAmount': '25000.00',
            'TxnDate': '2025-01-15',
            'Currency': 'KES',
            'DrCr': 'C',
            'CustMemo': 'School fees payment',
            'Narration1': 'FT from Peter Smith Parent',
            'Narration2': 'PWA3001 Term 1 fees',
            'Narration3': '',
            'EventType': 'CREDIT',
            'Balance': '1000000.00',
            'ValueDate': '2025-01-15',
            'PostingDate': '2025-01-15',
            'BranchCode': '001'
        }

    @patch('payments.services.notifications.send_sms')
    @patch('payments.services.notifications.send_email')
    def test_ipn_success_with_admission_in_narration(self, mock_email, mock_sms):
        """Test successful IPN with admission number in narration"""
        mock_sms.return_value = True
        mock_email.return_value = True

        response = self.client.post(
            self.url,
            data=self.get_valid_payload(),
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['MessageCode'], '0')
        self.assertIn('success', data['Message'].lower())

        # Verify payment created and matched
        payment = Payment.objects.filter(student=self.student).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('25000.00'))
        self.assertEqual(payment.payment_method, 'coop')

        # Verify bank transaction
        bank_txn = BankTransaction.objects.filter(
            transaction_reference='TXN-COOP-123456'
        ).first()
        self.assertIsNotNone(bank_txn)
        self.assertTrue(bank_txn.is_matched)
        self.assertEqual(bank_txn.processing_status, 'matched')

    def test_ipn_without_admission_in_narration(self):
        """Test IPN without admission number - should store for manual matching"""
        payload = self.get_valid_payload()
        payload['Narration1'] = 'General payment'
        payload['Narration2'] = 'No reference number'

        response = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['MessageCode'], '0')

        # Verify bank transaction created but not matched
        bank_txn = BankTransaction.objects.filter(
            transaction_reference='TXN-COOP-123456'
        ).first()
        self.assertIsNotNone(bank_txn)
        self.assertFalse(bank_txn.is_matched)
        self.assertEqual(bank_txn.processing_status, 'received')
        self.assertIsNone(bank_txn.payment)

    def test_ipn_wrong_account_number(self):
        """Test IPN with wrong account number"""
        payload = self.get_valid_payload()
        payload['AcctNo'] = '99999999999999'

        response = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('account', data['Message'].lower())

    def test_ipn_debit_transaction_ignored(self):
        """Test that debit transactions are acknowledged but not processed"""
        payload = self.get_valid_payload()
        payload['EventType'] = 'DEBIT'
        payload['DrCr'] = 'D'

        response = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['MessageCode'], '0')

        # Verify no bank transaction created
        bank_txn = BankTransaction.objects.filter(
            transaction_reference='TXN-COOP-123456'
        ).exists()
        self.assertFalse(bank_txn)

    @patch('payments.services.notifications.send_sms')
    @patch('payments.services.notifications.send_email')
    def test_ipn_idempotency(self, mock_email, mock_sms):
        """Test duplicate IPN is rejected"""
        mock_sms.return_value = True
        mock_email.return_value = True

        payload = self.get_valid_payload()

        # First request
        response1 = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # Duplicate request
        response2 = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response2.status_code, status.HTTP_409_CONFLICT)

        # Verify only one transaction
        txn_count = BankTransaction.objects.filter(
            transaction_reference='TXN-COOP-123456'
        ).count()
        self.assertEqual(txn_count, 1)

    def test_ipn_no_auth(self):
        """Test IPN without authentication"""
        response = self.client.post(
            self.url,
            data=self.get_valid_payload(),
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ipn_wrong_credentials(self):
        """Test IPN with wrong credentials"""
        wrong_creds = base64.b64encode(b'wrong:wrong').decode('utf-8')

        response = self.client.post(
            self.url,
            data=self.get_valid_payload(),
            format='json',
            HTTP_AUTHORIZATION=f'Basic {wrong_creds}'
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ipn_missing_fields(self):
        """Test IPN with missing required fields"""
        payload = {
            'TransactionId': 'TXN-123',
            'AcctNo': '01234567890100'
            # Missing other required fields
        }

        response = self.client.post(
            self.url,
            data=payload,
            format='json',
            **self.get_auth_header()
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AuthenticationTests(TestCase):
    """Tests specifically for authentication mechanisms"""

    def setUp(self):
        self.client = APIClient()

    @override_settings(EQUITY_API_KEY='correct-key')
    def test_equity_auth_header_formats(self):
        """Test various API key header formats"""
        url = reverse('payments:equity-validation')

        # Correct format
        response = self.client.post(
            url,
            data={'billNumber': 'TEST'},
            format='json',
            HTTP_AUTHORIZATION='Api-Key correct-key'
        )
        # Will be 404 (bill not found) not 401 (unauthorized)
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Wrong prefix
        response = self.client.post(
            url,
            data={'billNumber': 'TEST'},
            format='json',
            HTTP_AUTHORIZATION='Bearer correct-key'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # No prefix
        response = self.client.post(
            url,
            data={'billNumber': 'TEST'},
            format='json',
            HTTP_AUTHORIZATION='correct-key'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(COOP_IPN_USERNAME='user', COOP_IPN_PASSWORD='pass')
    def test_coop_basic_auth_formats(self):
        """Test various Basic auth header formats"""
        url = reverse('payments:coop-ipn')

        # Correct format
        creds = base64.b64encode(b'user:pass').decode('utf-8')
        response = self.client.post(
            url,
            data={'TransactionId': 'TEST'},
            format='json',
            HTTP_AUTHORIZATION=f'Basic {creds}'
        )
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Wrong encoding
        response = self.client.post(
            url,
            data={'TransactionId': 'TEST'},
            format='json',
            HTTP_AUTHORIZATION='Basic not-base64!'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ErrorHandlingTests(TestCase):
    """Tests for error handling and logging"""

    def setUp(self):
        self.client = APIClient()

    @override_settings(EQUITY_API_KEY='test-key')
    @patch('payments.views.equity.logger')
    def test_errors_are_logged(self, mock_logger):
        """Test that errors are properly logged"""
        url = reverse('payments:equity-validation')

        response = self.client.post(
            url,
            data={'billNumber': 'NONEXISTENT'},
            format='json',
            HTTP_AUTHORIZATION='Api-Key test-key'
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Verify logging was called
        self.assertTrue(mock_logger.warning.called or mock_logger.error.called)

    @override_settings(EQUITY_API_KEY='test-key')
    def test_error_response_format(self):
        """Test error responses match expected format"""
        url = reverse('payments:equity-validation')

        response = self.client.post(
            url,
            data={'billNumber': 'INVALID'},
            format='json',
            HTTP_AUTHORIZATION='Api-Key test-key'
        )

        data = response.json()
        # Should have error field
        self.assertIn('error', data)
        # Should have responseCode for Equity
        self.assertIn('responseCode', data)
        self.assertNotEqual(data['responseCode'], '00')