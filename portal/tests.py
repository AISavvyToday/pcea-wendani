from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academics.models import AcademicYear, Term
from core.models import Gender, Organization, PaymentStatus, TermChoices, UserRole
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from portal.views import _finance_kpis
from students.models import Student


class DashboardStudentCounterSyncTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Counter Org', code='counter-org')
        self.other_organization = Organization.objects.create(name='Other Org', code='other-org')

        self.user = User.objects.create_user(
            email='admin@example.com',
            password='password123',
            first_name='Admin',
            last_name='User',
            role=UserRole.SCHOOL_ADMIN,
            organization=self.organization,
            is_staff=True,
        )

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
            term=TermChoices.TERM_1,
            start_date=date(2026, 1, 6),
            end_date=date(2026, 4, 4),
            is_current=True,
        )

        Student.objects.create(
            organization=self.organization,
            admission_number='ADM001',
            admission_date=date(2026, 1, 10),
            first_name='New',
            last_name='Active',
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 5, 1),
            status='active',
        )
        Student.objects.create(
            organization=self.organization,
            admission_number='ADM002',
            admission_date=date(2025, 9, 10),
            first_name='Existing',
            last_name='Active',
            gender=Gender.MALE,
            date_of_birth=date(2015, 7, 1),
            status='active',
        )
        Student.objects.create(
            organization=self.organization,
            admission_number='ADM003',
            admission_date=date(2025, 5, 1),
            first_name='Grad',
            last_name='Student',
            gender=Gender.FEMALE,
            date_of_birth=date(2014, 6, 1),
            status='graduated',
        )
        Student.objects.create(
            organization=self.organization,
            admission_number='ADM004',
            admission_date=date(2025, 6, 1),
            first_name='Transfer',
            last_name='Student',
            gender=Gender.MALE,
            date_of_birth=date(2014, 8, 1),
            status='transferred',
        )
        Student.objects.create(
            organization=self.other_organization,
            admission_number='ADM999',
            admission_date=date(2026, 1, 12),
            first_name='Ignored',
            last_name='Student',
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 9, 1),
            status='active',
        )

    def test_dashboard_student_card_matches_student_list_counters(self):
        self.client.force_login(self.user)

        dashboard_response = self.client.get(reverse('portal:dashboard_admin'))
        students_response = self.client.get(reverse('students:list'))

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(students_response.status_code, 200)

        student_card = next(
            card for card in dashboard_response.context['stat_cards']
            if card['title'] == 'Total Students(Active only)'
        )
        status_counts = students_response.context['status_counts']

        self.assertEqual(int(student_card['value'].replace(',', '')), status_counts['active'])
        self.assertIn(f"New-{status_counts['new']}", student_card['helper_lines'])
        self.assertIn(
            f"Graduated-{status_counts['graduated']}, Transferred-{status_counts['transferred']}",
            student_card['helper_lines'],
        )


class DashboardFinanceKpiAlignmentTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='PCEA Wendani Academy', code='PCEA_WENDANI')
        self.other_organization = Organization.objects.create(name='Other Academy', code='OTHER')

        self.user = User.objects.create_user(
            email='finance-admin@example.com',
            password='password123',
            first_name='Finance',
            last_name='Admin',
            role=UserRole.SCHOOL_ADMIN,
            organization=self.organization,
            is_staff=True,
        )

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
            term=TermChoices.TERM_1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            is_current=True,
        )

    def _student(
        self,
        admission_number,
        *,
        organization=None,
        status='active',
        credit_balance=Decimal('0.00'),
        balance_bf_original=Decimal('0.00'),
        prepayment_original=Decimal('0.00'),
        outstanding_balance=Decimal('0.00'),
    ):
        organization = organization or self.organization
        student = Student.objects.create(
            organization=organization,
            admission_number=admission_number,
            admission_date=date(2026, 1, 5),
            first_name='Kpi',
            last_name=admission_number,
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 5, 1),
            status=status,
            credit_balance=credit_balance,
            balance_bf_original=balance_bf_original,
            prepayment_original=prepayment_original,
            outstanding_balance=outstanding_balance,
        )
        if credit_balance:
            Student.objects.filter(pk=student.pk).update(credit_balance=credit_balance)
            student.refresh_from_db()
        return student

    def _invoice(
        self,
        student,
        number,
        *,
        term=None,
        organization=None,
        subtotal=Decimal('0.00'),
        item_amount=Decimal('0.00'),
    ):
        term = term or self.term
        organization = organization or self.organization
        invoice = Invoice.objects.create(
            organization=organization,
            invoice_number=number,
            student=student,
            term=term,
            subtotal=subtotal,
            total_amount=subtotal,
            balance=subtotal,
            issue_date=term.start_date,
            due_date=term.end_date,
            generated_by=self.user,
        )
        item = InvoiceItem.objects.create(
            invoice=invoice,
            description='Tuition',
            category='tuition',
            amount=item_amount,
            net_amount=item_amount,
        )
        return invoice, item

    def _payment(self, student, invoice, item, number, amount):
        payment = Payment.objects.create(
            organization=invoice.organization,
            student=student,
            invoice=invoice,
            amount=amount,
            payment_method='bank_deposit',
            payment_source='coop_bank',
            status=PaymentStatus.COMPLETED,
            payment_reference=f'PAY-{number}',
            receipt_number=f'RCP-{number}',
            received_by=self.user,
            payment_date=timezone.now(),
            is_active=True,
        )
        PaymentAllocation.objects.create(
            payment=payment,
            invoice_item=item,
            amount=amount,
            is_active=True,
        )
        return payment

    def test_billed_uses_item_net_totals_not_invoice_subtotal(self):
        student = self._student('KPI001')
        self._invoice(
            student,
            'INV-KPI-001',
            subtotal=Decimal('1100.00'),
            item_amount=Decimal('1000.00'),
        )

        stats = _finance_kpis(term=self.term, organization=self.organization)['term_stats']

        self.assertEqual(stats['billed'], Decimal('1000.00'))
        self.assertEqual(stats['billed_breakdown']['fees'], Decimal('1000.00'))

    def test_collected_includes_transferred_student_allocations_for_same_org_only(self):
        transferred = self._student('KPI002', status='transferred')
        invoice, item = self._invoice(
            transferred,
            'INV-KPI-002',
            subtotal=Decimal('500.00'),
            item_amount=Decimal('500.00'),
        )
        self._payment(transferred, invoice, item, 'KPI-002', Decimal('400.00'))

        other_student = self._student('KPI999', organization=self.other_organization, status='transferred')
        other_invoice, other_item = self._invoice(
            other_student,
            'INV-KPI-999',
            organization=self.other_organization,
            subtotal=Decimal('300.00'),
            item_amount=Decimal('300.00'),
        )
        self._payment(other_student, other_invoice, other_item, 'KPI-999', Decimal('250.00'))

        stats = _finance_kpis(term=self.term, organization=self.organization)['term_stats']

        self.assertEqual(stats['collected'], Decimal('400.00'))
        self.assertEqual(stats['collected_breakdown']['fees'], Decimal('400.00'))

    def test_collected_does_not_add_current_credit_overpayments(self):
        student = self._student('KPI003', credit_balance=Decimal('500.00'))
        invoice, item = self._invoice(
            student,
            'INV-KPI-003',
            subtotal=Decimal('300.00'),
            item_amount=Decimal('300.00'),
        )
        self._payment(student, invoice, item, 'KPI-003', Decimal('300.00'))

        stats = _finance_kpis(term=self.term, organization=self.organization)['term_stats']

        self.assertEqual(stats['collected'], Decimal('300.00'))
        self.assertEqual(stats['prepayments_breakdown']['current_credit'], Decimal('500.00'))
        self.assertNotIn('overpayments', stats['collected_breakdown'])

    def test_balances_bf_and_prepayments_show_before_new_term_invoices_exist(self):
        self._student(
            'KPI004',
            balance_bf_original=Decimal('750.00'),
            prepayment_original=Decimal('125.00'),
            outstanding_balance=Decimal('750.00'),
        )

        stats = _finance_kpis(term=self.term, organization=self.organization)['term_stats']

        self.assertEqual(stats['invoice_count'], 0)
        self.assertEqual(stats['balances_bf'], Decimal('750.00'))
        self.assertEqual(stats['balance_bf_breakdown']['total'], Decimal('750.00'))
        self.assertEqual(stats['balance_bf_breakdown']['cleared'], Decimal('0.00'))
        self.assertEqual(stats['balance_bf_breakdown']['uncleared'], Decimal('750.00'))
        self.assertEqual(stats['prepayments'], Decimal('125.00'))
        self.assertEqual(stats['prepayments_breakdown']['total'], Decimal('125.00'))
        self.assertEqual(stats['prepayments_breakdown']['consumed'], Decimal('0'))
        self.assertEqual(stats['prepayments_breakdown']['unconsumed'], Decimal('125.00'))
