from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from students.models import Student
from finance.models import Invoice
from payments.models import Payment, PaymentAllocation


class Command(BaseCommand):
    help = "Fix named account discrepancies by admission number using canonical payment/allocation math"

    TARGETS = {
        '2631': {'credit_balance': Decimal('36000.00')},
        '2877': {'credit_balance': Decimal('31000.00')},
        '2775': {'credit_balance': Decimal('3900.00')},
        '3030': {'outstanding_balance': Decimal('500.00')},
    }

    def add_arguments(self, parser):
        parser.add_argument('admission_numbers', nargs='+')
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']

        for adm in options['admission_numbers']:
            student = Student.objects.select_for_update().filter(admission_number=adm).first()
            if not student:
                raise CommandError(f'Student not found: {adm}')
            if adm not in self.TARGETS:
                raise CommandError(f'Admission not whitelisted for this fixer: {adm}')

            total_paid = Payment.objects.filter(
                student=student, is_active=True, status='completed'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            total_alloc = PaymentAllocation.objects.filter(
                payment__student=student,
                payment__is_active=True,
                payment__status='completed',
                is_active=True,
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            expected_credit = max(Decimal('0.00'), total_paid - total_alloc)

            invoice_outstanding = Invoice.objects.filter(
                student=student,
                is_active=True,
            ).exclude(status='cancelled').aggregate(total=Sum('balance'))['total'] or Decimal('0.00')
            invoice_outstanding = max(invoice_outstanding, Decimal('0.00'))

            self.stdout.write(f'Admission {adm} - {student.full_name}')
            self.stdout.write(f'  current credit_balance={student.credit_balance}')
            self.stdout.write(f'  current outstanding_balance={student.outstanding_balance}')
            self.stdout.write(f'  computed expected_credit={expected_credit}')
            self.stdout.write(f'  computed invoice_outstanding={invoice_outstanding}')

            target_credit = self.TARGETS[adm].get('credit_balance', student.credit_balance or Decimal('0.00'))
            target_outstanding = self.TARGETS[adm].get('outstanding_balance', invoice_outstanding)

            if adm in ('2631', '2877', '2775') and target_credit != expected_credit:
                raise CommandError(
                    f'Guard failed for {adm}: hardcoded target credit {target_credit} != computed {expected_credit}'
                )

            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'  DRY RUN → would set credit_balance={target_credit}, outstanding_balance={target_outstanding}'
                ))
                continue

            student.credit_balance = max(target_credit, Decimal('0.00'))
            student.outstanding_balance = max(target_outstanding, Decimal('0.00'))
            student.save(update_fields=['credit_balance', 'outstanding_balance', 'updated_at'])

            # Keep payment.unallocated_amount aligned with actual allocations for receipt/reporting.
            for payment in Payment.objects.filter(student=student, is_active=True, status='completed'):
                alloc = payment.allocations.filter(is_active=True).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                unallocated = max(Decimal('0.00'), (payment.amount or Decimal('0.00')) - alloc)
                if payment.unallocated_amount != unallocated:
                    payment.unallocated_amount = unallocated
                    payment.save(update_fields=['unallocated_amount', 'updated_at'])

            self.stdout.write(self.style.SUCCESS(
                f'  FIXED → credit_balance={student.credit_balance}, outstanding_balance={student.outstanding_balance}'
            ))
