"""
Bulk delete invoices for graduated/transferred students with proper balance restoration.
This command finds all students with status 'graduated' or 'transferred', finds their
active invoices for the current term, and deletes them while properly restoring
balance_bf and prepayments to student credit_balance.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal

from finance.models import Invoice
from students.models import Student
from core.models import InvoiceStatus
from portal.views import _get_current_term


class Command(BaseCommand):
    help = 'Bulk delete invoices for graduated/transferred students with proper balance restoration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without making changes',
        )
        parser.add_argument(
            '--term-id',
            type=int,
            default=None,
            help='Specific term ID to use (default: auto-detect current term)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for each student and invoice',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        term_id = options.get('term_id')
        verbose = options.get('verbose', False)

        self.stdout.write('=' * 80)
        self.stdout.write('BULK DELETE INVOICES FOR GRADUATED/TRANSFERRED STUDENTS')
        self.stdout.write('=' * 80)
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        self.stdout.write('')

        # Get current term
        if term_id:
            from academics.models import Term
            try:
                term = Term.objects.get(id=term_id)
            except Term.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Term with ID {term_id} not found'))
                return
        else:
            term = _get_current_term()
            if not term:
                self.stdout.write(self.style.ERROR('No current term found. Please specify --term-id'))
                return

        self.stdout.write(f'Term: {term}')
        self.stdout.write('')

        # Find students with graduated or transferred status
        inactive_students = Student.objects.filter(
            status__in=['graduated', 'transferred']
        ).order_by('admission_number')

        student_count = inactive_students.count()
        self.stdout.write(f'Found {student_count} students with status "graduated" or "transferred"')
        self.stdout.write('')

        if student_count == 0:
            self.stdout.write(self.style.SUCCESS('No inactive students found. Nothing to do.'))
            return

        # Statistics
        stats = {
            'students_processed': 0,
            'invoices_deleted': 0,
            'invoices_skipped_with_payments': 0,
            'balance_bf_restored': Decimal('0.00'),
            'prepayments_restored': Decimal('0.00'),
            'errors': 0,
        }

        self.stdout.write('Processing students...')
        self.stdout.write('-' * 80)

        for student in inactive_students:
            # Get active invoices for current term
            invoices = Invoice.objects.filter(
                student=student,
                term=term,
                is_active=True
            ).exclude(
                status=InvoiceStatus.CANCELLED
            )

            invoice_count = invoices.count()
            if invoice_count == 0:
                if verbose:
                    self.stdout.write(f'{student.admission_number} - {student.full_name}: No invoices')
                continue

            stats['students_processed'] += 1

            if verbose:
                self.stdout.write(f'\n{student.admission_number} - {student.full_name}')
                self.stdout.write(f'  Status: {student.status}')
                self.stdout.write(f'  Invoices found: {invoice_count}')

            current_credit_before = student.credit_balance or Decimal('0.00')

            for invoice in invoices:
                # Skip invoices with payments
                if invoice.amount_paid > 0:
                    if verbose:
                        self.stdout.write(
                            f'  ⚠ Skipping {invoice.invoice_number}: has payments (KES {invoice.amount_paid:,.2f})'
                        )
                    stats['invoices_skipped_with_payments'] += 1
                    continue

                # Show invoice details
                if verbose:
                    bf = invoice.balance_bf_original or invoice.balance_bf or Decimal('0.00')
                    prep = invoice.prepayment or Decimal('0.00')
                    self.stdout.write(f'  Invoice {invoice.invoice_number}:')
                    if bf > 0:
                        self.stdout.write(f'    Balance B/F: {bf:,.2f}')
                    if prep < 0:
                        self.stdout.write(f'    Prepayment: {abs(prep):,.2f}')

                # Calculate what will be restored
                balance_bf_to_restore = Decimal('0.00')
                prepayment_to_restore = Decimal('0.00')

                if invoice.balance_bf_original and invoice.balance_bf_original > 0:
                    balance_bf_to_restore = invoice.balance_bf_original
                elif invoice.balance_bf and invoice.balance_bf > 0:
                    balance_bf_to_restore = invoice.balance_bf

                if invoice.prepayment and invoice.prepayment < 0:
                    prepayment_to_restore = invoice.prepayment

                if dry_run:
                    if verbose:
                        self.stdout.write(f'    [DRY RUN] Would delete and restore:')
                        if balance_bf_to_restore > 0:
                            self.stdout.write(f'      Balance B/F: +{balance_bf_to_restore:,.2f}')
                        if prepayment_to_restore < 0:
                            self.stdout.write(f'      Prepayment: {prepayment_to_restore:,.2f}')
                else:
                    # Delete invoice using the fixed deletion logic
                    try:
                        with transaction.atomic():
                            # Get current credit_balance
                            student.refresh_from_db()
                            current_credit = student.credit_balance or Decimal('0.00')

                            # Restore balance_bf_original to Student frozen field
                            if invoice.balance_bf_original and invoice.balance_bf_original > 0:
                                student.balance_bf_original = invoice.balance_bf_original
                                student.credit_balance = current_credit + invoice.balance_bf_original
                                current_credit = student.credit_balance
                                stats['balance_bf_restored'] += invoice.balance_bf_original
                            elif invoice.balance_bf and invoice.balance_bf > 0:
                                # Fallback if balance_bf_original not set
                                student.balance_bf_original = invoice.balance_bf
                                student.credit_balance = current_credit + invoice.balance_bf
                                current_credit = student.credit_balance
                                stats['balance_bf_restored'] += invoice.balance_bf

                            # Restore prepayment_original to Student frozen field
                            if invoice.prepayment and invoice.prepayment < 0:
                                student.prepayment_original = abs(invoice.prepayment)
                                student.credit_balance = current_credit + invoice.prepayment
                                stats['prepayments_restored'] += abs(invoice.prepayment)

                            # Soft delete invoice
                            invoice.is_active = False
                            invoice.save(update_fields=['is_active', 'updated_at'])
                            
                            # Save student with restored frozen fields
                            student.save(update_fields=[
                                'balance_bf_original', 
                                'prepayment_original', 
                                'credit_balance', 
                                'updated_at'
                            ])

                        if verbose:
                            self.stdout.write(f'    ✓ Deleted {invoice.invoice_number}')
                        stats['invoices_deleted'] += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(
                            f'    ✗ Error deleting {invoice.invoice_number}: {e}'
                        ))
                        stats['errors'] += 1

            # Show student summary
            if not dry_run:
                student.refresh_from_db()
                current_credit_after = student.credit_balance or Decimal('0.00')
                if current_credit_after != current_credit_before:
                    if verbose:
                        self.stdout.write(
                            f'  Credit balance: {current_credit_before:,.2f} → {current_credit_after:,.2f}'
                        )

        # Summary
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write('SUMMARY')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Students processed: {stats["students_processed"]}')
        self.stdout.write(f'Invoices deleted: {stats["invoices_deleted"]}')
        self.stdout.write(f'Invoices skipped (with payments): {stats["invoices_skipped_with_payments"]}')
        self.stdout.write(f'Balance B/F restored: KES {stats["balance_bf_restored"]:,.2f}')
        self.stdout.write(f'Prepayments restored: KES {stats["prepayments_restored"]:,.2f}')
        if stats['errors'] > 0:
            self.stdout.write(self.style.ERROR(f'Errors: {stats["errors"]}'))

        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('DRY RUN - No changes were made'))
            self.stdout.write('Run without --dry-run to apply changes')
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('✓ Bulk deletion completed'))

