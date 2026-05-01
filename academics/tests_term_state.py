from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from academics.models import AcademicYear, Term, TermTransitionLog
from academics.services.term_state import activate_term_for_org, recalculate_term_invoices
from core.models import InvoiceStatus
from core.models import Gender, Organization, TermChoices, UserRole
from finance.models import Invoice, InvoiceItem
from students.models import Student


class TermActivationServiceTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='PCEA Wendani Academy', code='PCEA_WENDANI')
        self.user = User.objects.create_user(
            email='term-admin@example.com',
            password='password123',
            first_name='Term',
            last_name='Admin',
            role=UserRole.SCHOOL_ADMIN,
            organization=self.organization,
        )
        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=True,
        )
        self.term1 = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term=TermChoices.TERM_1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 30),
            is_current=True,
        )
        self.term2 = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term=TermChoices.TERM_2,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 8, 31),
            is_current=False,
        )
        self.student = Student.objects.create(
            organization=self.organization,
            admission_number='PWA/T001',
            admission_date=date(2025, 1, 10),
            first_name='Balance',
            last_name='Student',
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 5, 1),
            status='active',
        )
        Invoice.objects.create(
            organization=self.organization,
            invoice_number='INV-TERM-001',
            student=self.student,
            term=self.term1,
            subtotal=Decimal('1000.00'),
            total_amount=Decimal('1000.00'),
            amount_paid=Decimal('250.00'),
            issue_date=self.term1.start_date,
            due_date=self.term1.end_date,
        )

    def test_forward_activation_transitions_balances_once(self):
        stats = activate_term_for_org(
            organization=self.organization,
            term=self.term2,
            previous_term=self.term1,
            transition=True,
            user=self.user,
        )

        self.term1.refresh_from_db()
        self.term2.refresh_from_db()
        self.student.refresh_from_db()

        self.assertFalse(self.term1.is_current)
        self.assertTrue(self.term2.is_current)
        self.assertEqual(self.student.balance_bf_original, Decimal('750.00'))
        self.assertEqual(TermTransitionLog.objects.count(), 1)
        self.assertFalse(stats['transition_skipped'])

        self.student.balance_bf_original = Decimal('123.00')
        self.student.save(update_fields=['balance_bf_original'])

        second_stats = activate_term_for_org(
            organization=self.organization,
            term=self.term2,
            previous_term=self.term1,
            transition=True,
            user=self.user,
        )
        self.student.refresh_from_db()

        self.assertEqual(TermTransitionLog.objects.count(), 1)
        self.assertEqual(self.student.balance_bf_original, Decimal('123.00'))
        self.assertTrue(second_stats['transition_already_logged'])

    def test_forward_activation_skips_when_new_term_finance_state_already_exists(self):
        Invoice.objects.create(
            organization=self.organization,
            invoice_number='INV-TERM-002',
            student=self.student,
            term=self.term2,
            subtotal=Decimal('1000.00'),
            total_amount=Decimal('1000.00'),
            amount_paid=Decimal('0.00'),
            balance_bf=Decimal('750.00'),
            balance=Decimal('1750.00'),
            status=InvoiceStatus.OVERDUE,
            issue_date=self.term2.start_date,
            due_date=self.term2.end_date,
        )

        stats = activate_term_for_org(
            organization=self.organization,
            term=self.term2,
            previous_term=self.term1,
            transition=True,
            user=self.user,
        )
        self.student.refresh_from_db()

        self.assertEqual(self.student.balance_bf_original, Decimal('0.00'))
        self.assertTrue(stats['transition_already_materialized'])
        self.assertEqual(TermTransitionLog.objects.count(), 1)
        self.assertEqual(
            TermTransitionLog.objects.first().stats['skipped'],
            'new_term_already_has_finance_state',
        )

    def test_recalculate_term_invoices_rebuilds_header_from_items(self):
        invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number='INV-TERM-003',
            student=self.student,
            term=self.term2,
            subtotal=Decimal('1000.00'),
            discount_amount=Decimal('500.00'),
            total_amount=Decimal('500.00'),
            amount_paid=Decimal('0.00'),
            balance=Decimal('500.00'),
            status=InvoiceStatus.PAID,
            issue_date=self.term2.start_date,
            due_date=self.term2.end_date,
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description='Tuition',
            category='tuition',
            amount=Decimal('1500.00'),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            description='Transport',
            category='transport',
            amount=Decimal('500.00'),
        )

        stats = recalculate_term_invoices(
            self.term2,
            organization=self.organization,
        )
        invoice.refresh_from_db()

        self.assertEqual(invoice.subtotal, Decimal('2000.00'))
        self.assertEqual(invoice.discount_amount, Decimal('500.00'))
        self.assertEqual(invoice.total_amount, Decimal('1500.00'))
        self.assertEqual(invoice.balance, Decimal('1500.00'))
        self.assertEqual(invoice.status, InvoiceStatus.OVERDUE)
        self.assertEqual(stats['header_changed'], 1)
        self.assertEqual(stats['item_discounts_changed'], 2)
