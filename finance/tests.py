from decimal import Decimal
from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academics.models import AcademicYear, Term
from core.models import Organization, UserRole
from finance.models import Invoice, InvoiceItem
from payments.models import BankTransaction, Payment, PaymentAllocation
from students.models import Parent, Student, StudentParent
from portal.views import _finance_kpis


class BankTransactionReconciliationViewTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='PCEA Wendani Academy',
            code='PWA',
        )
        self.user = User.objects.create_user(
            email='accountant@example.com',
            password='testpass123',
            first_name='Ava',
            last_name='Accountant',
            role=UserRole.ACCOUNTANT,
            organization=self.organization,
        )
        self.client.force_login(self.user)

        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term='term_1',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 30),
            is_current=True,
        )

        self.student_one = self._create_student('ADM001', 'Alice', 'Wanjiru', '254700111222')
        self.student_two = self._create_student('ADM002', 'Brian', 'Otieno', '254700333444')

    def _create_student(self, admission_number, first_name, last_name, phone):
        student = Student.objects.create(
            organization=self.organization,
            admission_number=admission_number,
            admission_date=date(2026, 1, 5),
            first_name=first_name,
            last_name=last_name,
            gender='F' if first_name == 'Alice' else 'M',
            date_of_birth=date(2016, 5, 20),
            status='active',
        )
        parent = Parent.objects.create(
            organization=self.organization,
            first_name=f'{first_name} Parent',
            last_name=last_name,
            phone_primary=phone,
            relationship='guardian',
        )
        StudentParent.objects.create(
            student=student,
            parent=parent,
            relationship='guardian',
            is_primary=True,
        )
        return student

    def _create_invoice(self, student, number, amount):
        invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number=number,
            student=student,
            term=self.term,
            subtotal=amount,
            total_amount=amount,
            balance=amount,
            issue_date=self.term.start_date,
            due_date=self.term.end_date,
            generated_by=self.user,
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description='Tuition',
            category='tuition',
            amount=amount,
            net_amount=amount,
        )
        invoice.refresh_from_db()
        return invoice

    def _create_transaction(
        self,
        transaction_id='EQ123',
        amount=Decimal('1000.00'),
        gateway='equity',
        processing_status='received',
        matched_at=None,
    ):
        bank_timestamp = timezone.now().replace(hour=14, minute=35, second=0, microsecond=0)
        transaction = BankTransaction.objects.create(
            gateway=gateway,
            transaction_id=transaction_id,
            transaction_reference='REF-001',
            amount=amount,
            currency='KES',
            payer_account='254700111222',
            payer_name='Parent Depositor',
            bank_status='SUCCESS',
            bank_status_description='Payment received',
            bank_timestamp=bank_timestamp,
            raw_request={
                'billNumber': 'ADM001',
                'phonenumber': '254700111222',
                'paymentMode': 'CASH',
            },
            raw_response={},
            processing_status=processing_status,
            matched_at=matched_at,
        )
        callback_time = bank_timestamp + timedelta(minutes=7)
        BankTransaction.objects.filter(pk=transaction.pk).update(callback_received_at=callback_time)
        transaction.refresh_from_db()
        return transaction

    def test_single_student_match_creates_payment_and_marks_timestamp(self):
        invoice = self._create_invoice(self.student_one, 'INV-001', Decimal('1000.00'))
        transaction = self._create_transaction(amount=Decimal('1000.00'))

        response = self.client.post(
            reverse('finance:bank_transaction_match', args=[transaction.pk]),
            data={
                'notes': 'Matched by operator',
                'search_query': 'ADM001',
                'allocations-TOTAL_FORMS': '1',
                'allocations-INITIAL_FORMS': '0',
                'allocations-MIN_NUM_FORMS': '1',
                'allocations-MAX_NUM_FORMS': '1000',
                'allocations-0-student': str(self.student_one.pk),
                'allocations-0-invoice': str(invoice.pk),
                'allocations-0-amount': '1000.00',
            },
        )

        self.assertRedirects(response, reverse('finance:bank_transaction_list'))
        transaction.refresh_from_db()
        payment = Payment.objects.get(student=self.student_one, transaction_reference=transaction.transaction_id)

        self.assertEqual(payment.amount, Decimal('1000.00'))
        self.assertEqual(transaction.processing_status, 'matched')
        self.assertIsNotNone(transaction.matched_at)
        self.assertEqual(transaction.matched_by, self.user)
        self.assertEqual(transaction.reconciliations.count(), 1)
        self.assertEqual(transaction.reconciliations.first().invoice, invoice)

    def test_partial_multi_student_match_keeps_remaining_amount(self):
        self._create_invoice(self.student_one, 'INV-101', Decimal('800.00'))
        self._create_invoice(self.student_two, 'INV-102', Decimal('900.00'))
        transaction = self._create_transaction(transaction_id='EQMULTI', amount=Decimal('1000.00'))

        response = self.client.post(
            reverse('finance:bank_transaction_match', args=[transaction.pk]),
            data={
                'notes': 'Split between siblings',
                'search_query': '254700',
                'allocations-TOTAL_FORMS': '2',
                'allocations-INITIAL_FORMS': '0',
                'allocations-MIN_NUM_FORMS': '1',
                'allocations-MAX_NUM_FORMS': '1000',
                'allocations-0-student': str(self.student_one.pk),
                'allocations-0-invoice': '',
                'allocations-0-amount': '600.00',
                'allocations-1-student': str(self.student_two.pk),
                'allocations-1-invoice': '',
                'allocations-1-amount': '250.00',
            },
        )

        self.assertRedirects(response, reverse('finance:bank_transaction_list'))
        transaction.refresh_from_db()

        self.assertEqual(transaction.processing_status, 'processing')
        self.assertEqual(transaction.allocated_amount, Decimal('850.00'))
        self.assertEqual(transaction.remaining_amount, Decimal('150.00'))
        self.assertEqual(transaction.reconciliations.count(), 2)
        self.assertEqual(
            Payment.objects.filter(transaction_reference=transaction.transaction_id).count(),
            2,
        )

    def test_search_by_parent_phone_shows_student(self):
        transaction = self._create_transaction(transaction_id='EQPHONE', amount=Decimal('500.00'))

        response = self.client.get(
            reverse('finance:bank_transaction_match', args=[transaction.pk]),
            {'q': '254700111222'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student_one.full_name)
        self.assertContains(response, '254700111222')

    @override_settings(
        TIME_ZONE='Africa/Nairobi',
        STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage',
    )
    def test_matched_timestamp_visibility_uses_consistent_timezone_in_list_and_detail(self):
        self._create_invoice(self.student_one, 'INV-301', Decimal('500.00'))
        transaction = self._create_transaction(transaction_id='EQTIME', amount=Decimal('500.00'))

        self.client.post(
            reverse('finance:bank_transaction_match', args=[transaction.pk]),
            data={
                'notes': 'Visibility test',
                'search_query': 'Alice',
                'allocations-TOTAL_FORMS': '1',
                'allocations-INITIAL_FORMS': '0',
                'allocations-MIN_NUM_FORMS': '1',
                'allocations-MAX_NUM_FORMS': '1000',
                'allocations-0-student': str(self.student_one.pk),
                'allocations-0-invoice': '',
                'allocations-0-amount': '500.00',
            },
        )
        transaction.refresh_from_db()

        list_response = self.client.get(reverse('finance:bank_transaction_list'), {'status': 'matched'})
        detail_response = self.client.get(reverse('finance:bank_transaction_detail', args=[transaction.pk]))

        self.assertContains(list_response, transaction.bank_timestamp.strftime('%d/%m/%Y %H:%M'))
        self.assertContains(list_response, transaction.matched_at.strftime('%d/%m/%Y %H:%M'))
        self.assertContains(detail_response, transaction.effective_received_at.strftime('%d %b %Y %H:%M'))
        self.assertContains(detail_response, transaction.effective_matched_at.strftime('%d %b %Y %H:%M'))

    @override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
    def test_unmatched_list_displays_equity_source_label(self):
        self._create_transaction(transaction_id='EQ-SOURCE-1', gateway='equity')

        response = self.client.get(reverse('finance:bank_transaction_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Equity Bank')

    @override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
    def test_unmatched_list_displays_coop_source_label(self):
        self._create_transaction(transaction_id='COOP-SOURCE-1', gateway='coop')

        response = self.client.get(reverse('finance:bank_transaction_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Co-Operative Bank')

    @override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
    def test_unmatched_filter_excludes_rows_with_matched_timestamp(self):
        matched_time = timezone.now()
        self._create_transaction(
            transaction_id='EQ-MATCHED-1',
            gateway='equity',
            processing_status='received',
            matched_at=matched_time,
        )
        unmatched = self._create_transaction(
            transaction_id='EQ-UNMATCHED-1',
            gateway='equity',
            processing_status='matched',
            matched_at=None,
        )

        response = self.client.get(reverse('finance:bank_transaction_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, unmatched.transaction_id)
        self.assertNotContains(response, 'EQ-MATCHED-1')
        expected_received_list = transaction.effective_received_at.strftime('%d/%m/%Y %H:%M')
        expected_matched_list = transaction.matched_at.strftime('%d/%m/%Y %H:%M')
        expected_received_detail = transaction.effective_received_at.strftime('%d %b %Y %H:%M')
        expected_matched_detail = transaction.effective_matched_at.strftime('%d %b %Y %H:%M')

        self.assertContains(list_response, expected_received_list)
        self.assertContains(list_response, expected_matched_list)
        self.assertContains(detail_response, expected_received_detail)
        self.assertContains(detail_response, expected_matched_detail)


class DeleteRefreshesDashboardKpisTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Dashboard Delete Org', code='dashboard-delete-org')
        self.user = User.objects.create_user(
            email='admin@delete.test',
            password='testpass123',
            first_name='Delete',
            last_name='Admin',
            role=UserRole.SCHOOL_ADMIN,
            organization=self.organization,
            is_staff=True,
        )
        self.client.force_login(self.user)

        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term='term_1',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 30),
            is_current=True,
        )
        self.student = Student.objects.create(
            organization=self.organization,
            admission_number='DEL001',
            admission_date=date(2026, 1, 5),
            first_name='Delete',
            last_name='Case',
            gender='M',
            date_of_birth=date(2016, 5, 20),
            status='active',
        )

    def _create_invoice(self, number='INV-DEL-001', amount=Decimal('1000.00')):
        invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number=number,
            student=self.student,
            term=self.term,
            subtotal=amount,
            total_amount=amount,
            balance=amount,
            issue_date=self.term.start_date,
            due_date=self.term.end_date,
            generated_by=self.user,
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description='Tuition',
            category='tuition',
            amount=amount,
            net_amount=amount,
        )
        invoice.refresh_from_db()
        return invoice

    def _create_payment(self, invoice, amount=Decimal('400.00')):
        payment = Payment.objects.create(
            organization=self.organization,
            student=self.student,
            invoice=invoice,
            amount=amount,
            payment_method='cash',
            payment_source='manual',
            status='completed',
            payment_reference='PAY-DEL-001',
            receipt_number='RCP-DEL-001',
            received_by=self.user,
            payment_date=timezone.now(),
            is_active=True,
        )
        PaymentAllocation.objects.create(
            payment=payment,
            invoice_item=invoice.items.first(),
            amount=amount,
            is_active=True,
        )
        invoice.amount_paid = amount
        invoice.balance = invoice.total_amount - amount
        invoice.status = 'partially_paid'
        invoice.save(update_fields=['amount_paid', 'balance', 'status', 'updated_at'])
        return payment

    def test_deleting_invoice_reduces_dashboard_billed(self):
        invoice = self._create_invoice(amount=Decimal('1000.00'))

        before = _finance_kpis(term=self.term, organization=self.organization)
        self.assertEqual(before['term_stats']['billed'], Decimal('1000.00'))

        response = self.client.post(reverse('finance:invoice_delete', args=[invoice.pk]))
        self.assertEqual(response.status_code, 302)

        after = _finance_kpis(term=self.term, organization=self.organization)
        self.assertEqual(after['term_stats']['billed'], Decimal('0'))

    def test_deleting_payment_reduces_dashboard_collected_without_error(self):
        invoice = self._create_invoice(amount=Decimal('1000.00'))
        payment = self._create_payment(invoice, amount=Decimal('400.00'))

        before = _finance_kpis(term=self.term, organization=self.organization)
        self.assertEqual(before['term_stats']['collected'], Decimal('400.00'))

        response = self.client.post(
            reverse('finance:payment_delete', args=[payment.pk]),
            HTTP_REFERER=reverse('finance:payment_detail', args=[payment.pk]),
        )
        self.assertEqual(response.status_code, 302)

        after = _finance_kpis(term=self.term, organization=self.organization)
        self.assertEqual(after['term_stats']['collected'], Decimal('0'))

        payment.refresh_from_db()
        self.assertFalse(payment.is_active)
