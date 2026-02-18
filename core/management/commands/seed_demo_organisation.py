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
from payments.models import Payment, BankTransaction
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

# Realistic Kenyan names for demo data
REALISTIC_STUDENTS = [
    ("James", "Otieno", "M", date(2015, 3, 15)),
    ("Mary", "Wanjiku", "F", date(2015, 7, 20)),
    ("Peter", "Kamau", "M", date(2014, 11, 8)),
    ("Grace", "Njeri", "F", date(2015, 1, 12)),
    ("David", "Ochieng", "M", date(2014, 5, 22)),
    ("Faith", "Wambui", "F", date(2015, 9, 3)),
    ("Joseph", "Kipchoge", "M", date(2014, 2, 28)),
    ("Lucy", "Muthoni", "F", date(2015, 7, 14)),
]
REALISTIC_PARENTS = [
    ("John", "Ochieng", "M", "+254711111101", "father"),
    ("Elizabeth", "Muthoni", "F", "+254722222202", "mother"),
    ("Robert", "Kamau", "M", "+254733333303", "father"),
    ("Catherine", "Wanjiku", "F", "+254744444404", "mother"),
    ("Michael", "Otieno", "M", "+254755555505", "father"),
    ("Anne", "Njeri", "F", "+254766666606", "mother"),
    ("Daniel", "Kipchoge", "M", "+254777777707", "father"),
    ("Sarah", "Wambui", "F", "+254788888808", "mother"),
]


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
                "organization": org,
                "start_date": date(2025, 9, 1),
                "end_date": date(2025, 11, 28),
                "is_current": True,
                "fee_deadline": date(2025, 9, 15),
            },
        )
        # Ensure demo org's term is current for dashboard (shared term may exist from another org)
        term.organization = org
        term.is_current = True
        term.save()
        stats["term"] = 1

        # 2. Users (admin, staff) - realistic Kenyan names
        admin_email = f"admin{DEMO_EMAIL_SUFFIX}"
        admin_user, created = User.objects.get_or_create(
            email=admin_email,
            defaults={
                "first_name": "Samuel",
                "last_name": "Kariuki",
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

        staff_email = f"teacher{DEMO_EMAIL_SUFFIX}"
        staff_user, created = User.objects.get_or_create(
            email=staff_email,
            defaults={
                "first_name": "Margaret",
                "last_name": "Wambui",
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

        # 3. Department (code max_length=10)
        dept, created = Department.objects.get_or_create(
            code="DEMO-D1",
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

        # 6. Subject (code max_length=10)
        subj, created = Subject.objects.get_or_create(
            code="DEMO-ENG",
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

        # 8. Parents (phone must match +254XXXXXXXXX) - realistic Kenyan names
        parents = []
        for i, (pf, pl, pg, phone, rel) in enumerate(REALISTIC_PARENTS):
            p, created = Parent.objects.get_or_create(
                phone_primary=phone,
                organization=org,
                defaults={
                    "first_name": pf,
                    "last_name": pl,
                    "gender": pg,
                    "email": f"parent_{i+1}{DEMO_EMAIL_SUFFIX}",
                    "relationship": rel,
                },
            )
            if created:
                p.organization = org
                p.save()
            parents.append(p)
        stats["parents"] = len(parents)

        # 9. Students - 8 active, 1 graduated, 1 transferred (realistic Kenyan names)
        # Dashboard stats: balance_bf_original, prepayment_original for Bal B/F and Prepayments
        # Fixed admission numbers for idempotent re-runs
        students_active = []
        for i, (sf, sl, sg, dob) in enumerate(REALISTIC_STUDENTS):
            adm_num = f"DEMO-{i+1:03d}"
            # Vary balance_bf and prepayment for dashboard: some have balance, some have prepay
            bal_bf = Decimal("5000.00") if i % 3 == 0 else Decimal("0.00")  # 3 students with balance
            prepay = Decimal("3000.00") if i % 3 == 1 else Decimal("0.00")  # 3 students with prepay
            s, created = Student.objects.get_or_create(
                admission_number=adm_num,
                organization=org,
                defaults={
                    "first_name": sf,
                    "middle_name": "",
                    "last_name": sl,
                    "gender": sg,
                    "date_of_birth": dob,
                    "admission_date": term.start_date if i < 2 else date(2025, 1, 6),  # 2 new in term
                    "current_class": cls,
                    "status": "active",
                    "balance_bf_original": bal_bf,
                    "prepayment_original": prepay,
                    "emergency_contact_name": f"{parents[i].first_name} {parents[i].last_name}",
                    "emergency_contact_phone": parents[i].phone_primary,
                },
            )
            if created:
                s.organization = org
                s.save()
            students_active.append(s)
            StudentParent.objects.get_or_create(
                student=s,
                parent=parents[i],
                defaults={
                    "relationship": parents[i].relationship,
                    "is_primary": True,
                    "receives_notifications": True,
                },
            )
        stats["students"] = len(students_active)

        # Graduated and transferred students (for dashboard helper stats)
        student_graduated, _ = Student.objects.get_or_create(
            admission_number="DEMO-GRAD-1",
            organization=org,
            defaults={
                "first_name": "Brian",
                "middle_name": "",
                "last_name": "Mwangi",
                "gender": "M",
                "date_of_birth": date(2010, 4, 10),
                "admission_date": date(2018, 1, 6),
                "current_class": cls,
                "status": "graduated",
                "balance_bf_original": Decimal("0.00"),
                "prepayment_original": Decimal("0.00"),
                "emergency_contact_name": "Joseph Mwangi",
                "emergency_contact_phone": "+254799999901",
            },
        )
        p_graduated, _ = Parent.objects.get_or_create(
            phone_primary="+254799999901",
            organization=org,
            defaults={
                "first_name": "Joseph",
                "last_name": "Mwangi",
                "gender": "M",
                "relationship": "father",
            },
        )
        StudentParent.objects.get_or_create(
            student=student_graduated,
            parent=p_graduated,
            defaults={"relationship": "father", "is_primary": True},
        )
        stats["students"] += 1

        student_transferred, _ = Student.objects.get_or_create(
            admission_number="DEMO-TRF-1",
            organization=org,
            defaults={
                "first_name": "Nancy",
                "middle_name": "",
                "last_name": "Akinyi",
                "gender": "F",
                "date_of_birth": date(2012, 8, 15),
                "admission_date": date(2020, 1, 6),
                "current_class": cls,
                "status": "transferred",
                "balance_bf_original": Decimal("0.00"),
                "prepayment_original": Decimal("0.00"),
                "emergency_contact_name": "Paul Akinyi",
                "emergency_contact_phone": "+254799999902",
            },
        )
        p_transferred, _ = Parent.objects.get_or_create(
            phone_primary="+254799999902",
            organization=org,
            defaults={
                "first_name": "Paul",
                "last_name": "Akinyi",
                "gender": "M",
                "relationship": "father",
            },
        )
        StudentParent.objects.get_or_create(
            student=student_transferred,
            parent=p_transferred,
            defaults={"relationship": "father", "is_primary": True},
        )
        stats["students"] += 1

        stats["student_parents"] = len(students_active) + 2

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
            fs.save()
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

        # 14. Invoices for active students (dashboard: Billed, Collected, Outstanding)
        # Create invoices for first 6 active students with varied amounts
        inv_configs = [
            (Decimal("18000.00"), Decimal("8000.00")),   # James - partial
            (Decimal("18000.00"), Decimal("18000.00")),  # Mary - fully paid
            (Decimal("18000.00"), Decimal("5000.00")),   # Peter - partial
            (Decimal("18000.00"), Decimal("0.00")),      # Grace - unpaid
            (Decimal("18000.00"), Decimal("12000.00")), # David - partial
            (Decimal("18000.00"), Decimal("0.00")),      # Faith - unpaid
        ]
        for i, (total, paid) in enumerate(inv_configs):
            if i >= len(students_active):
                break
            s = students_active[i]
            inv, created = Invoice.objects.get_or_create(
                student=s,
                term=term,
                defaults={
                    "organization": org,
                    "subtotal": total,
                    "discount_amount": Decimal("0.00"),
                    "total_amount": total,
                    "amount_paid": paid,
                    "balance_bf": Decimal("0.00"),
                    "prepayment": Decimal("0.00"),
                    "balance": total - paid,
                    "status": InvoiceStatus.PAID if paid >= total else (
                        InvoiceStatus.PARTIALLY_PAID if paid > 0 else InvoiceStatus.OVERDUE
                    ),
                    "issue_date": date(2025, 9, 1),
                    "due_date": date(2025, 9, 30),
                    "fee_structure": fs,
                    "generated_by": admin_user,
                },
            )
            if created:
                inv.organization = org
                inv.save()
            InvoiceItem.objects.get_or_create(
                invoice=inv,
                description="Tuition - Term 3",
                category=FeeCategory.TUITION,
                defaults={
                    "amount": total * Decimal("0.83"),
                    "discount_applied": Decimal("0.00"),
                    "net_amount": total * Decimal("0.83"),
                },
            )
            InvoiceItem.objects.get_or_create(
                invoice=inv,
                description="Lunch - Term 3",
                category=FeeCategory.MEALS,
                defaults={
                    "amount": total * Decimal("0.17"),
                    "discount_applied": Decimal("0.00"),
                    "net_amount": total * Decimal("0.17"),
                },
            )
        stats["invoices"] = min(6, len(students_active))
        stats["invoice_items"] = stats["invoices"] * 2

        # 16. Payments (for Collected stat - must match invoice amount_paid)
        pay_configs = [
            (0, "PAY-DEMO-SEED-001", Decimal("8000.00")),
            (1, "PAY-DEMO-SEED-002", Decimal("18000.00")),
            (2, "PAY-DEMO-SEED-003", Decimal("5000.00")),
            (4, "PAY-DEMO-SEED-004", Decimal("12000.00")),
        ]
        for idx, ref, amt in pay_configs:
            if idx >= len(students_active):
                continue
            inv = Invoice.objects.filter(student=students_active[idx], term=term).first()
            if not inv:
                continue
            pay, created = Payment.objects.get_or_create(
                payment_reference=ref,
                defaults={
                    "organization": org,
                    "student": students_active[idx],
                    "invoice": inv,
                    "amount": amt,
                    "payment_method": PaymentMethod.MOBILE_MONEY,
                    "payment_source": PaymentSource.MPESA,
                    "status": PaymentStatus.COMPLETED,
                    "payment_date": timezone.now(),
                    "payer_name": f"{parents[idx].first_name} {parents[idx].last_name}",
                    "payer_phone": parents[idx].phone_primary,
                    "transaction_reference": f"DEMO-MPESA-{idx+1:03d}",
                    "received_by": admin_user,
                },
            )
            if created:
                pay.organization = org
                pay.save()
        stats["payments"] = len(pay_configs)

        # 16b. BankTransactions - matched (linked to payments) and unmatched
        payments_created = list(
            Payment.objects.filter(
                payment_reference__in=[c[1] for c in pay_configs],
                organization=org,
            )
        )
        for i, pay in enumerate(payments_created[:4]):
            txn_id = f"DEMO-MPESA-{pay.payment_reference}-{i}"
            BankTransaction.objects.get_or_create(
                transaction_id=txn_id,
                defaults={
                    "payment": pay,
                    "gateway": "mpesa",
                    "amount": pay.amount,
                    "currency": "KES",
                    "payer_account": pay.payer_phone or "+254700000000",
                    "payer_name": pay.payer_name or "Demo Payer",
                    "bank_status": "Completed",
                    "processing_status": "matched",
                },
            )
        # Unmatched bank transactions (for dashboard "Unmatched Bank Txns" stat)
        unmatched_configs = [
            ("DEMO-EQ-UNM-001", "equity", Decimal("15000.00"), "John Ochieng"),
            ("DEMO-EQ-UNM-002", "equity", Decimal("8500.00"), "Catherine Wanjiku"),
            ("DEMO-COOP-UNM-001", "coop", Decimal("12000.00"), "Robert Kamau"),
            ("DEMO-MPESA-UNM-001", "mpesa", Decimal("5000.00"), "Anne Njeri"),
            ("DEMO-EQ-UNM-003", "equity", Decimal("22000.00"), "Michael Otieno"),
        ]
        for txn_id, gateway, amt, pname in unmatched_configs:
            BankTransaction.objects.get_or_create(
                transaction_id=txn_id,
                defaults={
                    "payment": None,
                    "gateway": gateway,
                    "amount": amt,
                    "currency": "KES",
                    "payer_account": "+254712345678",
                    "payer_name": pname,
                    "bank_status": "Completed",
                    "processing_status": "received",
                },
            )
        stats["bank_transactions"] = len(payments_created) + len(unmatched_configs)

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
            student=students_active[0],
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
            student=students_active[0],
            date=att_date,
            defaults={
                "organization": org,
                "class_obj": cls,
                "status": AttendanceStatus.PRESENT,
                "recorded_by": staff_user,
            },
        )
        Attendance.objects.get_or_create(
            student=students_active[1],
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
            student=students_active[0],
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
        stats["other_income_invoices"] = 1

        OtherIncomeItem.objects.get_or_create(
            invoice=oinv,
            description="Bus hire - 1 day",
            defaults={"amount": Decimal("10000.00")},
        )
        stats["other_income_items"] = 1

        # 28. DisciplineRecord
        DisciplineRecord.objects.get_or_create(
            student=students_active[0],
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
            student=students_active[0],
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
