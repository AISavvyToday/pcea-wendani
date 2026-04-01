from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum, Q

from core.models import Organization, TermChoices, FeeCategory, PaymentStatus
from finance.models import Invoice, InvoiceItem
from finance.services_kpi import build_term_kpis
from payments.models import PaymentAllocation
from portal.views import _finance_kpis, _get_current_term
from reports.report_utils import calculate_invoice_billed_collected_outstanding


class Command(BaseCommand):
    help = 'Compare dashboard billed/collected vs invoice reports for active students only'

    def add_arguments(self, parser):
        parser.add_argument('--org-name', default='PCEA Wendani Academy')

    def handle(self, *args, **options):
        org = Organization.objects.get(name=options['org_name'])
        term = _get_current_term(organization=org)
        self.stdout.write(f'Organization: {org.name}')
        self.stdout.write(f'Term: {term}')

        dashboard = _finance_kpis(term=term, organization=org)['current_term']
        self.stdout.write('\n=== DASHBOARD CURRENT TERM ===')
        self.stdout.write(f"dashboard.billed={dashboard['billed']}")
        self.stdout.write(f"dashboard.collected={dashboard['collected']}")
        self.stdout.write(f"dashboard.outstanding={dashboard['outstanding']}")
        self.stdout.write(f"dashboard.balance_bf={dashboard['balances_bf']}")
        self.stdout.write(f"dashboard.prepayments={dashboard['prepayments']}")
        self.stdout.write(f"dashboard.billed_breakdown={dashboard.get('billed_breakdown')}")
        self.stdout.write(f"dashboard.collected_breakdown={dashboard.get('collected_breakdown')}")

        invoices = Invoice.objects.filter(
            is_active=True,
            organization=org,
            term=term,
            student__status='active',
        ).exclude(status='cancelled')

        items = InvoiceItem.objects.filter(invoice__in=invoices, is_active=True)
        calc = calculate_invoice_billed_collected_outstanding(
            invoices_qs=invoices,
            mode='summary',
            items_qs=items,
        )
        self.stdout.write('\n=== REPORT SUMMARY BASIS (ALL CATEGORIES) ===')
        self.stdout.write(f"report.total_billed={calc['totals']['total_billed']}")
        self.stdout.write(f"report.total_collected={calc['totals']['total_collected']}")
        self.stdout.write(f"report.total_outstanding={calc['totals']['total_outstanding']}")
        self.stdout.write(f"report.billed_map={calc['billed_map']}")
        self.stdout.write(f"report.collected_map={calc['collected_map']}")

        fee_categories = [
            FeeCategory.TUITION,
            FeeCategory.MEALS,
            FeeCategory.EXAMINATION,
            'assessment',
            FeeCategory.ACTIVITY,
        ]
        fees_items = items.filter(category__in=fee_categories)
        fees_alloc = PaymentAllocation.objects.filter(
            invoice_item__in=fees_items,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        fees_billed = fees_items.aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

        transport_items = items.filter(category=FeeCategory.TRANSPORT)
        transport_alloc = PaymentAllocation.objects.filter(
            invoice_item__in=transport_items,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        transport_billed = transport_items.aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

        admission_items = items.filter(category=FeeCategory.ADMISSION)
        admission_alloc = PaymentAllocation.objects.filter(
            invoice_item__in=admission_items,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        admission_billed = admission_items.aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

        edu_items = items.filter(category=FeeCategory.OTHER)
        edu_alloc = PaymentAllocation.objects.filter(
            invoice_item__in=edu_items,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        edu_billed = edu_items.aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

        amount_paid_total = invoices.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        balance_bf_total = invoices.aggregate(total=Sum('balance_bf'))['total'] or Decimal('0.00')
        prepayment_total = invoices.aggregate(total=Sum('prepayment'))['total'] or Decimal('0.00')

        self.stdout.write('\n=== REPORT BASIS BY BUCKET ===')
        self.stdout.write(f'fees billed={fees_billed} collected={fees_alloc}')
        self.stdout.write(f'transport billed={transport_billed} collected={transport_alloc}')
        self.stdout.write(f'admission billed={admission_billed} collected={admission_alloc}')
        self.stdout.write(f'educational_activities billed={edu_billed} collected={edu_alloc}')
        self.stdout.write(f'invoices.amount_paid total={amount_paid_total}')
        self.stdout.write(f'invoices.balance_bf total={balance_bf_total}')
        self.stdout.write(f'invoices.prepayment total={prepayment_total}')

        kpis = build_term_kpis(term=term, organization=org)
        self.stdout.write('\n=== KPI SERVICE BUCKETS ===')
        self.stdout.write(str(kpis))
