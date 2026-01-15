# finance/management/commands/import_transport_fees.py
import os
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from students.models import Student
from finance.models import Invoice, InvoiceItem, FeeStructure, FeeItem
from academics.models import Term, AcademicYear
from core.models import FeeCategory

class Command(BaseCommand):
    help = 'Import transport fees from Excel to student invoices for Term 1 2026'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='transport-report.xlsx',
            help='Path to transport report Excel file'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def normalize_admission_number(self, adm):
        """Normalize admission number from Excel format to DB format"""
        if not adm:
            return None
        
        # Remove any whitespace
        adm = str(adm).strip()
        
        # Handle cases like 'PWA2629' -> convert to 'PWA/2629/'
        if '/' not in adm and adm.startswith('PWA'):
            try:
                # Extract the numeric part
                num_part = adm[3:]  # Remove 'PWA'
                if num_part.isdigit():
                    return f'PWA/{num_part}/'
            except:
                pass
        
        # If it already has slashes, keep as is
        return adm

    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']
        
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        # Load the Excel file
        try:
            df = pd.read_excel(file_path, skiprows=4)  # Skip header rows
            self.stdout.write(f"Loaded {len(df)} records from Excel")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error reading Excel: {e}"))
            return

        # Get or create Term 1 2026
        try:
            # First get or create academic year
            academic_year, created = AcademicYear.objects.get_or_create(
                year=2026,
                defaults={'is_current': False}
            )
            
            # Get or create term
            term, created = Term.objects.get_or_create(
                academic_year=academic_year,
                term='term_1',  # Based on your TermChoices
                defaults={
                    'name': 'Term 1 2026',
                    'start_date': '2026-01-01',
                    'end_date': '2026-03-31',
                    'is_active': True
                }
            )
            self.stdout.write(f"Using term: {term.name}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting term: {e}"))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
            self.stdout.write("=" * 80)

        success_count = 0
        error_count = 0
        skipped_count = 0

        for index, row in df.iterrows():
            try:
                # Get and normalize admission number
                raw_adm = row.get('Admission #')
                if pd.isna(raw_adm):
                    self.stdout.write(f"Row {index}: No admission number")
                    error_count += 1
                    continue
                
                admission_number = self.normalize_admission_number(raw_adm)
                transport_amount = Decimal(str(row.get('Transport Amount', 0)))
                route = str(row.get('Route/Destination', ''))
                
                # Skip if transport amount is 0
                if transport_amount <= 0:
                    self.stdout.write(f"{admission_number}: Skipped (zero transport amount)")
                    skipped_count += 1
                    continue
                
                # Find student
                try:
                    student = Student.objects.get(admission_number=admission_number)
                except Student.DoesNotExist:
                    # Try alternative format (without trailing slash)
                    if admission_number.endswith('/'):
                        alt_adm = admission_number.rstrip('/')
                        try:
                            student = Student.objects.get(admission_number=alt_adm)
                        except Student.DoesNotExist:
                            self.stdout.write(f"{admission_number}: Student not found")
                            error_count += 1
                            continue
                    else:
                        self.stdout.write(f"{admission_number}: Student not found")
                        error_count += 1
                        continue
                
                # Get or create invoice for Term 1 2026
                invoice, created = Invoice.objects.get_or_create(
                    student=student,
                    term=term,
                    defaults={
                        'subtotal': 0,
                        'total_amount': 0,
                        'status': 'overdue',
                        'issue_date': '2026-01-13',
                        'due_date': '2026-01-31',
                    }
                )
                
                # Check if transport already exists in invoice items
                existing_transport = invoice.items.filter(category=FeeCategory.TRANSPORT).exists()
                if existing_transport:
                    self.stdout.write(f"{admission_number}: Transport already exists in invoice")
                    skipped_count += 1
                    continue
                
                # DRY RUN: Show what would happen
                if dry_run:
                    old_balance = invoice.balance
                    new_balance = old_balance + transport_amount
                    
                    self.stdout.write(f"{admission_number}: Would add transport fee of {transport_amount}")
                    self.stdout.write(f"  Route: {route}")
                    self.stdout.write(f"  Invoice: {invoice.invoice_number}")
                    self.stdout.write(f"  Current total: {invoice.total_amount}")
                    self.stdout.write(f"  Current balance: {old_balance}")
                    self.stdout.write(f"  New balance would be: {new_balance}")
                    self.stdout.write("-" * 40)
                    success_count += 1
                    continue
                
                # ACTUAL EXECUTION
                with transaction.atomic():
                    # Get or create fee structure for transport
                    fee_structure, _ = FeeStructure.objects.get_or_create(
                        name=f"Transport Fee - Term 1 2026",
                        academic_year=academic_year,
                        term='term_1',
                        defaults={
                            'description': 'Transport fees imported from Excel',
                        }
                    )
                    
                    # Get or create fee item
                    fee_item, _ = FeeItem.objects.get_or_create(
                        fee_structure=fee_structure,
                        category=FeeCategory.TRANSPORT,
                        description=f'Transport Fee - {route[:50]}',  # Truncate if too long
                        defaults={
                            'amount': transport_amount,
                            'is_optional': True,
                            'applies_to_all': False,
                        }
                    )
                    
                    # Create invoice item
                    invoice_item = InvoiceItem.objects.create(
                        invoice=invoice,
                        fee_item=fee_item,
                        description=f'Transport Fee - {route}',
                        category=FeeCategory.TRANSPORT,
                        amount=transport_amount,
                        discount_applied=Decimal('0.00'),
                        net_amount=transport_amount,
                    )
                    
                    # Update invoice amounts
                    invoice.subtotal += transport_amount
                    invoice.total_amount += transport_amount
                    
                    # Save invoice (which will recalculate balance and update student)
                    invoice.save()
                    
                    # Also update student's transport route if blank
                    if not student.transport_route and route:
                        # Try to find or create TransportRoute
                        from transport.models import TransportRoute
                        try:
                            transport_route, _ = TransportRoute.objects.get_or_create(
                                name=route[:100],  # Truncate if too long
                                defaults={'amount': transport_amount}
                            )
                            student.transport_route = transport_route
                            student.save(update_fields=['transport_route'])
                        except:
                            pass
                    
                    success_count += 1
                    self.stdout.write(f"{admission_number}: Added transport fee of {transport_amount}")
                    
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"Error processing {raw_adm}: {str(e)}"))
                import traceback
                traceback.print_exc()

        # Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("IMPORT SUMMARY:")
        self.stdout.write(f"  Successfully processed: {success_count}")
        self.stdout.write(f"  Skipped (already exists): {skipped_count}")
        self.stdout.write(f"  Errors: {error_count}")
        self.stdout.write(f"  Total in Excel: {len(df)}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("\nThis was a DRY RUN. No changes were made to the database."))
            self.stdout.write("Run without --dry-run to actually import the fees.")
        else:
            self.stdout.write(self.style.SUCCESS("\nTransport fees import completed!"))