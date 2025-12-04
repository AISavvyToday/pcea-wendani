# File: payments/tests/test_services.py
# ============================================================
# RATIONALE: Unit tests for all payment services
# - Tests each service function in isolation
# - Mocks external dependencies (SMS, Email)
# - Covers success and failure scenarios
# ============================================================

from decimal import Decimal
from datetime import date, datetime
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from students.models import Student, Grade
from fees.models import Invoice, InvoiceItem, FeeStructure, FeeItem
from payments.models import Payment, BankTransaction, PaymentAllocation
from payments.services.bank_transaction import BankTransactionService
from payments.services.resolution import StudentResolutionService
from payments.services.payment import PaymentCreationService
from payments.services.invoice import InvoiceUpdateService
from payments.services.notifications import NotificationService
from payments.exceptions import (
    BillNotFoundError,
    DuplicateTransactionError,
    InvalidAccountError,
    PaymentProcessingError
)

User = get_user_model()


class BankTransactionServiceTests(TestCase):
    """Tests for BankTransactionService"""

    def setUp(self):
        self.service = BankTransactionService()
        self.equity_payload = {
            'billNumber': 'PWA1001',
            'amount': '15000.00',
            'bankReference': 'EQ123456789',
            'transactionDate': '2025-01-15T10:30:00',
            'customerName': 'John Doe',
            'phoneNumber': '254712345678',
            'paymentChannel': 'MOBILE'
        }
        self.coop_payload = {
            'MessageReference': 'COOP-REF-001',
            'TransactionId': 'TXN123456',
            'AcctNo': '01234567890100',
            'TxnAmount': '25000.00',
            'TxnDate': '2025-01-15',
            'Currency': 'KES',
            'DrCr': 'C',
            'CustMemo': 'School fees PWA1002',
            'Narration1': 'FT from John Doe',
            'Narration2': 'PWA1002 Term 1 fees',
            'Narration3': '',
            'EventType': 'CREDIT',
            'Balance': '500000.00',
            'ValueDate': '2025-01-15',
            'PostingDate': '2025-01-15',
            'BranchCode': '001'
        }

    def test_create_equity_bank_transaction_success(self):
        """Test successful creation of Equity bank transaction"""
        txn = self.service.create_equity_bank_transaction(self.equity_payload)

        self.assertIsNotNone(txn)
        self.assertEqual(txn.transaction_reference, 'EQ123456789')
        self.assertEqual(txn.customer_name, 'John Doe')
        self.assertEqual(txn.amount, Decimal('15000.00'))
        self.assertEqual(txn.source_bank, 'equity')
        self.assertEqual(txn.processing_status, 'received')
        self.assertFalse(txn.is_matched)

    def test_create_coop_bank_transaction_success(self):
        """Test successful creation of Co-op bank transaction"""
        txn = self.service.create_coop_bank_transaction(self.coop_payload)

        self.assertIsNotNone(txn)
        self.assertEqual(txn.transaction_reference, 'TXN123456')
        self.assertEqual(txn.amount, Decimal('25000.00'))
        self.assertEqual(txn.source_bank, 'coop')
        self.assertEqual(txn.narration, 'FT from John Doe | PWA1002 Term 1 fees')

    def test_check_duplicate_transaction_equity(self):
        """Test duplicate detection for Equity transactions"""
        # Create first transaction
        self.service.create_equity_bank_transaction(self.equity_payload)

        # Check for duplicate
        is_duplicate = self.service.check_duplicate_transaction(
            gateway='equity',
            transaction_id='EQ123456789'
        )
        self.assertTrue(is_duplicate)

        # Check non-existent
        is_duplicate = self.service.check_duplicate_transaction(
            gateway='equity',
            transaction_id='NONEXISTENT'
        )
        self.assertFalse(is_duplicate)

    def test_check_duplicate_transaction_coop(self):
        """Test duplicate detection for Co-op transactions"""
        self.service.create_coop_bank_transaction(self.coop_payload)

        is_duplicate = self.service.check_duplicate_transaction(
            gateway='coop',
            transaction_id='TXN123456'
        )
        self.assertTrue(is_duplicate)

    def test_create_equity_transaction_with_missing_fields(self):
        """Test handling of missing optional fields"""
        minimal_payload = {
            'billNumber': 'PWA1001',
            'amount': '15000.00',
            'bankReference': 'EQ999999999',
            'transactionDate': '2025-01-15T10:30:00'
        }
        txn = self.service.create_equity_bank_transaction(minimal_payload)

        self.assertIsNotNone(txn)
        self.assertEqual(txn.customer_name, '')
        self.assertEqual(txn.customer_phone, '')


