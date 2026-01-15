# finance/management/commands/import_transport_fees.py
import os
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction, models
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

    def get_admission_number_variations(self, raw_adm):
        """Return all possible admission number variations to try"""
        if not raw_adm or pd.isna(raw_adm):
            return []
        
        raw_adm = str(raw_adm).strip()
        variations = []
        
        # Add the raw version first
        variations.append(raw_adm)
        
        # If it has slashes, also try without them
        if '/' in raw_adm:
            without_slashes = raw_adm.replace('/', '')
            if without_slashes not in variations:
                variations.append(without_slashes)
        
        # If it doesn't have slashes and starts with PWA, try with slashes
        if '/' not in raw_adm and raw_adm.startswith('PWA'):
            # Extract numeric part
            num_part = raw_adm[3:]  # Remove 'PWA'
            if num_part.isdigit():
                with_slashes = f'PWA/{num_part}/'
                if with_slashes not in variations:
                    variations.append(with_slashes)
        
        return variations

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
            
            # Try to find term
            term = Term.objects.filter(
                academic_year=academic_year,
                term='term_1'
            ).first()
            
            if not term:
                self.stdout.write(self.style.ERROR("Term 1 2026 not found"))
                return
            
            self.stdout.write(f"Using term: {term}")
            
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
        skipped_not_active = 0

        for index, row in df.iterrows():
            try:
                # Get raw admission number
                raw_adm = row.get('Admission #')
                if pd.isna(raw_adm):
                    self.stdout.write(f"Row {index}: No admission number")
                    error_count += 1
                    continue
                
                transport_amount = Decimal(str(row.get('Transport Amount', 0)))
                route = str(row.get('Route/Destination', '')).strip()
                
                # Skip if transport amount is 0
                if transport_amount <= 0:
                    self.stdout.write(f"Row {index}: Skipped (zero transport amount)")
                    continue
                
                # Try multiple admission number variations
                variations = self.get_admission_number_variations(raw_adm)
                student = None
                found_admission = None
                
                for adm_variation in variations:
                    try:
                        student = Student.objects.get(admission_number=adm_variation)
                        found_admission = adm_variation
                        break
                    except Student.DoesNotExist:
                        continue
                
                if not student:
                    self.stdout.write(f"{raw_adm}: Student not found (tried: {variations})")
                    error_count += 1
                    continue
                
                # Check if student is active
                if student.status != 'active':
                    self.stdout.write(f"{found_admission}: Student is not active (status: {student.status}) - skipping")
                    skipped_not_active += 1
                    continue
                
                # Find existing invoice for Term 1 2026
                try:
                    invoice = Invoice.objects.get(student=student, term=term)
                except Invoice.DoesNotExist:
                    self.stdout.write(f"{found_admission}: No invoice found for Term 1 2026 - skipping")
                    skipped_no_invoice += 1
                    continue
                except Invoice.MultipleObjectsReturned:
                    # Take the first one
                    invoice = Invoice.objects.filter(student=student, term=term).first()
                    self.stdout.write(f"{found_admission}: Multiple invoices found, using {invoice.invoice_number}")
                
                # Check if transport already exists in invoice items
                existing_transport = invoice.items.filter(category=FeeCategory.TRANSPORT).exists()
                if existing_transport:
                    self.stdout.write(f"{found_admission}: Transport already exists in invoice")
                    skipped_already_exists += 1
                    continue
                
                # DRY RUN: Show what would happen
                if dry_run:
                    old_balance = invoice.balance
                    old_total = invoice.total_amount
                    new_total = old_total + transport_amount
                    new_balance = old_balance + transport_amount
                    
                    self.stdout.write(f"{found_admission}: Would add transport fee of {transport_amount}")
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
                    self.stdout.write(self.style.SUCCESS(f"{found_admission}: Added transport fee of {transport_amount}"))
                    
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
        self.stdout.write(f"  Skipped (not active): {skipped_not_active}")
        self.stdout.write(f"  Errors: {error_count}")
        self.stdout.write(f"  Total in Excel: {len(df)}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("\nThis was a DRY RUN. No changes were made to the database."))
            self.stdout.write("Run without --dry-run to actually import the fees.")
        else:
            self.stdout.write(self.style.SUCCESS("\nTransport fees import completed!"))