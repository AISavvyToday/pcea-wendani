from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import Organization, FeeCategory, PaymentStatus
from finance.models import Invoice, InvoiceItem
from payments.models import PaymentAllocation
from portal.views import _get_current_term


class Command(BaseCommand):
    help = 'Trace category/item deltas between dashboard KPI basis and report basis'

    def add_arguments(self, parser):
        parser.add_argument('--org-name', default='PCEA Wendani Academy')

    def handle(self, *args, **options):
        org = Organization.objects.get(name=options['org_name'])
        term = _get_current_term(organization=org)

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

        billed = {row['category']: row['total'] or Decimal('0.00') for row in items.values('category').annotate(total=Sum('net_amount'))}
        collected = {row['invoice_item__category']: row['total'] or Decimal('0.00') for row in allocs.values('invoice_item__category').annotate(total=Sum('amount'))}

        self.stdout.write('=== CATEGORY TOTALS ===')
        for cat in sorted(set(billed.keys()) | set(collected.keys())):
            self.stdout.write(f"{cat}: billed={billed.get(cat, Decimal('0.00'))} collected={collected.get(cat, Decimal('0.00'))}")

        self.stdout.write('\n=== ADMISSION ITEMS ===')
        for row in items.filter(category=FeeCategory.ADMISSION).values('invoice__student__admission_number', 'invoice__student__first_name', 'invoice__student__last_name', 'description').annotate(total=Sum('net_amount')).order_by('invoice__student__admission_number', 'description'):
            self.stdout.write(str(row))

        self.stdout.write('\n=== FEES-LIKE ITEMS (non transport/admission/other/balance_bf/prepayment) ===')
        fees_items = items.exclude(category__in=['transport', 'admission', 'other', 'balance_bf', 'prepayment'])
        for row in fees_items.values('category').annotate(total=Sum('net_amount')).order_by('category'):
            self.stdout.write(str(row))

        self.stdout.write('\n=== LEGACY/ODD CATEGORIES PRESENT ===')
        odd = items.exclude(category__in=['tuition', 'meals', 'activity', 'examination', 'assessment', 'transport', 'admission', 'other', 'balance_bf', 'prepayment'])
        for row in odd.values('category').annotate(total=Sum('net_amount')).order_by('category'):
            self.stdout.write(str(row))
