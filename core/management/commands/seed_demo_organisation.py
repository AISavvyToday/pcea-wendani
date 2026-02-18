"""
Django management command to seed sample test data for Demo Organisation (demoorg).

Adds sample data for all tables, scoped ONLY to Demo Organisation.
Other organisations are never touched.

Usage:
    python manage.py seed_demo_organisation           # Run for real
    python manage.py seed_demo_organisation --dry-run   # Preview only, no changes
"""

import logging
from datetime import date, datetime, timedelta, time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    Organization,
    UserRole,
    Gender,
    TermChoices,
    FeeCategory,
    PaymentMethod,
    PaymentStatus,
    PaymentSource,
    InvoiceStatus,
    AttendanceStatus,
    GradeLevel,
    StreamChoices,
)
from accounts.models import User
from students.models import Parent, Student, StudentParent
from students.services import StudentService
from academics.models import (
    AcademicYear,
    Term,
    Department,
    Staff,
    Class,
    Subject,
    ClassSubject,
    Exam,
    Grade,
    Attendance,
    Timetable,
    ReportCard,
    ReportCardItem,
    LeaveApplication,
)
from finance.models import (
    FeeStructure,
    FeeItem,
    Discount,
    Invoice,
    InvoiceItem,
)
from transport.models import TransportRoute, TransportFee
from payments.models import Payment
from communications.models import Announcement, NotificationTemplate
from reports.models import ReportRequest
from other_income.models import OtherIncomeInvoice, OtherIncomeItem, OtherIncomePayment
from payroll.models import (
    SalaryStructure,
    Allowance,
    Deduction,
    StaffSalary,
    PayrollPeriod,
    PayrollEntry,
    PayrollAllowance,
    PayrollDeduction,
    Payslip,
)
from students.models import DisciplineRecord, MedicalRecord

logger = logging.getLogger(__name__)

DEMO_ORG_CODE = "demoorg"
DEMO_ORG_NAME = "Demo Organisation"
DEMO_EMAIL_SUFFIX = "@demoorg.seed.local"  # Unique suffix to avoid conflicts


