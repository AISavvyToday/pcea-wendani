# core/management/commands/migrate_to_organization.py
"""
Django management command to migrate existing data to organization.

This command:
1. Creates "PCEA Wendani Academy" organization if it doesn't exist
2. Assigns all existing records to this organization
3. Assigns all users without organization to this organization

Usage:
    python manage.py migrate_to_organization
"""

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Organization
from accounts.models import User
from students.models import Student, Parent
from academics.models import (
    AcademicYear, Term, Department, Staff, Class, Subject, 
    ClassSubject, Exam, Grade, Attendance, Timetable
)
from finance.models import FeeStructure, Discount, Invoice
from transport.models import TransportRoute, TransportFee
from payments.models import Payment
from reports.models import ReportRequest
from other_income.models import OtherIncomeInvoice

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migrate existing data to PCEA Wendani Academy organization'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Perform a dry run without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        try:
            with transaction.atomic():
                # Create or get organization
                org, created = Organization.objects.get_or_create(
                    code='PCEA_WENDANI',
                    defaults={
                        'name': 'PCEA Wendani Academy',
                        'sms_account_number': 'SMS001',
                        'sms_balance': 0,
                        'sms_price_per_unit': 1.00,
                        'imarabiz_shortcode': 'SWIFT_TECH',
                        'is_active': True,
                    }
                )
                
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Created organization: {org.name}'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'Using existing organization: {org.name}'))
                
                if dry_run:
                    # Rollback transaction for dry run
                    transaction.set_rollback(True)
                    self.stdout.write(self.style.WARNING('Dry run complete - rolling back'))
                    return
                
                # Counters for reporting
                counts = {}
                
                # Migrate Users
                users_updated = User.objects.filter(organization__isnull=True).update(organization=org)
                counts['users'] = users_updated
                self.stdout.write(f'  Updated {users_updated} users')
                
                # Migrate Students
                students_updated = Student.objects.filter(organization__isnull=True).update(organization=org)
                counts['students'] = students_updated
                self.stdout.write(f'  Updated {students_updated} students')
                
                # Migrate Parents
                parents_updated = Parent.objects.filter(organization__isnull=True).update(organization=org)
                counts['parents'] = parents_updated
                self.stdout.write(f'  Updated {parents_updated} parents')
                
                # Migrate AcademicYear
                academic_years_updated = AcademicYear.objects.filter(organization__isnull=True).update(organization=org)
                counts['academic_years'] = academic_years_updated
                self.stdout.write(f'  Updated {academic_years_updated} academic years')
                
                # Migrate Term
                terms_updated = Term.objects.filter(organization__isnull=True).update(organization=org)
                counts['terms'] = terms_updated
                self.stdout.write(f'  Updated {terms_updated} terms')
                
                # Migrate Department
                departments_updated = Department.objects.filter(organization__isnull=True).update(organization=org)
                counts['departments'] = departments_updated
                self.stdout.write(f'  Updated {departments_updated} departments')
                
                # Migrate Staff
                staff_updated = Staff.objects.filter(organization__isnull=True).update(organization=org)
                counts['staff'] = staff_updated
                self.stdout.write(f'  Updated {staff_updated} staff members')
                
                # Migrate Class
                classes_updated = Class.objects.filter(organization__isnull=True).update(organization=org)
                counts['classes'] = classes_updated
                self.stdout.write(f'  Updated {classes_updated} classes')
                
                # Migrate Subject
                subjects_updated = Subject.objects.filter(organization__isnull=True).update(organization=org)
                counts['subjects'] = subjects_updated
                self.stdout.write(f'  Updated {subjects_updated} subjects')
                
                # Migrate Exam
                exams_updated = Exam.objects.filter(organization__isnull=True).update(organization=org)
                counts['exams'] = exams_updated
                self.stdout.write(f'  Updated {exams_updated} exams')
                
                # Migrate Grade
                grades_updated = Grade.objects.filter(organization__isnull=True).update(organization=org)
                counts['grades'] = grades_updated
                self.stdout.write(f'  Updated {grades_updated} grades')
                
                # Migrate Attendance
                attendance_updated = Attendance.objects.filter(organization__isnull=True).update(organization=org)
                counts['attendance'] = attendance_updated
                self.stdout.write(f'  Updated {attendance_updated} attendance records')
                
                # Migrate Timetable
                timetables_updated = Timetable.objects.filter(organization__isnull=True).update(organization=org)
                counts['timetables'] = timetables_updated
                self.stdout.write(f'  Updated {timetables_updated} timetable entries')
                
                # Migrate FeeStructure
                fee_structures_updated = FeeStructure.objects.filter(organization__isnull=True).update(organization=org)
                counts['fee_structures'] = fee_structures_updated
                self.stdout.write(f'  Updated {fee_structures_updated} fee structures')
                
                # Migrate Discount
                discounts_updated = Discount.objects.filter(organization__isnull=True).update(organization=org)
                counts['discounts'] = discounts_updated
                self.stdout.write(f'  Updated {discounts_updated} discounts')
                
                # Migrate Invoice
                invoices_updated = Invoice.objects.filter(organization__isnull=True).update(organization=org)
                counts['invoices'] = invoices_updated
                self.stdout.write(f'  Updated {invoices_updated} invoices')
                
                # Migrate TransportRoute
                transport_routes_updated = TransportRoute.objects.filter(organization__isnull=True).update(organization=org)
                counts['transport_routes'] = transport_routes_updated
                self.stdout.write(f'  Updated {transport_routes_updated} transport routes')
                
                # Migrate TransportFee
                transport_fees_updated = TransportFee.objects.filter(organization__isnull=True).update(organization=org)
                counts['transport_fees'] = transport_fees_updated
                self.stdout.write(f'  Updated {transport_fees_updated} transport fees')
                
                # Migrate Payment
                payments_updated = Payment.objects.filter(organization__isnull=True).update(organization=org)
                counts['payments'] = payments_updated
                self.stdout.write(f'  Updated {payments_updated} payments')
                
                # Migrate ReportRequest
                report_requests_updated = ReportRequest.objects.filter(organization__isnull=True).update(organization=org)
                counts['report_requests'] = report_requests_updated
                self.stdout.write(f'  Updated {report_requests_updated} report requests')
                
                # Migrate OtherIncomeInvoice
                other_income_updated = OtherIncomeInvoice.objects.filter(organization__isnull=True).update(organization=org)
                counts['other_income_invoices'] = other_income_updated
                self.stdout.write(f'  Updated {other_income_updated} other income invoices')
                
                # Summary
                total = sum(counts.values())
                self.stdout.write(self.style.SUCCESS(f'\nMigration complete! Updated {total} records across {len(counts)} models.'))
                
        except Exception as e:
            logger.error(f"Error during migration: {str(e)}", exc_info=True)
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            raise

