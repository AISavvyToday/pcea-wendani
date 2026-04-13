from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from core.models import PaymentStatus
from finance.models import InvoiceItem
from payments.models import PaymentAllocation
from payments.services.invoice import InvoiceService
from students.models import Student


class Command(BaseCommand):
    help = "Repair Balance B/F items and allocations cleanly for active students"

    def add_arguments(self, parser):
        parser.add_argument('--org-name', default='PCEA Wendani Academy')
        parser.add_argument('--dry-run', action='store_true', default=False)

    def handle(self, *args, **options):
        org_name = options['org_name']
        dry_run = options['dry_run']

        students = Student.objects.filter(
            status='active',
            organization__name=org_name,
        ).order_by('admission_number')

        created_items = 0
        created_allocations = 0
        touched_invoice_ids = set()

        for student in students:
            invoices = list(
                student.invoices.filter(is_active=True)
                .exclude(status='cancelled')
                .order_by('issue_date', 'created_at', 'invoice_number')
            )
            if not invoices:
                continue

            for invoice in invoices:
                if (invoice.balance_bf or Decimal('0.00')) <= 0:
                    continue

                bf_item = invoice.items.filter(is_active=True, category='balance_bf').order_by('id').first()
                if not bf_item:
                    if dry_run:
                        created_items += 1
                        continue
                    bf_item = InvoiceItem.objects.create(
                        invoice=invoice,
                        fee_item=None,
                        category='balance_bf',
                        description='Balance B/F from previous term',
                        amount=invoice.balance_bf,
                        discount_applied=Decimal('0.00'),
                        net_amount=invoice.balance_bf,
                    )
                    created_items += 1
                    touched_invoice_ids.add(invoice.id)

                bf_allocated = bf_item.allocations.filter(
                    is_active=True,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED,
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                bf_due = max(Decimal('0.00'), (bf_item.net_amount or Decimal('0.00')) - bf_allocated)
                if bf_due <= 0:
                    continue

                admission_item = invoice.items.filter(is_active=True, category='admission').order_by('id').first()
                admission_due = Decimal('0.00')
                if admission_item:
                    admission_allocated = admission_item.allocations.filter(
                        is_active=True,
                        payment__is_active=True,
                        payment__status=PaymentStatus.COMPLETED,
                    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                    admission_due = max(Decimal('0.00'), (admission_item.net_amount or Decimal('0.00')) - admission_allocated)

                payment_alloc_qs = PaymentAllocation.objects.filter(
                    is_active=True,
                    payment__student=student,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED,
                    invoice_item__invoice=invoice,
                ).select_related('payment', 'invoice_item')

                by_payment = {}
                for alloc in payment_alloc_qs:
                    slot = by_payment.setdefault(alloc.payment_id, {
                        'payment': alloc.payment,
                        'admission': Decimal('0.00'),
                        'bf': Decimal('0.00'),
                        'other': Decimal('0.00'),
                    })
                    if alloc.invoice_item.category == 'admission':
                        slot['admission'] += alloc.amount or Decimal('0.00')
                    elif alloc.invoice_item.category == 'balance_bf':
                        slot['bf'] += alloc.amount or Decimal('0.00')
                    else:
                        slot['other'] += alloc.amount or Decimal('0.00')

                payment_ids_in_order = sorted(
                    by_payment.keys(),
                    key=lambda pid: (
                        by_payment[pid]['payment'].payment_date,
                        by_payment[pid]['payment'].created_at,
                        by_payment[pid]['payment'].payment_reference or '',
                        pid,
                    )
                )

                for payment_id in payment_ids_in_order:
                    if bf_due <= 0:
                        break

                    slot = by_payment[payment_id]
                    payment = slot['payment']
                    payment_amount = payment.amount or Decimal('0.00')
                    existing_non_bf = slot['admission'] + slot['other']
                    existing_bf = slot['bf']

                    remaining_payment_capacity = max(
                        Decimal('0.00'),
                        payment_amount - existing_non_bf - existing_bf,
                    )
                    if remaining_payment_capacity <= 0:
                        continue

                    admission_shortfall_after_this_payment = max(
                        Decimal('0.00'),
                        admission_due - slot['admission'],
                    )
                    available_for_bf = max(
                        Decimal('0.00'),
                        remaining_payment_capacity - admission_shortfall_after_this_payment,
                    )
                    if available_for_bf <= 0:
                        continue

                    amount_to_allocate = min(available_for_bf, bf_due)
                    if amount_to_allocate <= 0:
                        continue

                    if dry_run:
                        created_allocations += 1
                        bf_due -= amount_to_allocate
                        continue

                    with transaction.atomic():
                        PaymentAllocation.objects.create(
                            payment=payment,
                            invoice_item=bf_item,
                            amount=amount_to_allocate,
                        )
                    created_allocations += 1
                    bf_due -= amount_to_allocate
                    touched_invoice_ids.add(invoice.id)

            if not dry_run:
                for invoice in invoices:
                    if invoice.id in touched_invoice_ids:
                        InvoiceService._recalculate_invoice_fields(invoice)
                student.recompute_outstanding_balance()

        self.stdout.write(f'created_items={created_items}')
        self.stdout.write(f'created_allocations={created_allocations}')
        self.stdout.write(f'touched_invoices={len(touched_invoice_ids)}')
