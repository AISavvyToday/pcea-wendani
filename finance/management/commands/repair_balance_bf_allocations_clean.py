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
    help = "Repair Balance B/F allocations cleanly using admission-first then BF-first reallocation rules"

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

        moved_allocations = 0
        moved_amount_total = Decimal('0.00')
        touched_invoice_ids = set()
        touched_student_ids = set()

        for student in students:
            invoices = list(
                student.invoices.filter(is_active=True)
                .exclude(status='cancelled')
                .order_by('issue_date', 'created_at', 'invoice_number')
            )
            if not invoices:
                continue

            for invoice in invoices:
                bf_item = invoice.items.filter(is_active=True, category='balance_bf').order_by('id').first()
                if not bf_item:
                    continue

                admission_exists = invoice.items.filter(is_active=True, category='admission').exists()
                if admission_exists:
                    continue

                bf_allocated = bf_item.allocations.filter(
                    is_active=True,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED,
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                bf_due = max(Decimal('0.00'), (bf_item.net_amount or Decimal('0.00')) - bf_allocated)
                if bf_due <= 0:
                    continue

                movable_allocations = list(
                    PaymentAllocation.objects.filter(
                        is_active=True,
                        payment__student=student,
                        payment__is_active=True,
                        payment__status=PaymentStatus.COMPLETED,
                        invoice_item__invoice=invoice,
                        invoice_item__is_active=True,
                    )
                    .exclude(invoice_item__category__in=['admission', 'balance_bf'])
                    .select_related('payment', 'invoice_item')
                    .order_by(
                        'payment__payment_date',
                        'payment__created_at',
                        'payment__payment_reference',
                        'id',
                    )
                )

                for alloc in movable_allocations:
                    if bf_due <= 0:
                        break

                    alloc_amount = alloc.amount or Decimal('0.00')
                    if alloc_amount <= 0:
                        continue

                    amount_to_move = min(alloc_amount, bf_due)
                    if amount_to_move <= 0:
                        continue

                    if dry_run:
                        self.stdout.write(
                            f"DRY-RUN move KES {amount_to_move} | adm={student.admission_number} | invoice={invoice.invoice_number} | from={alloc.invoice_item.category} | alloc_id={alloc.id}"
                        )
                        bf_due -= amount_to_move
                        moved_amount_total += amount_to_move
                        moved_allocations += 1
                        touched_invoice_ids.add(str(invoice.id))
                        touched_student_ids.add(str(student.id))
                        continue

                    with transaction.atomic():
                        if amount_to_move == alloc_amount:
                            alloc.invoice_item = bf_item
                            alloc.save(update_fields=['invoice_item'])
                        else:
                            alloc.amount = alloc_amount - amount_to_move
                            alloc.save(update_fields=['amount'])
                            PaymentAllocation.objects.create(
                                payment=alloc.payment,
                                invoice_item=bf_item,
                                amount=amount_to_move,
                            )

                    self.stdout.write(
                        f"MOVED KES {amount_to_move} | adm={student.admission_number} | invoice={invoice.invoice_number} | from={alloc.invoice_item.category} | alloc_id={alloc.id}"
                    )
                    bf_due -= amount_to_move
                    moved_amount_total += amount_to_move
                    moved_allocations += 1
                    touched_invoice_ids.add(str(invoice.id))
                    touched_student_ids.add(str(student.id))

        if not dry_run:
            touched_invoices = (
                student.invoices.filter(id__in=touched_invoice_ids)
                for student in students.filter(id__in=touched_student_ids)
            )
            seen_invoice_ids = set()
            for invoice_qs in touched_invoices:
                for invoice in invoice_qs:
                    if str(invoice.id) in seen_invoice_ids:
                        continue
                    InvoiceService._recalculate_invoice_fields(invoice)
                    seen_invoice_ids.add(str(invoice.id))
            for student in students.filter(id__in=touched_student_ids):
                student.recompute_outstanding_balance()

        self.stdout.write(f'moved_allocations={moved_allocations}')
        self.stdout.write(f'moved_amount_total={moved_amount_total}')
        self.stdout.write(f'touched_invoices={len(touched_invoice_ids)}')
        self.stdout.write(f'touched_students={len(touched_student_ids)}')
