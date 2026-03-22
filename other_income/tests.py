from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Organization
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

        self.invoice = OtherIncomeInvoice.objects.create(
            organization=self.organization,
            client_name='Community Hall Hire',
            client_contact='0700000000',
            description='Weekend venue booking',
            status='unpaid',
            issue_date=timezone.localdate(),
            due_date=timezone.localdate() + timedelta(days=7),
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
            invoice=self.invoice,
            amount=Decimal('5000.00'),
            payment_method='bank_transfer',
            payer_name='John Client',
            transaction_reference='BANK-123',
            payment_date=timezone.now(),
        )

    def test_report_dataset_includes_header_items_and_payment_history(self):
        rows = build_other_income_report_dataset(organization=self.organization)

        self.assertEqual(len(rows), 1)
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
            issue_date_from=timezone.localdate() - timedelta(days=1),
        )
        inventory = build_other_income_report_inventory(
            organization=self.organization,
            filters=matching_filter,
        )

        self.assertEqual(inventory['counts']['invoice_count'], 1)
        self.assertEqual(inventory['counts']['line_item_count'], 2)
        self.assertEqual(inventory['counts']['payment_count'], 1)
        self.assertIn('bank_transfer', inventory['payment_methods'])
