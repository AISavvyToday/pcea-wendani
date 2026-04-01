from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from students.models import Student
from finance.models import Invoice, InvoiceItem


class Command(BaseCommand):
    help = 'Fix known Balance B/F alignment cases cleanly'

    @transaction.atomic
    def handle(self, *args, **options):
        # 2419: student BF should match invoice/header/item (1200)
        s = Student.objects.select_for_update().get(admission_number='2419')
        inv = Invoice.objects.select_for_update().get(invoice_number='INV-2026-00535')
        s.balance_bf_original = inv.balance_bf
        s.save(update_fields=['balance_bf_original', 'updated_at'])
        self.stdout.write(f'2419 -> student.balance_bf_original set to {s.balance_bf_original}')

        # 2505: student BF should be zero because invoice has no BF carry-forward
        s = Student.objects.select_for_update().get(admission_number='2505')
        s.balance_bf_original = Decimal('0.00')
        s.save(update_fields=['balance_bf_original', 'updated_at'])
        self.stdout.write(f'2505 -> student.balance_bf_original set to {s.balance_bf_original}')

        # 2721: fix zero BF item to match invoice header BF (500)
        inv = Invoice.objects.select_for_update().get(invoice_number='INV-2026-00130')
        item = InvoiceItem.objects.select_for_update().get(invoice=inv, category='balance_bf', is_active=True)
        item.amount = inv.balance_bf
        item.net_amount = inv.balance_bf
        item.discount_applied = Decimal('0.00')
        item.save(update_fields=['amount', 'net_amount', 'discount_applied'])
        self.stdout.write(f'2721 -> balance_bf item set to {item.net_amount}')

        # 2740: fix zero BF item to match invoice header BF (1500)
        inv = Invoice.objects.select_for_update().get(invoice_number='INV-2026-00142')
        item = InvoiceItem.objects.select_for_update().get(invoice=inv, category='balance_bf', is_active=True)
        item.amount = inv.balance_bf
        item.net_amount = inv.balance_bf
        item.discount_applied = Decimal('0.00')
        item.save(update_fields=['amount', 'net_amount', 'discount_applied'])
        self.stdout.write(f'2740 -> balance_bf item set to {item.net_amount}')

        # Recompute impacted students after fixes
        for adm in ['2419', '2505', '2721', '2740']:
            s = Student.objects.get(admission_number=adm)
            s.recompute_outstanding_balance()
            self.stdout.write(f'{adm} -> outstanding={s.outstanding_balance}, credit={s.credit_balance}, bf_original={s.balance_bf_original}')