class StudentResolutionServiceTests(TestCase):
    """Tests for StudentResolutionService"""

    def setUp(self):
        self.service = StudentResolutionService()

        # Create test grade
        self.grade = Grade.objects.create(
            name='Grade 5',
            code='G5',
            level='primary'
        )

        # Create test student
        self.student = Student.objects.create(
            admission_number='PWA1001',
            first_name='Jane',
            last_name='Doe',
            date_of_birth=date(2015, 5, 10),
            gender='F',
            current_grade=self.grade,
            status='active'
        )

        # Create invoice
        self.invoice = Invoice.objects.create(
            student=self.student,
            invoice_number='INV-2025-001',
            academic_year=2025,
            term=1,
            total_amount=Decimal('50000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('50000.00'),
            status='unpaid',
            due_date=date(2025, 2, 15)
        )

    def test_resolve_bill_number_by_admission(self):
        """Test resolution by admission number"""
        student, invoice = self.service.resolve_bill_number('PWA1001')

        self.assertEqual(student, self.student)
        self.assertEqual(invoice, self.invoice)

    def test_resolve_bill_number_by_invoice(self):
        """Test resolution by invoice number"""
        student, invoice = self.service.resolve_bill_number('INV-2025-001')

        self.assertEqual(student, self.student)
        self.assertEqual(invoice, self.invoice)

    def test_resolve_bill_number_not_found(self):
        """Test BillNotFoundError for invalid bill number"""
        with self.assertRaises(BillNotFoundError) as context:
            self.service.resolve_bill_number('INVALID123')

        self.assertIn('INVALID123', str(context.exception))

    def test_resolve_bill_number_inactive_student(self):
        """Test handling of inactive student"""
        self.student.status = 'withdrawn'
        self.student.save()

        with self.assertRaises(BillNotFoundError) as context:
            self.service.resolve_bill_number('PWA1001')

        self.assertIn('not active', str(context.exception))

    def test_extract_admission_from_narration_success(self):
        """Test extraction of admission number from narration"""
        narrations = [
            'FT from John Doe',
            'School fees PWA1001',
            'Term 1 payment'
        ]
        result = self.service.extract_admission_from_narration(narrations)
        self.assertEqual(result, 'PWA1001')

    def test_extract_admission_from_narration_variations(self):
        """Test various narration formats"""
        test_cases = [
            (['Payment for PWA1001'], 'PWA1001'),
            (['pwa1001 fees'], 'PWA1001'),
            (['Ref: PWA-1001'], 'PWA1001'),
            (['Student PWA 1001 fees'], 'PWA1001'),
        ]

        for narrations, expected in test_cases:
            result = self.service.extract_admission_from_narration(narrations)
            self.assertEqual(result, expected, f"Failed for: {narrations}")

    def test_extract_admission_from_narration_not_found(self):
        """Test when no admission number in narration"""
        narrations = ['General payment', 'No reference']
        result = self.service.extract_admission_from_narration(narrations)
        self.assertIsNone(result)

    def test_resolve_student_only(self):
        """Test resolving student without invoice requirement"""
        student = self.service.resolve_student_only('PWA1001')
        self.assertEqual(student, self.student)

    def test_get_outstanding_amount(self):
        """Test getting outstanding amount for student"""
        amount = self.service.get_outstanding_amount(self.student)
        self.assertEqual(amount, Decimal('50000.00'))


class PaymentCreationServiceTests(TestCase):
    """Tests for PaymentCreationService"""

    def setUp(self):
        self.service = PaymentCreationService()

        # Create user for created_by
        self.user = User.objects.create_user(
            username='system',
            email='system@school.com',
            password='testpass123'
        )

        # Create grade and student
        self.grade = Grade.objects.create(
            name='Grade 6',
            code='G6',
            level='primary'
        )

        self.student = Student.objects.create(
            admission_number='PWA2001',
            first_name='Peter',
            last_name='Smith',
            date_of_birth=date(2014, 3, 20),
            gender='M',
            current_grade=self.grade,
            status='active'
        )

        # Create invoice
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

        # Create bank transaction
        self.bank_txn = BankTransaction.objects.create(
            transaction_reference='EQ-TEST-001',
            source_bank='equity',
            amount=Decimal('20000.00'),
            customer_name='Peter Smith Parent',
            transaction_date=timezone.now(),
            processing_status='received'
        )

    def test_create_payment_from_bank_transaction(self):
        """Test creating payment from bank transaction"""
        payment = self.service.create_payment_from_bank_tx(
            bank_tx=self.bank_txn,
            student=self.student,
            invoice=self.invoice,
            amount=Decimal('20000.00')
        )

        self.assertIsNotNone(payment)
        self.assertEqual(payment.student, self.student)
        self.assertEqual(payment.amount, Decimal('20000.00'))
        self.assertEqual(payment.payment_method, 'equity')
        self.assertEqual(payment.status, 'completed')
        self.assertIsNotNone(payment.receipt_number)
        self.assertTrue(payment.receipt_number.startswith('RCP'))

        # Check bank transaction is linked
        self.bank_txn.refresh_from_db()
        self.assertEqual(self.bank_txn.payment, payment)
        self.assertEqual(self.bank_txn.processing_status, 'matched')
        self.assertTrue(self.bank_txn.is_matched)

    def test_create_payment_generates_unique_receipt(self):
        """Test that each payment gets unique receipt number"""
        payment1 = self.service.create_payment_from_bank_tx(
            bank_tx=self.bank_txn,
            student=self.student,
            invoice=self.invoice,
            amount=Decimal('10000.00')
        )

        # Create another bank transaction
        bank_txn2 = BankTransaction.objects.create(
            transaction_reference='EQ-TEST-002',
            source_bank='equity',
            amount=Decimal('10000.00'),
            customer_name='Peter Smith Parent',
            transaction_date=timezone.now(),
            processing_status='received'
        )

        payment2 = self.service.create_payment_from_bank_tx(
            bank_tx=bank_txn2,
            student=self.student,
            invoice=self.invoice,
            amount=Decimal('10000.00')
        )

        self.assertNotEqual(payment1.receipt_number, payment2.receipt_number)

    def test_create_payment_with_coop_source(self):
        """Test payment creation from Co-op transaction"""
        coop_txn = BankTransaction.objects.create(
            transaction_reference='COOP-TEST-001',
            source_bank='coop',
            amount=Decimal('15000.00'),
            customer_name='Parent Name',
            transaction_date=timezone.now(),
            processing_status='received'
        )

        payment = self.service.create_payment_from_bank_tx(
            bank_tx=coop_txn,
            student=self.student,
            invoice=self.invoice,
            amount=Decimal('15000.00')
        )

        self.assertEqual(payment.payment_method, 'coop')

    def test_generate_receipt_number_format(self):
        """Test receipt number format"""
        receipt = self.service._generate_receipt_number()

        self.assertTrue(receipt.startswith('RCP'))
        self.assertEqual(len(receipt), 16)  # RCP + YYYYMMDD + 5 digits


class InvoiceUpdateServiceTests(TestCase):
    """Tests for InvoiceUpdateService"""

    def setUp(self):
        self.service = InvoiceUpdateService()

        # Create grade and student
        self.grade = Grade.objects.create(
            name='Grade 7',
            code='G7',
            level='primary'
        )

        self.student = Student.objects.create(
            admission_number='PWA3001',
            first_name='Mary',
            last_name='Johnson',
            date_of_birth=date(2013, 7, 15),
            gender='F',
            current_grade=self.grade,
            status='active'
        )

        # Create fee structure and items
        self.fee_structure = FeeStructure.objects.create(
            name='Grade 7 Fees 2025',
            academic_year=2025,
            term=1,
            grade=self.grade,
            total_amount=Decimal('40000.00'),
            is_active=True
        )

        self.fee_item_tuition = FeeItem.objects.create(
            fee_structure=self.fee_structure,
            name='Tuition',
            fee_type='tuition',
            amount=Decimal('25000.00'),
            is_mandatory=True,
            priority=1
        )

        self.fee_item_lunch = FeeItem.objects.create(
            fee_structure=self.fee_structure,
            name='Lunch',
            fee_type='lunch',
            amount=Decimal('10000.00'),
            is_mandatory=True,
            priority=2
        )

        self.fee_item_transport = FeeItem.objects.create(
            fee_structure=self.fee_structure,
            name='Transport',
            fee_type='transport',
            amount=Decimal('5000.00'),
            is_mandatory=False,
            priority=3
        )

        # Create invoice with items
        self.invoice = Invoice.objects.create(
            student=self.student,
            invoice_number='INV-2025-003',
            academic_year=2025,
            term=1,
            total_amount=Decimal('40000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('40000.00'),
            status='unpaid',
            due_date=date(2025, 2, 15)
        )

        # Create invoice items
        InvoiceItem.objects.create(
            invoice=self.invoice,
            fee_item=self.fee_item_tuition,
            amount=Decimal('25000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('25000.00')
        )

        InvoiceItem.objects.create(
            invoice=self.invoice,
            fee_item=self.fee_item_lunch,
            amount=Decimal('10000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('10000.00')
        )

        InvoiceItem.objects.create(
            invoice=self.invoice,
            fee_item=self.fee_item_transport,
            amount=Decimal('5000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('5000.00')
        )

        # Create payment
        self.payment = Payment.objects.create(
            student=self.student,
            amount=Decimal('30000.00'),
            payment_method='equity',
            payment_date=timezone.now().date(),
            transaction_reference='EQ-PAY-001',
            receipt_number='RCP20250115001',
            status='completed',
            academic_year=2025,
            term=1
        )

    def test_apply_payment_to_invoice_partial(self):
        """Test partial payment application"""
        self.service.apply_payment_to_invoice(self.payment, self.invoice)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('30000.00'))
        self.assertEqual(self.invoice.balance, Decimal('10000.00'))
        self.assertEqual(self.invoice.status, 'partially_paid')

    def test_apply_payment_to_invoice_full(self):
        """Test full payment application"""
        self.payment.amount = Decimal('40000.00')
        self.payment.save()

        self.service.apply_payment_to_invoice(self.payment, self.invoice)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('40000.00'))
        self.assertEqual(self.invoice.balance, Decimal('0.00'))
        self.assertEqual(self.invoice.status, 'paid')

    def test_apply_payment_overpayment(self):
        """Test overpayment handling (creates credit)"""
        self.payment.amount = Decimal('50000.00')
        self.payment.save()

        self.service.apply_payment_to_invoice(self.payment, self.invoice)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('40000.00'))
        self.assertEqual(self.invoice.balance, Decimal('0.00'))
        self.assertEqual(self.invoice.status, 'paid')

        # Check credit balance on student
        self.student.refresh_from_db()
        self.assertEqual(self.student.credit_balance, Decimal('10000.00'))

    def test_allocate_payment_to_items_by_priority(self):
        """Test payment allocation follows priority order"""
        allocations = self.service.allocate_payment_to_items(
            self.payment,
            self.invoice
        )

        self.assertEqual(len(allocations), 2)  # Should cover tuition + part of lunch

        # Check tuition fully paid
        tuition_item = InvoiceItem.objects.get(
            invoice=self.invoice,
            fee_item=self.fee_item_tuition
        )
        self.assertEqual(tuition_item.amount_paid, Decimal('25000.00'))
        self.assertEqual(tuition_item.balance, Decimal('0.00'))

        # Check lunch partially paid
        lunch_item = InvoiceItem.objects.get(
            invoice=self.invoice,
            fee_item=self.fee_item_lunch
        )
        self.assertEqual(lunch_item.amount_paid, Decimal('5000.00'))
        self.assertEqual(lunch_item.balance, Decimal('5000.00'))

        # Check transport not touched
        transport_item = InvoiceItem.objects.get(
            invoice=self.invoice,
            fee_item=self.fee_item_transport
        )
        self.assertEqual(transport_item.amount_paid, Decimal('0.00'))

    def test_allocate_payment_creates_allocation_records(self):
        """Test PaymentAllocation records are created"""
        self.service.allocate_payment_to_items(self.payment, self.invoice)

        allocations = PaymentAllocation.objects.filter(payment=self.payment)
        self.assertEqual(allocations.count(), 2)

        # Verify allocation amounts
        total_allocated = sum(a.amount for a in allocations)
        self.assertEqual(total_allocated, Decimal('30000.00'))


class NotificationServiceTests(TestCase):
    """Tests for NotificationService"""

    def setUp(self):
        self.service = NotificationService()

        # Create grade and student with parent contact
        self.grade = Grade.objects.create(
            name='Grade 8',
            code='G8',
            level='primary'
        )

        self.student = Student.objects.create(
            admission_number='PWA4001',
            first_name='David',
            last_name='Wilson',
            date_of_birth=date(2012, 11, 5),
            gender='M',
            current_grade=self.grade,
            status='active',
            parent_phone='254712345678',
            parent_email='parent@example.com'
        )

        # Create payment
        self.payment = Payment.objects.create(
            student=self.student,
            amount=Decimal('25000.00'),
            payment_method='equity',
            payment_date=timezone.now().date(),
            transaction_reference='EQ-NOTIF-001',
            receipt_number='RCP20250115002',
            status='completed',
            academic_year=2025,
            term=1
        )

    @patch('payments.services.notifications.send_sms')
    def test_send_payment_receipt_sms(self, mock_send_sms):
        """Test SMS receipt sending"""
        mock_send_sms.return_value = True

        result = self.service.send_payment_receipt(self.payment)

        self.assertTrue(result['sms_sent'])
        mock_send_sms.assert_called_once()

        # Verify SMS content
        call_args = mock_send_sms.call_args
        self.assertIn('254712345678', call_args[0])
        self.assertIn('25,000', call_args[0][1])  # Amount formatted
        self.assertIn('RCP20250115002', call_args[0][1])  # Receipt number

    @patch('payments.services.notifications.send_email')
    def test_send_payment_receipt_email(self, mock_send_email):
        """Test email receipt sending"""
        mock_send_email.return_value = True

        result = self.service.send_payment_receipt(self.payment)

        self.assertTrue(result['email_sent'])
        mock_send_email.assert_called_once()

        # Verify email content
        call_args = mock_send_email.call_args
        self.assertEqual(call_args[1]['to'], 'parent@example.com')
        self.assertIn('Payment Receipt', call_args[1]['subject'])

    @patch('payments.services.notifications.send_sms')
    @patch('payments.services.notifications.send_email')
    def test_send_payment_receipt_updates_payment(self, mock_email, mock_sms):
        """Test payment record is updated after sending receipt"""
        mock_sms.return_value = True
        mock_email.return_value = True

        self.service.send_payment_receipt(self.payment)

        self.payment.refresh_from_db()
        self.assertTrue(self.payment.receipt_sent)
        self.assertIsNotNone(self.payment.receipt_sent_at)

    @patch('payments.services.notifications.send_sms')
    def test_send_receipt_no_phone(self, mock_send_sms):
        """Test handling when no phone number"""
        self.student.parent_phone = ''
        self.student.save()

        result = self.service.send_payment_receipt(self.payment)

        self.assertFalse(result['sms_sent'])
        mock_send_sms.assert_not_called()

    @patch('payments.services.notifications.send_sms')
    def test_send_receipt_sms_failure(self, mock_send_sms):
        """Test handling of SMS sending failure"""
        mock_send_sms.side_effect = Exception('SMS gateway error')

        result = self.service.send_payment_receipt(self.payment)

        self.assertFalse(result['sms_sent'])
        self.assertIn('error', result)

    def test_format_receipt_message(self):
        """Test receipt message formatting"""
        message = self.service._format_sms_message(self.payment)

        self.assertIn('David Wilson', message)
        self.assertIn('KES 25,000', message)
        self.assertIn('RCP20250115002', message)
        self.assertIn('PCEA Wendani', message)


class PaymentMatchingServiceTests(TestCase):
    """Tests for the payment matching service used in admin"""

    def setUp(self):
        from payments.services import PaymentMatchingService
        self.service = PaymentMatchingService()

        # Create grade and student
        self.grade = Grade.objects.create(
            name='Grade 4',
            code='G4',
            level='primary'
        )

        self.student = Student.objects.create(
            admission_number='PWA5001',
            first_name='Sarah',
            last_name='Brown',
            date_of_birth=date(2016, 2, 28),
            gender='F',
            current_grade=self.grade,
            status='active'
        )

        # Create invoice
        self.invoice = Invoice.objects.create(
            student=self.student,
            invoice_number='INV-2025-005',
            academic_year=2025,
            term=1,
            total_amount=Decimal('35000.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('35000.00'),
            status='unpaid',
            due_date=date(2025, 2, 15)
        )

        # Create unmatched bank transaction with admission in narration
        self.bank_txn = BankTransaction.objects.create(
            transaction_reference='COOP-MATCH-001',
            source_bank='coop',
            amount=Decimal('20000.00'),
            customer_name='Brown Family',
            narration='School fees PWA5001 Term 1',
            transaction_date=timezone.now(),
            processing_status='received',
            is_matched=False
        )

    def test_match_transaction_success(self):
        """Test successful automatic matching"""
        result = self.service.match_transaction(self.bank_txn)

        self.assertTrue(result)
        self.bank_txn.refresh_from_db()
        self.assertTrue(self.bank_txn.is_matched)
        self.assertEqual(self.bank_txn.processing_status, 'matched')
        self.assertIsNotNone(self.bank_txn.payment)

    def test_match_transaction_no_admission_found(self):
        """Test matching fails when no admission number in narration"""
        self.bank_txn.narration = 'General payment no reference'
        self.bank_txn.save()

        result = self.service.match_transaction(self.bank_txn)

        self.assertFalse(result)
        self.bank_txn.refresh_from_db()
        self.assertFalse(self.bank_txn.is_matched)

    def test_manual_match_transaction(self):
        """Test manual matching by admin"""
        result = self.service.manual_match(
            bank_transaction=self.bank_txn,
            student=self.student,
            matched_by=None  # System
        )

        self.assertTrue(result)
        self.bank_txn.refresh_from_db()
        self.assertTrue(self.bank_txn.is_matched)
        self.assertEqual(self.bank_txn.matching_status, 'manual')