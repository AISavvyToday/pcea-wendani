from django.core.management.base import BaseCommand
from finance.models import Invoice, InvoiceItem
from students.models import Student

CASES = ['2419', '2505', '2721', '2740']

class Command(BaseCommand):
    help = 'Inspect specific Balance B/F mismatch cases'

    def handle(self, *args, **options):
        for adm in CASES:
            s = Student.objects.get(admission_number=adm)
            print('\n' + '='*80)
            print('STUDENT', s.admission_number, s.full_name, 'student_bf', s.balance_bf_original, 'outstanding', s.outstanding_balance)
            invoices = Invoice.objects.filter(student=s, is_active=True).exclude(status='cancelled').order_by('invoice_number')
            for inv in invoices:
                print('INVOICE', inv.invoice_number, 'term', inv.term_id, 'bf', inv.balance_bf, 'bf_original', getattr(inv, 'balance_bf_original', None), 'total', inv.total_amount, 'paid', inv.amount_paid, 'balance', inv.balance)
                items = InvoiceItem.objects.filter(invoice=inv, is_active=True).order_by('id')
                for item in items:
                    print('  ITEM', item.id, item.category, item.net_amount, item.description)
