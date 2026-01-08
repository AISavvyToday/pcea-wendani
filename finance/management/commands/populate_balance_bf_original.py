"""
Populate balance_bf_original field for existing invoices where it's NULL.
This migration script ensures all invoices have balance_bf_original set to balance_bf value.
"""
from django.core.management.base import BaseCommand
from django.db import transaction, models
from decimal import Decimal

from finance.models import Invoice


class Command(BaseCommand):
    help = 'Populate balance_bf_original field for invoices where it is NULL'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for each invoice updated',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']
        
        # Find invoices where balance_bf_original is NULL or 0 but balance_bf > 0
        # We'll set balance_bf_original = balance_bf for these invoices
        invoices_to_update = Invoice.objects.filter(
            balance_bf__gt=0
        ).filter(
            # balance_bf_original is NULL or 0
            models.Q(balance_bf_original__isnull=True) | models.Q(balance_bf_original=0)
        )
        
        count = invoices_to_update.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No invoices need updating. All invoices have balance_bf_original set.'))
            return
        
        self.stdout.write(f'Found {count} invoice(s) that need balance_bf_original populated.')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
            self.stdout.write('')
        
        updated_count = 0
        total_balance_bf = Decimal('0.00')
        
        with transaction.atomic():
            for invoice in invoices_to_update:
                old_value = invoice.balance_bf_original
                new_value = invoice.balance_bf
                
                if verbose:
                    self.stdout.write(
                        f'  Invoice {invoice.invoice_number} (Student: {invoice.student.admission_number}): '
                        f'balance_bf_original: {old_value} -> {new_value}'
                    )
                
                if not dry_run:
                    invoice.balance_bf_original = new_value
                    invoice.save(update_fields=['balance_bf_original'])
                
                updated_count += 1
                total_balance_bf += new_value
        
        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(f'Would update {updated_count} invoice(s)'))
            self.stdout.write(self.style.WARNING(f'Total balance_bf_original to be set: {total_balance_bf:,.2f}'))
            self.stdout.write('')
            self.stdout.write('Run without --dry-run to apply changes')
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'Successfully updated {updated_count} invoice(s)'))
            self.stdout.write(self.style.SUCCESS(f'Total balance_bf_original set: {total_balance_bf:,.2f}'))

