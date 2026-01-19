# finance/management/commands/fix_transport_routes_only.py
import os
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from finance.models import InvoiceItem
from students.models import Student
from academics.models import Term, AcademicYear
from core.models import FeeCategory
from transport.models import TransportRoute

class Command(BaseCommand):
    help = 'ONLY set transport routes from Excel (no other modifications)'
    
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
    
    def get_admission_variations(self, raw_adm):
        """Return admission number variations"""
        if pd.isna(raw_adm):
            return []
        
        variations = [str(raw_adm).strip()]
        
        # Without slashes
        if '/' in variations[0]:
            variations.append(variations[0].replace('/', ''))
        
        return variations
    
    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']
        
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {file_path}"))
            return
        
        # Load Excel
        try:
            df = pd.read_excel(file_path, skiprows=4)
            df.columns = df.columns.str.strip()
            self.stdout.write(f"Loaded {len(df)} rows from Excel")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error reading Excel: {e}"))
            return
        
        # Get Term 1 2026
        try:
            academic_year = AcademicYear.objects.get(year=2026)
            term = Term.objects.get(academic_year=academic_year, term='term_1')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error getting term: {e}"))
            return
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
        
        # Statistics
        stats = {
            'items_updated': 0,
            'routes_created': 0,
            'skipped_no_route': 0,
            'skipped_no_student': 0,
            'skipped_no_item': 0,
            'errors': 0,
        }
        
        # Cache routes
        route_cache = {}
        
        for index, row in df.iterrows():
            try:
                raw_adm = row.get('Admission #')
                raw_route = row.get('Route/Destination')
                
                if pd.isna(raw_adm) or pd.isna(raw_route):
                    continue
                
                # Find student
                student = None
                for adm_var in self.get_admission_variations(raw_adm):
                    try:
                        student = Student.objects.get(admission_number=adm_var)
                        break
                    except Student.DoesNotExist:
                        continue
                
                if not student:
                    stats['skipped_no_student'] += 1
                    continue
                
                # Get or create route
                route_name = str(raw_route).strip()
                if route_name not in route_cache:
                    route = TransportRoute.objects.filter(name__iexact=route_name).first()
                    if not route:
                        # Create simple route
                        route = TransportRoute.objects.create(
                            name=route_name,
                            description=f"Route for {route_name}",
                            pickup_points=route_name,
                            dropoff_points="School"
                        )
                        stats['routes_created'] += 1
                        if not dry_run:
                            self.stdout.write(f"Created route: {route_name}")
                    route_cache[route_name] = route
                else:
                    route = route_cache[route_name]
                
                # Find transport invoice items for this student in Term 1 2026
                transport_items = InvoiceItem.objects.filter(
                    invoice__student=student,
                    invoice__term=term,
                    category=FeeCategory.TRANSPORT
                )
                
                if not transport_items.exists():
                    stats['skipped_no_item'] += 1
                    continue
                
                # DRY RUN
                if dry_run:
                    self.stdout.write(f"[DRY RUN] {student.admission_number}: Would set route to '{route_name}'")
                    stats['items_updated'] += transport_items.count()
                    continue
                
                # ACTUAL UPDATE
                with transaction.atomic():
                    updated = transport_items.update(
                        transport_route=route,
                        transport_trip_type='full'
                    )
                    
                    # Also update student's transport route
                    if not student.transport_route:
                        student.transport_route = route
                        student.save(update_fields=['transport_route'])
                    
                    stats['items_updated'] += updated
                    self.stdout.write(f"✓ {student.admission_number}: Set route to '{route_name}'")
                    
            except Exception as e:
                stats['errors'] += 1
                self.stdout.write(self.style.ERROR(f"Error on row {index}: {e}"))
        
        # Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("ROUTE FIX SUMMARY:")
        self.stdout.write(f"  Transport items updated: {stats['items_updated']}")
        self.stdout.write(f"  Routes created: {stats['routes_created']}")
        self.stdout.write(f"  Skipped (no student): {stats['skipped_no_student']}")
        self.stdout.write(f"  Skipped (no transport item): {stats['skipped_no_item']}")
        self.stdout.write(f"  Errors: {stats['errors']}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN - Nothing was changed"))