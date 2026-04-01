from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import Organization
from finance.models import Invoice, InvoiceItem
from payments.models import PaymentAllocation
from portal.views import _get_current_term, _get_active_students_qs


class Command(BaseCommand):
    help = 'Trace dashboard vs report Balance B/F totals'

    def add_arguments(self, parser):
        parser.add_argument('--org-name', default='PCEA Wendani Academy')

    def handle(self, *args, **options):
        org = Organization.objects.get(name=options['org_name'])
        term = _get_current_term(organization=org)
        active_students = _get_active_students_qs(organization=org)

        dashboard_bf = active_students.aggregate(total=Sum('balance_bf_original'))['total'] or Decimal('0.00')
        self.stdout.write(f'dashboard_balance_bf_original_sum={dashboard_bf}')

        invoices = Invoice.objects.filter(
            is_active=True,
            organization=org,
            term=term,
            student__status='active',
        ).exclude(status='cancelled')

        report_invoice_balance_bf = invoices.aggregate(total=Sum('balance_bf'))['total'] or Decimal('0.00')
        self.stdout.write(f'report_invoice_balance_bf_sum={report_invoice_balance_bf}')

        bf_items = InvoiceItem.objects.filter(invoice__in=invoices, is_active=True, category='balance_bf')
        report_bf_items_total = bf_items.aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')
        self.stdout.write(f'report_balance_bf_items_total={report_bf_items_total}')

        bf_alloc_total = PaymentAllocation.objects.filter(
            invoice_item__in=bf_items,
            is_active=True,
            payment__is_active=True,
            payment__status='completed',
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        self.stdout.write(f'balance_bf_allocations_total={bf_alloc_total}')

        self.stdout.write('\n=== ACTIVE STUDENTS WITH balance_bf_original > 0 ===')
        for s in active_students.filter(balance_bf_original__gt=0).order_by('admission_number'):
            self.stdout.write(f'{s.admission_number} | {s.full_name} | student.balance_bf_original={s.balance_bf_original}')

        self.stdout.write('\n=== INVOICES WITH balance_bf > 0 ===')
        for inv in invoices.filter(balance_bf__gt=0).select_related('student').order_by('student__admission_number', 'invoice_number'):
            self.stdout.write(f'{inv.student.admission_number} | {inv.student.full_name} | {inv.invoice_number} | invoice.balance_bf={inv.balance_bf}')

        self.stdout.write('\n=== BALANCE_BF ITEMS ===')
        for item in bf_items.select_related('invoice', 'invoice__student').order_by('invoice__student__admission_number', 'invoice__invoice_number'):
            self.stdout.write(f'{item.invoice.student.admission_number} | {item.invoice.student.full_name} | {item.invoice.invoice_number} | item.net_amount={item.net_amount} | desc={item.description}')
