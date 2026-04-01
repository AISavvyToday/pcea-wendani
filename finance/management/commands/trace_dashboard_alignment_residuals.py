from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import Organization, PaymentStatus
from finance.models import Invoice, InvoiceItem
from payments.models import PaymentAllocation
from portal.views import _get_current_term


class Command(BaseCommand):
    help = 'Trace residual dashboard/report deltas to exact items and allocations'

    def add_arguments(self, parser):
        parser.add_argument('--org-name', default='PCEA Wendani Academy')

    def handle(self, *args, **options):
        org = Organization.objects.get(name=options['org_name'])
        term = _get_current_term(organization=org)

        report_invoices = Invoice.objects.filter(
            is_active=True,
            organization=org,
            term=term,
            student__status='active',
        ).exclude(status='cancelled')

        kpi_items = InvoiceItem.objects.filter(
            is_active=True,
            invoice__is_active=True,
            invoice__student__is_active=True,
            invoice__student__status='active',
            invoice__organization=org,
            invoice__term=term,
        ).exclude(invoice__status='cancelled')

        report_items = InvoiceItem.objects.filter(invoice__in=report_invoices, is_active=True)

        self.stdout.write('=== BILLED CATEGORY DIFFS: KPI minus REPORT ===')
        categories = sorted(set(report_items.values_list('category', flat=True)) | set(kpi_items.values_list('category', flat=True)))
        for category in categories:
            report_total = report_items.filter(category=category).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')
            kpi_total = kpi_items.filter(category=category).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')
            delta = kpi_total - report_total
            if delta != 0:
                self.stdout.write(f'{category}: kpi={kpi_total} report={report_total} delta={delta}')

        self.stdout.write('\n=== ITEMS PRESENT IN KPI BUT NOT REPORT ===')
        report_ids = set(report_items.values_list('id', flat=True))
        extra_items = kpi_items.exclude(id__in=report_ids).select_related('invoice', 'invoice__student').order_by('category', 'invoice__student__admission_number', 'id')
        for item in extra_items:
            self.stdout.write(
                f'EXTRA_ITEM id={item.id} cat={item.category} amt={item.net_amount} invoice={item.invoice.invoice_number} adm={item.invoice.student.admission_number} student={item.invoice.student.full_name} desc={item.description}'
            )

        self.stdout.write('\n=== ALLOCATION CATEGORY DIFFS: KPI minus REPORT ===')
        report_allocs = PaymentAllocation.objects.filter(
            invoice_item__in=report_items,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED,
        )
        kpi_allocs = PaymentAllocation.objects.filter(
            invoice_item__in=kpi_items,
            is_active=True,
            payment__is_active=True,
            payment__status=PaymentStatus.COMPLETED,
        )
        alloc_categories = sorted(set(report_allocs.values_list('invoice_item__category', flat=True)) | set(kpi_allocs.values_list('invoice_item__category', flat=True)))
        for category in alloc_categories:
            report_total = report_allocs.filter(invoice_item__category=category).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            kpi_total = kpi_allocs.filter(invoice_item__category=category).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            delta = kpi_total - report_total
            if delta != 0:
                self.stdout.write(f'{category}: kpi={kpi_total} report={report_total} delta={delta}')

        self.stdout.write('\n=== ALLOCATIONS PRESENT IN KPI ITEM SET BUT NOT REPORT ITEM SET ===')
        extra_allocs = kpi_allocs.exclude(invoice_item_id__in=report_items.values_list('id', flat=True)).select_related('invoice_item', 'invoice_item__invoice', 'invoice_item__invoice__student', 'payment').order_by('invoice_item__category', 'invoice_item__invoice__student__admission_number', 'id')
        for alloc in extra_allocs:
            self.stdout.write(
                f'EXTRA_ALLOC id={alloc.id} cat={alloc.invoice_item.category} amt={alloc.amount} payment={alloc.payment.payment_reference} invoice={alloc.invoice_item.invoice.invoice_number} adm={alloc.invoice_item.invoice.student.admission_number} student={alloc.invoice_item.invoice.student.full_name} item_desc={alloc.invoice_item.description}'
            )