class Command(BaseCommand):
    help = "Seed sample test data for Demo Organisation (demoorg) only. Other orgs untouched."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be created without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        try:
            try:
                org = Organization.objects.filter(code=DEMO_ORG_CODE).first()
                if not org:
                    org = Organization.objects.filter(name=DEMO_ORG_NAME).first()
                if not org:
                    org, _ = Organization.objects.get_or_create(
                        code=DEMO_ORG_CODE,
                        defaults={
                            "name": DEMO_ORG_NAME,
                            "address": "Demo Address",
                            "phone": "+254700000000",
                            "email": "demo@demoorg.local",
                        },
                    )
                    self.stdout.write(self.style.SUCCESS(f"Created organization: {org.name} ({org.code})"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"Using organization: {org.name} ({org.code})"))
            except Exception as e:
                err_msg = str(e).lower()
                if "no such table" in err_msg or "operationalerror" in err_msg:
                    self.stdout.write(
                        self.style.ERROR(
                            "Database tables not found. Run: python manage.py migrate"
                        )
                    )
                    return
                raise

            if dry_run:
                with transaction.atomic():
                    self._seed_all(org, dry_run=True)
                    transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run complete - no changes persisted"))
            else:
                with transaction.atomic():
                    self._seed_all(org, dry_run=False)
                self.stdout.write(self.style.SUCCESS("Seed complete."))

        except Exception as e:
            logger.exception("Seed failed")
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
            raise

    def _seed_all(self, org, dry_run):
        """Create sample data for all tables, scoped to org."""
        stats = {}

        # 1. Academic year & term
        ay, created = AcademicYear.objects.get_or_create(
            year=2025,
            defaults={
                "start_date": date(2025, 1, 6),
                "end_date": date(2025, 11, 28),
                "is_current": True,
            },
        )
        if created:
            ay.organization = org
            ay.save()
        stats["academic_year"] = 1

        term, created = Term.objects.get_or_create(
            academic_year=ay,
            term=TermChoices.TERM_3,
            defaults={
                "start_date": date(2025, 9, 1),
                "end_date": date(2025, 11, 28),
                "is_current": True,
                "fee_deadline": date(2025, 9, 15),
            },
        )
        if created:
            term.organization = org
            term.save()
        stats["term"] = 1

        # 2. Users (admin, staff, parent)
        admin_email = f"demo_admin{DEMO_EMAIL_SUFFIX}"
        admin_user, created = User.objects.get_or_create(
            email=admin_email,
            defaults={
                "first_name": "Demo",
                "last_name": "Admin",
                "role": UserRole.SCHOOL_ADMIN,
                "organization": org,
                "is_staff": True,
                "is_active": True,
            },
        )
        if created:
            admin_user.set_password("DemoPass123!")
            admin_user.save()
        stats["users"] = 1

        staff_email = f"demo_teacher{DEMO_EMAIL_SUFFIX}"
        staff_user, created = User.objects.get_or_create(
            email=staff_email,
            defaults={
                "first_name": "Demo",
                "last_name": "Teacher",
                "role": UserRole.TEACHER,
                "organization": org,
                "is_staff": False,
                "is_active": True,
            },
        )
        if created:
            staff_user.set_password("DemoPass123!")
            staff_user.save()
        stats["users"] += 1

        # 3. Department (unique code per org - use DEMOORG prefix)
        dept, created = Department.objects.get_or_create(
            code="DEMOORG-DEPT-1",
            defaults={
                "name": "Demo Languages Department",
                "organization": org,
            },
        )
        if created:
            dept.organization = org
            dept.save()
        stats["departments"] = 1

        # 4. Staff (unique staff_number - use DEMOORG prefix)
        staff, created = Staff.objects.get_or_create(
            staff_number="DEMOORG-T-001",
            defaults={
                "user": staff_user,
                "organization": org,
                "staff_type": "teaching",
                "department": dept,
                "id_number": "DEMOORG-ID-001",
                "phone_number": "+254712345678",
                "date_joined": date(2024, 1, 15),
                "employment_type": "permanent",
                "status": "active",
            },
        )
        if created:
            staff.organization = org
            staff.save()
        dept.head = staff
        dept.save(update_fields=["head"])
        stats["staff"] = 1

        # 5. Class
        cls, created = Class.objects.get_or_create(
            name="Grade 5 East",
            academic_year=ay,
            defaults={
                "organization": org,
                "grade_level": GradeLevel.GRADE_5,
                "stream": StreamChoices.EAST,
                "class_teacher": staff,
                "room": "R101",
            },
        )
        if created:
            cls.organization = org
            cls.save()
        stats["classes"] = 1

        # 6. Subject (unique code - use DEMOORG prefix)
        subj, created = Subject.objects.get_or_create(
            code="DEMOORG-ENG",
            defaults={
                "name": "English",
                "organization": org,
                "department": dept,
                "grade_levels": ["grade_5", "grade_6"],
                "subject_type": "core",
                "max_marks": 100,
                "pass_marks": 40,
            },
        )
        if created:
            subj.organization = org
            subj.save()
        stats["subjects"] = 1

        # 7. ClassSubject
        ClassSubject.objects.get_or_create(
            class_obj=cls,
            subject=subj,
            defaults={"teacher": staff, "periods_per_week": 5},
        )
        stats["class_subjects"] = 1

        # 8. Parents (phone must match +254XXXXXXXXX)
        parent1, created = Parent.objects.get_or_create(
            phone_primary="+254711111101",
            organization=org,
            defaults={
                "first_name": "Demo",
                "last_name": "Parent1",
                "gender": "M",
                "email": f"demo_parent1{DEMO_EMAIL_SUFFIX}",
                "relationship": "father",
            },
        )
        if created:
            parent1.organization = org
            parent1.save()
        stats["parents"] = 1

        parent2, created = Parent.objects.get_or_create(
            phone_primary="+254722222202",
            organization=org,
            defaults={
                "first_name": "Demo",
                "last_name": "Parent2",
                "gender": "F",
                "email": f"demo_parent2{DEMO_EMAIL_SUFFIX}",
                "relationship": "mother",
            },
        )
        if created:
            parent2.organization = org
            parent2.save()
        stats["parents"] += 1

        # 9. Students
        adm_num = StudentService.generate_admission_number(organization=org)
        student1, created = Student.objects.get_or_create(
            admission_number=adm_num,
            organization=org,
            defaults={
                "first_name": "Demo",
                "middle_name": "",
                "last_name": "Student1",
                "gender": Gender.MALE,
                "date_of_birth": date(2015, 3, 15),
                "admission_date": date(2025, 1, 6),
                "current_class": cls,
                "status": "active",
                "emergency_contact_name": "Demo Parent1",
                "emergency_contact_phone": "+254711111101",
            },
        )
        if created:
            student1.organization = org
            student1.save()
        stats["students"] = 1

        adm_num2 = StudentService.generate_admission_number(organization=org)
        student2, created = Student.objects.get_or_create(
            admission_number=adm_num2,
            organization=org,
            defaults={
                "first_name": "Demo",
                "middle_name": "",
                "last_name": "Student2",
                "gender": Gender.FEMALE,
                "date_of_birth": date(2015, 7, 20),
                "admission_date": date(2025, 1, 6),
                "current_class": cls,
                "status": "active",
                "emergency_contact_name": "Demo Parent2",
                "emergency_contact_phone": "+254722222202",
            },
        )
        if created:
            student2.organization = org
            student2.save()
        stats["students"] += 1

        # 10. StudentParent
        StudentParent.objects.get_or_create(
            student=student1,
            parent=parent1,
            defaults={
                "relationship": "father",
                "is_primary": True,
                "receives_notifications": True,
            },
        )
        StudentParent.objects.get_or_create(
            student=student2,
            parent=parent2,
            defaults={
                "relationship": "mother",
                "is_primary": True,
                "receives_notifications": True,
            },
        )
        stats["student_parents"] = 2

        # 11. Transport
        route, created = TransportRoute.objects.get_or_create(
            name="Demo Route A",
            organization=org,
            defaults={"description": "Demo transport route", "pickup_points": "Point 1\nPoint 2"},
        )
        stats["transport_routes"] = 1

        TransportFee.objects.get_or_create(
            route=route,
            academic_year=ay,
            term=TermChoices.TERM_3,
            defaults={
                "organization": org,
                "amount": Decimal("5000.00"),
            },
        )
        stats["transport_fees"] = 1

        # 12. Fee structure
        fs, created = FeeStructure.objects.get_or_create(
            name="Demo Grade 5 Term 3 2025",
            academic_year=ay,
            term=TermChoices.TERM_3,
            organization=org,
            defaults={
                "grade_levels": ["grade_5"],
                "description": "Demo fee structure",
            },
        )
        if created:
            fs.organization = org
            fs.save(        )
        stats["fee_structures"] = 1

        FeeItem.objects.get_or_create(
            fee_structure=fs,
            category=FeeCategory.TUITION,
            description="Tuition",
            defaults={"amount": Decimal("15000.00"), "is_optional": False},
        )
        FeeItem.objects.get_or_create(
            fee_structure=fs,
            category=FeeCategory.MEALS,
            description="Lunch",
            defaults={"amount": Decimal("3000.00"), "is_optional": False},
        )
        stats["fee_items"] = 2

        # 13. Discount
        disc, created = Discount.objects.get_or_create(
            name="Demo Sibling Discount",
            organization=org,
            defaults={
                "discount_type": "percentage",
                "value": Decimal("5.00"),
                "academic_year": ay,
                "requires_approval": False,
            },
        )
        if created:
            disc.organization = org
            disc.save()
        stats["discounts"] = 1

        # 14. Invoice (invoice_number auto-generated by model)
        inv, created = Invoice.objects.get_or_create(
            student=student1,
            term=term,
            defaults={
                "organization": org,
                "subtotal": Decimal("18000.00"),
                "discount_amount": Decimal("0.00"),
                "total_amount": Decimal("18000.00"),
                "amount_paid": Decimal("5000.00"),
                "balance_bf": Decimal("0.00"),
                "prepayment": Decimal("0.00"),
                "balance": Decimal("13000.00"),
                "status": InvoiceStatus.PARTIALLY_PAID,
                "issue_date": date(2025, 9, 1),
                "due_date": date(2025, 9, 30),
                "fee_structure": fs,
                "generated_by": admin_user,
            },
        )
        if created:
            inv.organization = org
            inv.save()
        stats["invoices"] = 1

        # 15. InvoiceItem
        InvoiceItem.objects.get_or_create(
            invoice=inv,
            description="Tuition - Term 3",
            category=FeeCategory.TUITION,
            defaults={
                "amount": Decimal("15000.00"),
                "discount_applied": Decimal("0.00"),
                "net_amount": Decimal("15000.00"),
            },
        )
        InvoiceItem.objects.get_or_create(
            invoice=inv,
            description="Lunch - Term 3",
            category=FeeCategory.MEALS,
            defaults={
                "amount": Decimal("3000.00"),
                "discount_applied": Decimal("0.00"),
                "net_amount": Decimal("3000.00"),
            },
        )
        stats["invoice_items"] = 2

        # 16. Payment (fixed ref to avoid duplicates on re-run)
        pay_ref = "PAY-DEMO-SEED-001"
        pay, created = Payment.objects.get_or_create(
            payment_reference=pay_ref,
            defaults={
                "organization": org,
                "student": student1,
                "invoice": inv,
                "amount": Decimal("5000.00"),
                "payment_method": PaymentMethod.MOBILE_MONEY,
                "payment_source": PaymentSource.MPESA,
                "status": PaymentStatus.COMPLETED,
                "payment_date": timezone.now(),
                "payer_name": "Demo Parent1",
                "payer_phone": "+254711111101",
                "transaction_reference": "DEMO-MPESA-001",
                "received_by": admin_user,
            },
        )
        if created:
            pay.organization = org
            pay.save()
        stats["payments"] = 1

        # 17. Exam
        exam, created = Exam.objects.get_or_create(
            name="Demo Mid-Term Exam",
            term=term,
            defaults={
                "organization": org,
                "exam_type": "midterm",
                "start_date": date(2025, 10, 15),
                "end_date": date(2025, 10, 17),
                "weight_percentage": Decimal("30.00"),
                "is_published": True,
            },
        )
        if created:
            exam.organization = org
            exam.classes.add(cls)
            exam.save()
        stats["exams"] = 1

        # 18. Grade
        Grade.objects.get_or_create(
            student=student1,
            exam=exam,
            subject=subj,
            defaults={
                "organization": org,
                "marks": Decimal("72.50"),
                "entered_by": staff_user,
            },
        )
        stats["grades"] = 1

        # 19. Attendance
        att_date = date.today() - timedelta(days=1)
        Attendance.objects.get_or_create(
            student=student1,
            date=att_date,
            defaults={
                "organization": org,
                "class_obj": cls,
                "status": AttendanceStatus.PRESENT,
                "recorded_by": staff_user,
            },
        )
        Attendance.objects.get_or_create(
            student=student2,
            date=att_date,
            defaults={
                "organization": org,
                "class_obj": cls,
                "status": AttendanceStatus.PRESENT,
                "recorded_by": staff_user,
            },
        )
        stats["attendance"] = 2

        # 20. Timetable
        Timetable.objects.get_or_create(
            class_obj=cls,
            subject=subj,
            day_of_week=1,
            term=term,
            defaults={
                "organization": org,
                "teacher": staff,
                "start_time": time(8, 0),
                "end_time": time(8, 40),
                "room": "R101",
            },
        )
        stats["timetables"] = 1

        # 21. ReportCard
        rc, created = ReportCard.objects.get_or_create(
            student=student1,
            term=term,
            defaults={
                "organization": org,
                "academic_year": ay,
                "class_obj": cls,
                "overall_grade": "B+",
                "position": 5,
                "total_marks": Decimal("350.00"),
                "average_marks": Decimal("70.00"),
                "teacher_comments": "Good progress.",
                "principal_comments": "Keep it up.",
                "is_published": True,
                "generated_by": staff_user,
            },
        )
        if created:
            rc.organization = org
            rc.save()
        stats["report_cards"] = 1

        ReportCardItem.objects.get_or_create(
            report_card=rc,
            subject=subj,
            defaults={
                "marks": Decimal("72.50"),
                "grade": "B+",
                "remarks": "Good",
            },
        )
        stats["report_card_items"] = 1

        # 22. LeaveApplication
        LeaveApplication.objects.get_or_create(
            staff=staff,
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 3),
            defaults={
                "organization": org,
                "leave_type": "annual",
                "reason": "Demo leave application",
                "status": "approved",
                "approved_by": admin_user,
                "approved_at": timezone.now(),
            },
        )
        stats["leave_applications"] = 1

        # 23. Payroll
        sal_struct, created = SalaryStructure.objects.get_or_create(
            code="DEMOORG-SAL-1",
            defaults={
                "name": "Demo T-Scale 1",
                "organization": org,
                "basic_salary": Decimal("45000.00"),
            },
        )
        if created:
            sal_struct.organization = org
            sal_struct.save()
        stats["salary_structures"] = 1

        allow, created = Allowance.objects.get_or_create(
            name="Demo Housing",
            organization=org,
            defaults={
                "allowance_type": "housing",
                "amount": Decimal("15000.00"),
                "is_percentage": False,
            },
        )
        if created:
            allow.organization = org
            allow.save()
        stats["allowances"] = 1

        ded, created = Deduction.objects.get_or_create(
            name="Demo NHIF",
            organization=org,
            defaults={
                "deduction_type": "nhif",
                "amount": Decimal("500.00"),
                "is_percentage": False,
            },
        )
        if created:
            ded.organization = org
            ded.save()
        stats["deductions"] = 1

        staff_sal, created = StaffSalary.objects.get_or_create(
            staff=staff,
            defaults={
                "organization": org,
                "salary_structure": sal_struct,
                "effective_date": date(2024, 1, 15),
            },
        )
        if created:
            staff_sal.organization = org
            staff_sal.allowances.add(allow)
            staff_sal.deductions.add(ded)
            staff_sal.save()
        stats["staff_salaries"] = 1

        pp, created = PayrollPeriod.objects.get_or_create(
            organization=org,
            period_month=9,
            period_year=2025,
            defaults={
                "start_date": date(2025, 9, 1),
                "end_date": date(2025, 9, 30),
                "is_closed": False,
            },
        )
        if created:
            pp.organization = org
            pp.save()
        stats["payroll_periods"] = 1

        pe, created = PayrollEntry.objects.get_or_create(
            payroll_period=pp,
            staff=staff,
            defaults={
                "organization": org,
                "staff_salary": staff_sal,
                "basic_salary": Decimal("45000.00"),
                "total_allowances": Decimal("15000.00"),
                "gross_salary": Decimal("60000.00"),
                "total_deductions": Decimal("500.00"),
                "net_salary": Decimal("59500.00"),
                "nhif": Decimal("500.00"),
            },
        )
        if created:
            pe.organization = org
            pe.save()
        stats["payroll_entries"] = 1

        PayrollAllowance.objects.get_or_create(
            payroll_entry=pe,
            allowance=allow,
            defaults={"amount": Decimal("15000.00")},
        )
        PayrollDeduction.objects.get_or_create(
            payroll_entry=pe,
            deduction=ded,
            defaults={"amount": Decimal("500.00")},
        )
        stats["payroll_allowances"] = 1
        stats["payroll_deductions"] = 1

        Payslip.objects.get_or_create(
            payroll_entry=pe,
            defaults={
                "organization": org,
                "generated_by": admin_user,
            },
        )
        stats["payslips"] = 1

        # 24. Announcement
        ann, created = Announcement.objects.get_or_create(
            title="Demo Welcome Announcement",
            organization=org,
            defaults={
                "message": "Welcome to the demo school. This is sample data.",
                "target_audience": "all",
                "send_sms": False,
                "send_email": False,
                "is_sent": False,
                "created_by": admin_user,
            },
        )
        if created:
            ann.organization = org
            ann.save()
        stats["announcements"] = 1

        # 25. NotificationTemplate
        NotificationTemplate.objects.get_or_create(
            organization=org,
            name="Demo Fee Reminder",
            template_type="sms",
            defaults={
                "template_text": "Dear {{parent_name}}, fee reminder for {{student_name}}: {{amount}} due {{due_date}}.",
                "variables": ["parent_name", "student_name", "amount", "due_date"],
            },
        )
        stats["notification_templates"] = 1

        # 26. ReportRequest
        ReportRequest.objects.get_or_create(
            organization=org,
            report_type="invoice_summary",
            academic_year=ay,
            term=TermChoices.TERM_3,
            created_by=admin_user,
            defaults={"params": {}, "note": "Demo report request"},
        )
        stats["report_requests"] = 1

        # 27. OtherIncomeInvoice (invoice_number auto-generated by model)
        oinv = OtherIncomeInvoice.objects.filter(
            organization=org,
            client_name="Demo Client",
            description="Demo bus hire",
        ).first()
        if not oinv:
            oinv = OtherIncomeInvoice.objects.create(
                organization=org,
                client_name="Demo Client",
                client_contact="+254733333303",
                description="Demo bus hire",
                subtotal=Decimal("10000.00"),
                total_amount=Decimal("10000.00"),
                amount_paid=Decimal("0.00"),
                balance=Decimal("10000.00"),
                status="unpaid",
                issue_date=date.today(),
                generated_by=admin_user,
            )
        if created:
            oinv.organization = org
            oinv.save()
        stats["other_income_invoices"] = 1

        OtherIncomeItem.objects.get_or_create(
            invoice=oinv,
            description="Bus hire - 1 day",
            defaults={"amount": Decimal("10000.00")},
        )
        stats["other_income_items"] = 1

        # 28. DisciplineRecord
        DisciplineRecord.objects.get_or_create(
            student=student1,
            incident_date=date(2025, 9, 10),
            incident_type="positive",
            defaults={
                "description": "Excellent class participation",
                "action_taken": "Commendation",
                "reported_by": staff_user,
            },
        )
        stats["discipline_records"] = 1

        # 29. MedicalRecord
        MedicalRecord.objects.get_or_create(
            student=student1,
            record_date=date(2025, 8, 15),
            record_type="checkup",
            defaults={
                "description": "Routine health checkup - all clear",
                "treatment": "None required",
                "recorded_by": staff_user,
            },
        )
        stats["medical_records"] = 1

        # Summary
        for model_name, count in sorted(stats.items()):
            self.stdout.write(f"  {model_name}: {count}")
