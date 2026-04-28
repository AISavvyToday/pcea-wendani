from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academics.models import AcademicYear, Term
from core.models import Organization
from core.models import TermChoices, UserRole
from other_income.models import OtherIncomeInvoice, OtherIncomeItem, OtherIncomePayment
from other_income.reporting import (
    OtherIncomeReportFilters,
    build_other_income_report_dataset,
    build_other_income_report_inventory,
)


class OtherIncomeReportingTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='PCEA Wendani Academy',
            code='WENDANI',
        )
        self.user = User.objects.create_user(
            email='other-income@example.com',
            password='password123',
            first_name='Other',
            last_name='Income',
            role=UserRole.ACCOUNTANT,
            organization=self.organization,
        )
        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=True,
        )
        self.term_1 = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term=TermChoices.TERM_1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 30),
            is_current=False,
        )
        self.term_2 = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term=TermChoices.TERM_2,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )

        self.invoice = OtherIncomeInvoice.objects.create(
            organization=self.organization,
            invoice_number='OINV-2026-TERM2',
            client_name='Community Hall Hire',
            client_contact='0700000000',
            description='Weekend venue booking',
            status='unpaid',
            issue_date=date(2026, 5, 10),
            due_date=date(2026, 5, 17),
        )
        OtherIncomeItem.objects.create(
            invoice=self.invoice,
            description='Hall hire',
            amount=Decimal('15000.00'),
        )
        OtherIncomeItem.objects.create(
            invoice=self.invoice,
            description='Cleaning fee',
            amount=Decimal('2500.00'),
        )
        self.invoice.recalc_totals()
        self.invoice.save(update_fields=['subtotal', 'total_amount', 'balance', 'updated_at'])

        self.payment = OtherIncomePayment.objects.create(
            payment_reference='OAP-TERM2',
            invoice=self.invoice,
            amount=Decimal('5000.00'),
            payment_method='bank_transfer',
            payer_name='John Client',
            transaction_reference='BANK-123',
            payment_date=timezone.make_aware(datetime(2026, 5, 12, 9, 30)),
        )

        self.old_invoice = OtherIncomeInvoice.objects.create(
            organization=self.organization,
            invoice_number='OINV-2026-TERM1',
            client_name='School Van Hire',
            client_contact='0711111111',
            description='Previous term trip',
            status='paid',
            issue_date=date(2026, 2, 15),
            due_date=date(2026, 2, 22),
        )
        OtherIncomeItem.objects.create(
            invoice=self.old_invoice,
            description='Van hire',
            amount=Decimal('9000.00'),
        )
        self.old_invoice.recalc_totals()
        self.old_invoice.save(update_fields=['subtotal', 'total_amount', 'balance', 'updated_at'])
        self.old_payment = OtherIncomePayment.objects.create(
            payment_reference='OAP-TERM1',
            invoice=self.old_invoice,
            amount=Decimal('9000.00'),
            payment_method='cash',
            payer_name='Previous Client',
            transaction_reference='CASH-123',
            payment_date=timezone.make_aware(datetime(2026, 2, 16, 11, 0)),
        )

    def test_report_dataset_includes_header_items_and_payment_history(self):
        rows = build_other_income_report_dataset(organization=self.organization)

        self.assertEqual(len(rows), 2)
        row = rows[0]
        self.assertEqual(row['invoice']['client_name'], 'Community Hall Hire')
        self.assertEqual(row['invoice']['balance'], Decimal('12500.00'))
        self.assertEqual(len(row['line_items']), 2)
        self.assertEqual(len(row['payment_history']), 1)
        self.assertEqual(row['payment_history'][0]['payment_reference'], self.payment.payment_reference)
        self.assertEqual(row['dimensions']['payment_methods'], ['bank_transfer'])

    def test_report_inventory_and_filters_share_same_pipeline(self):
        future_filter = OtherIncomeReportFilters(
            payment_method='mobile_money',
            issue_date_from=timezone.localdate() + timedelta(days=1),
        )
        empty_inventory = build_other_income_report_inventory(
            organization=self.organization,
            filters=future_filter,
        )
        self.assertEqual(empty_inventory['counts']['invoice_count'], 0)

        matching_filter = OtherIncomeReportFilters(
            payment_method='bank_transfer',
            term=self.term_2,
        )
        inventory = build_other_income_report_inventory(
            organization=self.organization,
            filters=matching_filter,
        )

        self.assertEqual(inventory['counts']['invoice_count'], 1)
        self.assertEqual(inventory['counts']['line_item_count'], 2)
        self.assertEqual(inventory['counts']['payment_count'], 1)
        self.assertIn('bank_transfer', inventory['payment_methods'])

    def test_report_filters_can_scope_by_academic_year_or_term(self):
        term_rows = build_other_income_report_dataset(
            organization=self.organization,
            filters=OtherIncomeReportFilters(term=self.term_2),
        )
        academic_year_rows = build_other_income_report_dataset(
            organization=self.organization,
            filters=OtherIncomeReportFilters(academic_year=self.academic_year),
        )

        self.assertEqual([row['invoice']['invoice_number'] for row in term_rows], ['OINV-2026-TERM2'])
        self.assertEqual(len(academic_year_rows), 2)

    def test_list_view_filters_invoice_and_payment_tabs_by_term(self):
        self.client.force_login(self.user)

        invoice_response = self.client.get(
            reverse('other_income:invoice_list'),
            {'tab': 'invoices', 'term': self.term_2.pk},
        )
        payment_response = self.client.get(
            reverse('other_income:invoice_list'),
            {'tab': 'payments', 'term': self.term_2.pk},
        )

        self.assertContains(invoice_response, 'Community Hall Hire')
        self.assertNotContains(invoice_response, 'School Van Hire')
        self.assertContains(payment_response, 'OAP-TERM2')
        self.assertNotContains(payment_response, 'OAP-TERM1')
