# students/management/commands/import_students.py

import re
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import List, Optional, Tuple

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from academics.models import AcademicYear, Term, Class
from students.models import Student, Parent, StudentParent
from core.models import TermChoices

STREAM_EAST = "East"  # change if your Class.stream choices require something else


def normalize_class_key(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.upper()


def to_decimal(value) -> Decimal:
    """
    Safe conversion from pandas values (NaN, floats, strings) to Decimal.
    """
    if value is None:
        return Decimal("0.00")

    try:
        # pandas NaN handling
        if pd.isna(value):
            return Decimal("0.00")
    except Exception:
        pass

    s = str(value).strip().replace(",", "")
    if s == "" or s.lower() == "nan":
        return Decimal("0.00")

    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def normalize_ke_phone(digits_only: str) -> Optional[str]:
    """
    Convert to +254XXXXXXXXX format.
    Accepts:
      - 2547XXXXXXXX / 2541XXXXXXXX
      - 07XXXXXXXX / 01XXXXXXXX
      - 7XXXXXXXX / 1XXXXXXXX (9 digits)
    """
    d = re.sub(r"\D", "", digits_only or "")
    if not d:
        return None

    if d.startswith("254") and len(d) >= 12:
        d = d[:12]
        return f"+{d}"

    if d.startswith("0") and len(d) >= 10:
        d = d[:10]
        return f"+254{d[1:]}"

    if len(d) == 9 and (d.startswith("7") or d.startswith("1")):
        return f"+254{d}"

    return None


def extract_phones(contacts: str) -> List[str]:
    """
    Extract Kenyan phone numbers from messy contact strings.
    """
    text = contacts or ""
    phones: List[str] = []
    seen = set()

    patterns = [
        r"\+254\d{9}",
        r"\b254\d{9}\b",
        r"\b0\d{9}\b",
        r"\b[71]\d{8}\b",
    ]
    for pat in patterns:
        for m in re.findall(pat, text):
            p = normalize_ke_phone(m)
            if p and p not in seen:
                phones.append(p)
                seen.add(p)

    digits = re.sub(r"\D", "", text)
    for m in re.findall(r"254\d{9}", digits):
        p = normalize_ke_phone(m)
        if p and p not in seen:
            phones.append(p)
            seen.add(p)

    for m in re.findall(r"0\d{9}", digits):
        p = normalize_ke_phone(m)
        if p and p not in seen:
            phones.append(p)
            seen.add(p)

    return phones


class Command(BaseCommand):
    help = "Import students with credit balances from Excel file"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to Excel file")
        parser.add_argument("--dry-run", action="store_true", help="Parse and validate but roll back DB changes")
        parser.add_argument("--limit", type=int, default=0, help="Only import first N rows (0 = all)")

    def handle(self, *args, **options):
        file_path = options["file_path"]
        dry_run = options["dry_run"]
        limit = options["limit"] or 0

        self.stdout.write(self.style.NOTICE(f"Reading {file_path}..."))

        # Read Excel: your sheet has a top line then header row (Year, #, Name...)
        df = pd.read_excel(file_path)



        print("Columns found:", df.columns.tolist())
        print("First few rows:")
        print(df.head())
        df.columns = [str(c).strip() for c in df.columns]

        # Rename columns safely based on actual header row
        df = df.rename(
            columns={
                "Year": "Year",
                "#": "Admission_No",
                "Name": "Name",
                "Class": "Class",
                "Contacts": "Contacts",
                "Total Balance": "Total_Balance",
            }
        )

        required = [
            "Year",
            "Admission_No",
            "Name",
            "Class",
            "Contacts",
            "Total_Balance",  # Only this balance column exists
        ]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing expected columns in Excel: {missing}. Found: {list(df.columns)}")

        df = df.dropna(subset=["Admission_No"]).copy()
        df["Admission_No"] = df["Admission_No"].astype(str).str.strip()
        df["Name"] = df["Name"].astype(str).str.strip()
        df["Class"] = df["Class"].astype(str).str.strip()

        if limit > 0:
            df = df.head(limit)

        stats = {
            "students_created": 0,
            "students_updated": 0,
            "parents_created": 0,
            "rows_skipped": 0,
            "errors": 0,
        }

        with transaction.atomic():
            academic_year, _ = AcademicYear.objects.get_or_create(
                year=2025,
                defaults={
                    "start_date": date(2025, 1, 6),
                    "end_date": date(2025, 11, 28),
                    "is_current": True,
                },
            )

            term, _ = Term.objects.get_or_create(
                academic_year=academic_year,
                term=TermChoices.TERM_3,
                defaults={
                    "start_date": date(2025, 9, 1),
                    "end_date": date(2025, 11, 28),
                    "is_current": True,
                    "fee_deadline": date(2025, 9, 15),
                },
            )

            class_mapping = self.create_classes(academic_year)

            for _, row in df.iterrows():
                try:
                    self.import_row(row, class_mapping, term, stats)
                except Exception as e:
                    stats["errors"] += 1
                    adm = str(row.get("Admission_No", "")).strip()
                    self.stdout.write(self.style.ERROR(f"[{adm}] Import failed: {e}"))

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"""
Import Complete! {'(DRY RUN - rolled back)' if dry_run else ''}
----------------
Students created: {stats['students_created']}
Students updated: {stats['students_updated']}
Parents created: {stats['parents_created']}
Rows skipped: {stats['rows_skipped']}
Errors: {stats['errors']}
"""
            )
        )

    def create_classes(self, academic_year):
        """
        Create all classes and return mapping keyed by normalized Excel class names.
        """
        class_config = [
            ("PLAYGROUP", "pp1", STREAM_EAST),
            ("PP1", "pp1", STREAM_EAST),
            ("PP2", "pp2", STREAM_EAST),
            ("GRADE 1", "grade_1", STREAM_EAST),
            ("GRADE 2", "grade_2", STREAM_EAST),
            ("GRADE 3", "grade_3", STREAM_EAST),
            ("GRADE 4", "grade_4", STREAM_EAST),
            ("GRADE 5", "grade_5", STREAM_EAST),
            ("GRADE 6", "grade_6", STREAM_EAST),
            ("GRADE SEVEN-JSS", "grade_7", STREAM_EAST),
            ("GRADE EIGHT-JSS", "grade_8", STREAM_EAST),
            ("GRADE NINE-JSS", "grade_9", STREAM_EAST),
        ]

        mapping = {}
        for excel_name, grade_level, stream in class_config:
            key = normalize_class_key(excel_name)

            if key == "PLAYGROUP":
                display_name = "Playgroup"
            elif "JSS" in key:
                base = key.replace("-JSS", "").title()
                display_name = f"{base} (JSS)"
            else:
                display_name = key.title()

            class_obj, _ = Class.objects.get_or_create(
                name=display_name,
                academic_year=academic_year,
                defaults={
                    "grade_level": grade_level,
                    "stream": stream,
                    "capacity": 50,
                },
            )

            # Enforce stream if field exists / is editable
            try:
                if getattr(class_obj, "stream", None) != stream:
                    class_obj.stream = stream
                    class_obj.save(update_fields=["stream"])
            except Exception:
                pass

            mapping[key] = class_obj

        return mapping

    def import_row(self, row, class_mapping, term, stats):
        admission_no = str(row["Admission_No"]).strip()
        if not admission_no:
            stats["rows_skipped"] += 1
            return

        full_name = str(row["Name"]).strip()
        class_name = str(row["Class"]).strip()
        contacts = str(row["Contacts"]).strip() if pd.notna(row["Contacts"]) else ""

        # Name parsing
        name_parts = full_name.split()
        if len(name_parts) >= 3:
            first_name = name_parts[0]
            last_name = name_parts[-1]
            middle_name = " ".join(name_parts[1:-1])
        elif len(name_parts) == 2:
            first_name, last_name = name_parts
            middle_name = ""
        else:
            first_name = full_name
            last_name = ""
            middle_name = ""

        # Class mapping (robust)
        class_key = normalize_class_key(class_name)
        class_obj = class_mapping.get(class_key)
        if not class_obj:
            stats["rows_skipped"] += 1
            self.stdout.write(self.style.WARNING(f"Unknown class '{class_name}' for {admission_no}"))
            return

        # Get credit_balance from Excel
        credit_balance = to_decimal(row["Total_Balance"])  # This is the TOTAL_BALANCE column

        # Student upsert with credit_balance
        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                "first_name": first_name.title(),
                "middle_name": middle_name.title(),
                "last_name": last_name.title(),
                "current_class": class_obj,
                "credit_balance": credit_balance,  # Store the balance (+ve = debt, -ve = credit)
                "admission_date": date(2025, 1, 6),
                "date_of_birth": date(2015, 1, 1),  # placeholder
                "gender": "M",  # placeholder
                "status": "active",
            },
        )
        if created:
            stats["students_created"] += 1
        else:
            stats["students_updated"] += 1

        # Parent extraction/link
        if contacts and contacts.strip().lower() not in {"254", "nan"}:
            self.create_parent_from_contacts(student, contacts, stats)

    def create_parent_from_contacts(self, student, contacts, stats):
        phones = extract_phones(contacts)
        if not phones:
            return

        primary_phone = phones[0]
        secondary_phone = phones[1] if len(phones) > 1 else ""

        parent = Parent.objects.filter(phone_primary=primary_phone).first()
        if not parent:
            placeholder_first = student.last_name or student.first_name or "Parent"
            parent = Parent.objects.create(
                first_name=placeholder_first.title(),
                last_name="(Parent)",
                phone_primary=primary_phone,
                phone_secondary=secondary_phone,
                relationship="guardian",
            )
            stats["parents_created"] += 1

        StudentParent.objects.get_or_create(
            student=student,
            parent=parent,
            defaults={
                "relationship": "guardian",
                "is_primary": True,
                "receives_notifications": True,
            },
        )