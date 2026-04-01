from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import Organization
from finance.models import Invoice, InvoiceItem
from portal.views import _get_current_term, _get_active_students_qs


class Command(BaseCommand):
    help = 'Find active students where balance_bf_original != invoice balance_bf / balance_bf item totals'

    def add_arguments(self, parser):
        parser.add_argument('--org-name', default='PCEA Wendani Academy')

    def handle(self, *args, **options):
        org = Organization.objects.get(name=options['org_name'])
        term = _get_current_term(organization=org)
        active_students = _get_active_students_qs(organization=org).filter(balance_bf_original__gt=0)

        for s in active_students.order_by('admission_number'):
            invoices = Invoice.objects.filter(
                is_active=True,
                organization=org,
                term=term,
                student=s,
            ).exclude(status='cancelled')
            invoice_bf = invoices.aggregate(total=Sum('balance_bf'))['total'] or Decimal('0.00')
            item_bf = InvoiceItem.objects.filter(
                invoice__in=invoices,
                is_active=True,
                category='balance_bf'
            ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')
            student_bf = s.balance_bf_original or Decimal('0.00')
            if student_bf != invoice_bf or student_bf != item_bf:
                print({
                    'admission': s.admission_number,
                    'name': s.full_name,
                    'student_bf': str(student_bf),
                    'invoice_bf': str(invoice_bf),
                    'item_bf': str(item_bf),
                    'invoice_numbers': list(invoices.values_list('invoice_number', flat=True)),
                })
