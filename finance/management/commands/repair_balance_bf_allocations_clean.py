from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from core.models import PaymentStatus
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
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
        ).select_related('organization').order_by('admission_number')

        created_items = 0
        created_allocations = 0
        touched_invoices = set()

        for student in students:
            invoices = list(
                student.invoices.filter(is_active=True)
                .exclude(status='cancelled')
                .order_by('issue_date', 'created_at', 'invoice_number')
            )
            if not invoices:
                continue

            payments = list(
                Payment.objects.filter(
                    student=student,
                    is_active=True,
                    status=PaymentStatus.COMPLETED,
                ).order_by('payment_date', 'created_at', 'payment_reference')
            )
            if not payments:
                continue

            for invoice in invoices:
                if (invoice.balance_bf or Decimal('0.00')) <= 0:
                    continue

                bf_item = invoice.items.filter(is_active=True, category='balance_bf').order_by('id').first()
                if not bf_item:
                    if dry_run:
                        created_items += 1
                    else:
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
                        touched_invoices.add(str(invoice.pk))

                if not bf_item:
                    continue

                admission_item = invoice.items.filter(is_active=True, category='admission').order_by('id').first()

                admission_due = Decimal('0.00')
                if admission_item:
                    admission_alloc = admission_item.allocations.filter(
                        is_active=True,
                        payment__is_active=True,
                        payment__status=PaymentStatus.COMPLETED,
                    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                    admission_due = max(Decimal('0.00'), (admission_item.net_amount or Decimal('0.00')) - admission_alloc)

                bf_alloc = bf_item.allocations.filter(
                    is_active=True,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED,
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                bf_due = max(Decimal('0.00'), (bf_item.net_amount or Decimal('0.00')) - bf_alloc)
                if bf_due <= 0:
                    continue

                for payment in payments:
                    if bf_due <= 0:
                        break

                    payment_alloc_total = payment.allocations.filter(is_active=True).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                    payment_unallocated = max(Decimal('0.00'), (payment.amount or Decimal('0.00')) - payment_alloc_total)
                    if payment_unallocated <= 0:
                        continue

                    reserve_for_admission = admission_due
                    available_for_bf = max(Decimal('0.00'), payment_unallocated - reserve_for_admission)
                    if available_for_bf <= 0:
                        continue

                    amount_to_allocate = min(available_for_bf, bf_due)
                    if amount_to_allocate <= 0:
                        continue

                    if dry_run:
                        created_allocations += 1
                        bf_due -= amount_to_allocate
                        admission_due = max(Decimal('0.00'), admission_due - payment_unallocated)
                        continue

                    with transaction.atomic():
                        PaymentAllocation.objects.create(
                            payment=payment,
                            invoice_item=bf_item,
                            amount=amount_to_allocate,
                        )
                        created_allocations += 1
                        bf_due -= amount_to_allocate
                        touched_invoices.add(str(invoice.pk))

            # recalc touched student invoices after processing the student
            if not dry_run:
                for invoice in invoices:
                    if str(invoice.pk) in touched_invoices:
                        InvoiceService._recalculate_invoice_fields(invoice)
                student.recompute_outstanding_balance()

        self.stdout.write(f'created_items={created_items}')
        self.stdout.write(f'created_allocations={created_allocations}')
        self.stdout.write(f'touched_invoices={len(touched_invoices)}')
