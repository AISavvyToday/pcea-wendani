"""
Fix invoice organizations - assign all invoices to 'PCEA Wendani Academy' organization.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from finance.models import Invoice
from core.models import Organization
from students.models import Student
from payments.models import Payment
from other_income.models import OtherIncomeInvoice


class Command(BaseCommand):
    help = 'Assign all invoices and related data to PCEA Wendani Academy organization'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Find or create the organization
        org_name = 'PCEA Wendani Academy'
        org = Organization.objects.filter(name__icontains='PCEA Wendani').first()
        
        if not org:
            # Try other variations
            org = Organization.objects.filter(name__icontains='Wendani').first()
        
        if not org:
            self.stdout.write(self.style.ERROR(f'Organization "{org_name}" not found. Available organizations:'))
            for o in Organization.objects.all():
                self.stdout.write(f'  - {o.name} (ID: {o.id})')
            if not dry_run:
                # Create it if it doesn't exist
                org = Organization.objects.create(name=org_name, is_active=True)
                self.stdout.write(self.style.SUCCESS(f'Created organization: {org.name} (ID: {org.id})'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Found organization: {org.name} (ID: {org.id})'))
        
        if not org:
            self.stdout.write(self.style.ERROR('Cannot proceed without organization'))
            return
        
        # Fix invoices
        invoices_without_org = Invoice.objects.filter(organization__isnull=True)
        invoices_wrong_org = Invoice.objects.exclude(organization=org).exclude(organization__isnull=True)
        
        self.stdout.write(f'\nInvoices without organization: {invoices_without_org.count()}')
        self.stdout.write(f'Invoices with wrong organization: {invoices_wrong_org.count()}')
        
        if not dry_run:
            updated_count = invoices_without_org.update(organization=org)
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_count} invoices without organization'))
            
            updated_wrong = invoices_wrong_org.update(organization=org)
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_wrong} invoices with wrong organization'))
        
        # Fix students
        students_without_org = Student.objects.filter(organization__isnull=True)
        students_wrong_org = Student.objects.exclude(organization=org).exclude(organization__isnull=True)
        
        self.stdout.write(f'\nStudents without organization: {students_without_org.count()}')
        self.stdout.write(f'Students with wrong organization: {students_wrong_org.count()}')
        
        if not dry_run:
            updated_students = students_without_org.update(organization=org)
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_students} students without organization'))
            
            updated_students_wrong = students_wrong_org.update(organization=org)
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_students_wrong} students with wrong organization'))
        
        # Fix payments
        payments_without_org = Payment.objects.filter(organization__isnull=True)
        payments_wrong_org = Payment.objects.exclude(organization=org).exclude(organization__isnull=True)
        
        self.stdout.write(f'\nPayments without organization: {payments_without_org.count()}')
        self.stdout.write(f'Payments with wrong organization: {payments_wrong_org.count()}')
        
        if not dry_run:
            updated_payments = payments_without_org.update(organization=org)
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_payments} payments without organization'))
            
            updated_payments_wrong = payments_wrong_org.update(organization=org)
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_payments_wrong} payments with wrong organization'))
        
        # Fix other income invoices
        other_invoices_without_org = OtherIncomeInvoice.objects.filter(organization__isnull=True)
        other_invoices_wrong_org = OtherIncomeInvoice.objects.exclude(organization=org).exclude(organization__isnull=True)
        
        self.stdout.write(f'\nOther income invoices without organization: {other_invoices_without_org.count()}')
        self.stdout.write(f'Other income invoices with wrong organization: {other_invoices_wrong_org.count()}')
        
        if not dry_run:
            updated_other = other_invoices_without_org.update(organization=org)
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_other} other income invoices without organization'))
            
            updated_other_wrong = other_invoices_wrong_org.update(organization=org)
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_other_wrong} other income invoices with wrong organization'))
        
        # Verify
        total_invoices = Invoice.objects.count()
        invoices_with_org = Invoice.objects.filter(organization=org).count()
        
        self.stdout.write(f'\n=== SUMMARY ===')
        self.stdout.write(f'Total invoices: {total_invoices}')
        self.stdout.write(f'Invoices with {org.name}: {invoices_with_org}')
        self.stdout.write(f'Invoices without organization: {Invoice.objects.filter(organization__isnull=True).count()}')
        
        if invoices_with_org == total_invoices:
            self.stdout.write(self.style.SUCCESS('\n✓ All invoices are now assigned to the correct organization!'))
        else:
            self.stdout.write(self.style.WARNING(f'\n⚠ {total_invoices - invoices_with_org} invoices still need to be fixed'))

