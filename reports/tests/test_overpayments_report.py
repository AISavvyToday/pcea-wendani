from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from academics.models import AcademicYear, Class, Term
from core.models import (
    Gender,
    GradeLevel,
    Organization,
    PaymentSource,
    PaymentStatus,
    StreamChoices,
    TermChoices,
)
from finance.models import Invoice
from payments.models import Payment
from reports.report_utils import build_overpayments_report_data
from students.models import Student


class OverpaymentsReportDataTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='PCEA Wendani Academy', code='PWA')
        self.other_organization = Organization.objects.create(name='Other Academy', code='OTHER')
        self.user = get_user_model().objects.create_user(
            email='overpayments@example.com',
            password='password123',
            organization=self.organization,
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
        self.student_class = Class.objects.create(
            organization=self.organization,
            name='Grade 4 East',
            grade_level=GradeLevel.GRADE_4,
            stream=StreamChoices.EAST,
            academic_year=self.academic_year,
        )

    def _student(self, admission_number, *, organization=None, credit_balance=Decimal('0.00')):
        organization = organization or self.organization
        student = Student.objects.create(
            organization=organization,
            admission_number=admission_number,
            admission_date=date(2026, 1, 8),
            first_name='Over',
            last_name=admission_number,
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 5, 1),
            current_class=self.student_class if organization == self.organization else None,
            status='active',
            credit_balance=credit_balance,
            outstanding_balance=Decimal('0.00'),
        )
        if credit_balance:
            Student.objects.filter(pk=student.pk).update(credit_balance=credit_balance)
            student.refresh_from_db()
        return student

    def _invoice(self, student, total):
        return Invoice.objects.create(
            organization=student.organization,
            invoice_number=f'INV-{student.admission_number}',
            student=student,
            term=self.term,
            subtotal=total,
            total_amount=total,
            balance=Decimal('0.00'),
            issue_date=self.term.start_date,
            due_date=self.term.end_date,
        )

    def _payment(self, student, invoice, amount, paid_at):
        return Payment.objects.create(
            organization=student.organization,
            student=student,
            invoice=invoice,
            amount=amount,
            payment_method='bank_deposit',
            payment_source=PaymentSource.COOP_BANK,
            status=PaymentStatus.COMPLETED,
            payment_reference=f'PAY-{student.admission_number}-{amount}',
            receipt_number=f'RCP-{student.admission_number}-{amount}',
            received_by=self.user,
            payment_date=timezone.make_aware(datetime.combine(paid_at, datetime.min.time())),
            is_active=True,
        )

    def test_overpayments_report_totals_are_org_scoped(self):
        student_one = self._student('PWA1001', credit_balance=Decimal('100.00'))
        student_two = self._student('PWA1002', credit_balance=Decimal('50.00'))
        other_student = self._student(
            'OTH1001',
            organization=self.other_organization,
            credit_balance=Decimal('999.00'),
        )
        invoice_one = self._invoice(student_one, Decimal('1000.00'))
        invoice_two = self._invoice(student_two, Decimal('500.00'))
        self._invoice(other_student, Decimal('999.00'))
        self._payment(student_one, invoice_one, Decimal('1100.00'), date(2026, 1, 20))
        self._payment(student_two, invoice_two, Decimal('550.00'), date(2026, 2, 15))

        data = build_overpayments_report_data(organization=self.organization)

        self.assertEqual(data['totals']['student_count'], 2)
        self.assertEqual(data['totals']['total_overpayments'], Decimal('150.00'))
        self.assertEqual(
            [row['student__admission_number'] for row in data['rows']],
            ['PWA1001', 'PWA1002'],
        )

    def test_overpayments_report_filters_by_search_and_payment_date(self):
        student_one = self._student('PWA2001', credit_balance=Decimal('100.00'))
        student_two = self._student('PWA2002', credit_balance=Decimal('50.00'))
        invoice_one = self._invoice(student_one, Decimal('1000.00'))
        invoice_two = self._invoice(student_two, Decimal('500.00'))
        self._payment(student_one, invoice_one, Decimal('1100.00'), date(2026, 1, 20))
        self._payment(student_two, invoice_two, Decimal('550.00'), date(2026, 2, 15))

        by_search = build_overpayments_report_data(
            organization=self.organization,
            student_search='2002',
        )
        by_date = build_overpayments_report_data(
            organization=self.organization,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(by_search['totals']['total_overpayments'], Decimal('50.00'))
        self.assertEqual(by_search['rows'][0]['student__admission_number'], 'PWA2002')
        self.assertEqual(by_date['totals']['total_overpayments'], Decimal('100.00'))
        self.assertEqual(by_date['rows'][0]['student__admission_number'], 'PWA2001')
