# payments/management/commands/backfill_payment_organizations.py
"""
Management command to backfill organization field for existing payments
based on their student's organization.
"""
from django.core.management.base import BaseCommand
from payments.models import Payment
from django.db.models import Q


class Command(BaseCommand):
    help = 'Backfill organization field for payments based on student organization'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Find payments without organization but with students that have organization
        payments_to_update = Payment.objects.filter(
            organization__isnull=True,
            student__organization__isnull=False
        ).select_related('student', 'student__organization')
        
        count = payments_to_update.count()
        
        if count == 0:
            self.stdout.write(
                self.style.SUCCESS('No payments need organization backfilling.')
            )
            return
        
        self.stdout.write(
            self.style.WARNING(f'Found {count} payments to update.')
        )
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN - No changes will be made.')
            )
            for payment in payments_to_update[:10]:  # Show first 10
                self.stdout.write(
                    f'  Payment {payment.payment_reference} -> '
                    f'Organization: {payment.student.organization.name}'
                )
            if count > 10:
                self.stdout.write(f'  ... and {count - 10} more')
        else:
            updated = 0
            for payment in payments_to_update:
                payment.organization = payment.student.organization
                payment.save(update_fields=['organization'])
                updated += 1
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully updated {updated} payments with organization.'
                )
            )

