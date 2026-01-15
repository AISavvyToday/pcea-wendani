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
        if not adm or pd.isna(adm):
            return None
        
        # Convert to string and strip
        adm = str(adm).strip()
        
        # Handle cases like 'PWA2629' -> convert to 'PWA/2629/'
        if '/' not in adm and adm.startswith('PWA'):
            try:
                # Extract the numeric part
                num_part = adm[3:]  # Remove 'PWA'
                if num_part.isdigit():
                    return f'PWA/{num_part}/'
                else:
                    # Handle cases with letters after PWA
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
            # Clean column names (remove extra spaces)
            df.columns = df.columns.str.strip()
            self.stdout.write(f"Loaded {len(df)} records from Excel")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error reading Excel: {e}"))
            return

        # Get Term 1 2026
        try:
            # First get academic year
            academic_year = AcademicYear.objects.get(year=2026)
            
            # Get term - try different field names
            term = None
            # Try 'term' field first (most common)
            term = Term.objects.filter(
                academic_year=academic_year,
                term='term_1'
            ).first()
            
            if not term:
                # Try 'name' field
                term = Term.objects.filter(
                    academic_year=academic_year,
                    name__icontains='term 1'
                ).first()
            
            if not term:
                self.stdout.write(self.style.ERROR("Term 1 2026 not found"))
                return
            
            # Get term display name (try different attributes)
            term_display = getattr(term, 'name', None) or getattr(term, 'term', 'Term 1 2026')
            self.stdout.write(f"Found term: {term_display}")
            
        except AcademicYear.DoesNotExist:
            self.stdout.write(self.style.ERROR("Academic year 2026 not found"))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting term: {e}"))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
            self.stdout.write("=" * 80)

        success_count = 0
        error_count = 0
        skipped_no_invoice = 0
        skipped_already_exists = 0

        for index, row in df.iterrows():
            try:
                # Get and normalize admission number
                raw_adm = row.get('Admission #')
                if pd.isna(raw_adm):
                    self.stdout.write(f"Row {index}: No admission number")
                    error_count += 1
                    continue
                
                admission_number = self.normalize_admission_number(raw_adm)
                if not admission_number:
                    self.stdout.write(f"Row {index}: Invalid admission number: {raw_adm}")
                    error_count += 1
                    continue
                    
                transport_amount = Decimal(str(row.get('Transport Amount', 0)))
                route = str(row.get('Route/Destination', '')).strip()
                
                # Skip if transport amount is 0
                if transport_amount <= 0:
                    self.stdout.write(f"{admission_number}: Skipped (zero transport amount)")
                    continue
                
                # Find student
                try:
                    # Try exact match first
                    student = Student.objects.get(admission_number=admission_number)
                except Student.DoesNotExist:
                    # Try without trailing slash
                    if admission_number.endswith('/'):
                        alt_adm = admission_number.rstrip('/')
                        try:
                            student = Student.objects.get(admission_number=alt_adm)
                            admission_number = alt_adm  # Update to found format
                        except Student.DoesNotExist:
                            # Try with/without prefix
                            if admission_number.startswith('PWA/'):
                                alt_adm = admission_number.replace('PWA/', 'PWA')
                                try:
                                    student = Student.objects.get(admission_number=alt_adm)
                                    admission_number = alt_adm
                                except Student.DoesNotExist:
                                    self.stdout.write(f"{admission_number}: Student not found")
                                    error_count += 1
                                    continue
                            else:
                                self.stdout.write(f"{admission_number}: Student not found")
                                error_count += 1
                                continue
                    else:
                        self.stdout.write(f"{admission_number}: Student not found")
                        error_count += 1
                        continue
                
                # Find existing invoice for Term 1 2026
                try:
                    invoice = Invoice.objects.get(student=student, term=term)
                except Invoice.DoesNotExist:
                    self.stdout.write(f"{admission_number}: No invoice found for Term 1 2026 - skipping")
                    skipped_no_invoice += 1
                    continue
                except Invoice.MultipleObjectsReturned:
                    # Take the first one
                    invoice = Invoice.objects.filter(student=student, term=term).first()
                    self.stdout.write(f"{admission_number}: Multiple invoices found, using {invoice.invoice_number}")
                
                # Check if transport already exists in invoice items
                existing_transport = invoice.items.filter(category=FeeCategory.TRANSPORT).exists()
                if existing_transport:
                    self.stdout.write(f"{admission_number}: Transport already exists in invoice")
                    skipped_already_exists += 1
                    continue
                
                # DRY RUN: Show what would happen
                if dry_run:
                    old_balance = invoice.balance
                    old_total = invoice.total_amount
                    new_total = old_total + transport_amount
                    new_balance = old_balance + transport_amount
                    
                    self.stdout.write(f"{admission_number}: Would add transport fee of {transport_amount}")
                    self.stdout.write(f"  Route: {route}")
                    self.stdout.write(f"  Invoice: {invoice.invoice_number}")
                    self.stdout.write(f"  Current total: {old_total} → New total: {new_total}")
                    self.stdout.write(f"  Current balance: {old_balance} → New balance: {new_balance}")
                    self.stdout.write("-" * 40)
                    success_count += 1
                    continue
                
                # ACTUAL EXECUTION
                with transaction.atomic():
                    # Get or create fee structure for transport (for reference only)
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
                        description=f'Transport Fee - {route[:50]}' if route else 'Transport Fee',
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
                        description=f'Transport Fee - {route}' if route else 'Transport Fee',
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
                    
                    # Also update student's transport flag and route if applicable
                    if not student.uses_school_transport:
                        student.uses_school_transport = True
                        student.save(update_fields=['uses_school_transport'])
                    
                    success_count += 1
                    self.stdout.write(self.style.SUCCESS(f"{admission_number}: Added transport fee of {transport_amount}"))
                    
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"Error processing row {index} ({raw_adm}): {str(e)}"))
                if not dry_run:
                    import traceback
                    traceback.print_exc()

        # Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("IMPORT SUMMARY:")
        self.stdout.write(f"  Successfully processed: {success_count}")
        self.stdout.write(f"  Skipped (no invoice): {skipped_no_invoice}")
        self.stdout.write(f"  Skipped (already exists): {skipped_already_exists}")
        self.stdout.write(f"  Errors: {error_count}")
        self.stdout.write(f"  Total in Excel: {len(df)}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("\nThis was a DRY RUN. No changes were made to the database."))
            self.stdout.write("Run without --dry-run to actually import the fees."))
        else:
            self.stdout.write(self.style.SUCCESS("\nTransport fees import completed!"))