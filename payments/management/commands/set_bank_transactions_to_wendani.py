# payments/management/commands/set_bank_transactions_to_wendani.py
"""
Management command to set all bank transactions to belong to 'PCEA Wendani Academy' organization.
This is a one-time migration to fix existing data.

For matched transactions: Sets payment.organization to PCEA Wendani Academy
For unmatched transactions: They will be filtered by transaction_reference matching 
student admission numbers, so they're already conceptually "belonging" to the organization.
"""
from django.core.management.base import BaseCommand
from payments.models import Payment, BankTransaction
from core.models import Organization
from django.db import transaction as db_transaction


class Command(BaseCommand):
    help = 'Set all bank transactions to belong to PCEA Wendani Academy organization'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Get PCEA Wendani Academy organization
        try:
            wendani_org = Organization.objects.get(name='PCEA Wendani Academy')
        except Organization.DoesNotExist:
            self.stdout.write(
                self.style.ERROR('Organization "PCEA Wendani Academy" not found.')
            )
            self.stdout.write('Available organizations:')
            for org in Organization.objects.all():
                self.stdout.write(f'  - {org.name}')
            return
        
        # Get all bank transactions
        all_bank_txns = BankTransaction.objects.all()
        total_count = all_bank_txns.count()
        
        # Get matched bank transactions (those with payments)
        matched_txns = all_bank_txns.filter(payment__isnull=False).select_related('payment', 'payment__student')
        matched_count = matched_txns.count()
        
        # Get unmatched bank transactions
        unmatched_txns = all_bank_txns.filter(payment__isnull=True)
        unmatched_count = unmatched_txns.count()
        
        self.stdout.write(f'Total bank transactions: {total_count}')
        self.stdout.write(f'  - Matched (with payment): {matched_count}')
        self.stdout.write(f'  - Unmatched (no payment): {unmatched_count}')
        self.stdout.write('')
        
        # For matched transactions, update payment.organization
        payments_to_update = Payment.objects.filter(
            bank_transactions__isnull=False
        ).distinct()
        
        # Filter payments that don't already have the correct organization
        payments_to_update = payments_to_update.exclude(organization=wendani_org)
        
        payment_count = payments_to_update.count()
        
        if payment_count == 0:
            self.stdout.write(
                self.style.SUCCESS('All matched bank transactions already belong to PCEA Wendani Academy.')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'Found {payment_count} payments linked to bank transactions to update.')
            )
            
            if dry_run:
                self.stdout.write(
                    self.style.WARNING('DRY RUN - No changes will be made.')
                )
                for payment in payments_to_update[:10]:  # Show first 10
                    current_org = payment.organization.name if payment.organization else 'None'
                    self.stdout.write(
                        f'  Payment {payment.payment_reference} (Student: {payment.student.full_name}) -> '
                        f'Current org: {current_org} -> New org: {wendani_org.name}'
                    )
                if payment_count > 10:
                    self.stdout.write(f'  ... and {payment_count - 10} more')
            else:
                updated = 0
                with db_transaction.atomic():
                    for payment in payments_to_update:
                        payment.organization = wendani_org
                        payment.save(update_fields=['organization'])
                        updated += 1
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully updated {updated} payments with PCEA Wendani Academy organization.'
                    )
                )
        
        # For unmatched transactions, explain the situation
        self.stdout.write('')
        self.stdout.write(
            self.style.WARNING(
                f'Note: {unmatched_count} unmatched bank transactions cannot have organization set directly '
                f'(BankTransaction model has no organization field).'
            )
        )
        self.stdout.write(
            'These will be filtered by matching transaction_reference to student admission numbers.'
        )
        
        if unmatched_count > 0:
            # Check how many unmatched transactions have transaction_reference that matches Wendani students
            from students.models import Student
            wendani_students = Student.objects.filter(organization=wendani_org, is_active=True)
            wendani_admission_numbers = set(
                wendani_students.values_list('admission_number', flat=True)
            )
            
            # Build variations
            admission_variations = set()
            for adm_num in wendani_admission_numbers:
                if adm_num:
                    adm_num_upper = adm_num.upper().strip()
                    admission_variations.add(adm_num_upper)
                    if adm_num_upper.startswith('PWA'):
                        admission_variations.add(adm_num_upper[3:].strip())
                    if not adm_num_upper.startswith('PWA'):
                        admission_variations.add(f"PWA{adm_num_upper}")
            
            # Count unmatched transactions that match Wendani admission numbers
            from django.db.models import Q
            matching_unmatched = unmatched_txns.filter(
                transaction_reference__in=admission_variations
            ).count()
            
            self.stdout.write(
                f'  - Unmatched transactions matching Wendani admission numbers: {matching_unmatched}'
            )
            self.stdout.write(
                f'  - Unmatched transactions NOT matching Wendani admission numbers: {unmatched_count - matching_unmatched}'
            )

