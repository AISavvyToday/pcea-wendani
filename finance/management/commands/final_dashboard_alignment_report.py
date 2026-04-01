from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import Organization, PaymentStatus
from finance.models import Invoice, InvoiceItem
from other_income.models import OtherIncomeInvoice
from payments.models import PaymentAllocation
from portal.views import _get_current_term, _get_active_students_qs
from finance.services_kpi import build_term_kpis


class Command(BaseCommand):
    help = 'Final dashboard vs reports alignment proof table'

    def add_arguments(self, parser):
        parser.add_argument('--org-name', default='PCEA Wendani Academy')

    def handle(self, *args, **options):
        org = Organization.objects.get(name=options['org_name'])
        term = _get_current_term(organization=org)
        active_students = _get_active_students_qs(organization=org)

        invoices = Invoice.objects.filter(
            is_active=True,
            organization=org,
            term=term,
            student__status='active',
        ).exclude(status='cancelled')

        items = InvoiceItem.objects.filter(invoice__in=invoices, is_active=True)
        allocs = PaymentAllocation.objects.filter(
            invoice_item__in=items,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED,
        )

        billed_map = {row['category']: row['total'] or Decimal('0.00') for row in items.values('category').annotate(total=Sum('net_amount'))}
        collected_map = {row['invoice_item__category']: row['total'] or Decimal('0.00') for row in allocs.values('invoice_item__category').annotate(total=Sum('amount'))}

        fees_categories = ['tuition', 'meals', 'activity', 'examination', 'assessment']
        report_fees_billed = sum((billed_map.get(cat, Decimal('0.00')) for cat in fees_categories), Decimal('0.00'))
        report_fees_collected = sum((collected_map.get(cat, Decimal('0.00')) for cat in fees_categories), Decimal('0.00'))
        report_transport_billed = billed_map.get('transport', Decimal('0.00'))
        report_transport_collected = collected_map.get('transport', Decimal('0.00'))
        report_admission_billed = billed_map.get('admission', Decimal('0.00'))
        report_admission_collected = collected_map.get('admission', Decimal('0.00'))
        report_edu_billed = billed_map.get('other', Decimal('0.00'))
        report_edu_collected = collected_map.get('other', Decimal('0.00'))
        report_balance_bf = active_students.aggregate(total=Sum('balance_bf_original'))['total'] or Decimal('0.00')
        report_prepayments = active_students.aggregate(total=Sum('prepayment_original'))['total'] or Decimal('0.00')
        report_overpayments = active_students.aggregate(total=Sum('credit_balance'))['total'] or Decimal('0.00')
        report_outstanding = active_students.aggregate(total=Sum('outstanding_balance'))['total'] or Decimal('0.00')

        other_income = OtherIncomeInvoice.objects.filter(
            is_active=True,
            organization=org,
            issue_date__gte=term.start_date,
            issue_date__lte=term.end_date,
        ).exclude(status='cancelled')
        report_other_income_billed = other_income.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        report_other_income_collected = other_income.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

        kpi = build_term_kpis(term=term, organization=org)
        buckets = kpi['buckets']

        dashboard_fees_billed = buckets['fees']['billed']
        dashboard_fees_collected = buckets['fees']['collected']
        dashboard_transport_billed = buckets['transport']['billed']
        dashboard_transport_collected = buckets['transport']['collected']
        dashboard_admission_billed = buckets['admission']['billed']
        dashboard_admission_collected = buckets['admission']['collected']
        dashboard_edu_billed = buckets['educational_activities']['billed']
        dashboard_edu_collected = buckets['educational_activities']['collected']
        dashboard_other_income_billed = buckets['other_income']['billed']
        dashboard_other_income_collected = buckets['other_income']['collected']
        dashboard_balance_bf = report_balance_bf
        dashboard_prepayments = report_prepayments
        dashboard_overpayments = report_overpayments
        dashboard_outstanding = report_outstanding
        dashboard_collected_total = (
            dashboard_fees_collected + dashboard_transport_collected + dashboard_admission_collected +
            dashboard_edu_collected + dashboard_other_income_collected + dashboard_overpayments
        )
        report_collected_total = (
            report_fees_collected + report_transport_collected + report_admission_collected +
            report_edu_collected + report_other_income_collected + report_overpayments
        )
        dashboard_billed_total = (
            dashboard_fees_billed + dashboard_transport_billed + dashboard_admission_billed +
            dashboard_edu_billed + dashboard_other_income_billed
        )
        report_billed_total = (
            report_fees_billed + report_transport_billed + report_admission_billed +
            report_edu_billed + report_other_income_billed
        )

        rows = [
            ('Fees Billed', dashboard_fees_billed, report_fees_billed),
            ('Fees Collected', dashboard_fees_collected, report_fees_collected),
            ('Transport Billed', dashboard_transport_billed, report_transport_billed),
            ('Transport Collected', dashboard_transport_collected, report_transport_collected),
            ('Admission Billed', dashboard_admission_billed, report_admission_billed),
            ('Admission Collected', dashboard_admission_collected, report_admission_collected),
            ('Educational Activities Billed', dashboard_edu_billed, report_edu_billed),
            ('Educational Activities Collected', dashboard_edu_collected, report_edu_collected),
            ('Other Income Billed', dashboard_other_income_billed, report_other_income_billed),
            ('Other Income Collected', dashboard_other_income_collected, report_other_income_collected),
            ('Balance B/F', dashboard_balance_bf, report_balance_bf),
            ('Total Prepayments', dashboard_prepayments, report_prepayments),
            ('Overpayments', dashboard_overpayments, report_overpayments),
            ('Outstanding', dashboard_outstanding, report_outstanding),
            ('Total Billed Card', dashboard_billed_total, report_billed_total),
            ('Total Collected Card', dashboard_collected_total, report_collected_total),
        ]

        self.stdout.write('Metric | Dashboard | Expected/Report | Delta')
        self.stdout.write('-' * 90)
        for label, dashboard_val, report_val in rows:
            delta = dashboard_val - report_val
            self.stdout.write(f'{label} | {dashboard_val} | {report_val} | {delta}')
