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


def map_excel_class_to_db_class(excel_class_name: str, class_mapping: dict) -> Optional[Class]:
    """
    Map Excel class names to existing database classes.
    Handles various formats like 'GRADE 9 2025', 'GRADE 9 2035', 'GRADE 8 2025', etc.
    Maps all to 2025 classes.
    """
    excel_class = excel_class_name.strip().upper()
    
    # Remove any extra years from the class name (e.g., 'GRADE 9 2035' -> 'GRADE 9')
    # Also handle PP1, PP2, PlayGroup
    if excel_class.startswith("GRADE"):
        # Extract grade number
        parts = excel_class.split()
        if len(parts) >= 2:
            grade_num = parts[1]
            # Map to 'Grade X 2025' format
            db_class_name = f"Grade {grade_num} 2025"
            # Try to find in mapping
            for key, class_obj in class_mapping.items():
                if key.upper() == db_class_name.upper():
                    return class_obj
    elif excel_class.startswith("PP1"):
        # Look for PP1 2025
        for key, class_obj in class_mapping.items():
            if "PP1" in key.upper() and "2025" in key:
                return class_obj
    elif excel_class.startswith("PP2"):
        # Look for PP2 2025
        for key, class_obj in class_mapping.items():
            if "PP2" in key.upper() and "2025" in key:
                return class_obj
    elif "PLAYGROUP" in excel_class or "PP1" in excel_class:
        # Look for PlayGroup 2025 or PP1 2025
        for key, class_obj in class_mapping.items():
            if ("PLAYGROUP" in key.upper() or "PP1" in key.upper()) and "2025" in key:
                return class_obj
    elif "PP2" in excel_class:
        # Look for PP2 2025
        for key, class_obj in class_mapping.items():
            if "PP2" in key.upper() and "2025" in key:
                return class_obj
    
    return None


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
        Get existing classes for the academic year and create a mapping.
        Uses classes in format 'Grade 1 2025', 'PlayGroup 2025', 'PP1 2025', etc.
        """
        mapping = {}
        
        # Get all classes for the academic year
        existing_classes = Class.objects.filter(academic_year=academic_year)
        
        for class_obj in existing_classes:
            # Store mapping by class name
            key = class_obj.name.strip()
            mapping[key] = class_obj
            
            # Also store uppercase version for easier matching
            mapping[key.upper()] = class_obj
            
            # Store just the grade part (e.g., "Grade 1") for flexible matching
            if "2025" in key:
                grade_part = key.replace(" 2025", "").strip()
                mapping[grade_part.upper()] = class_obj
        
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

        # Class mapping
        class_obj = map_excel_class_to_db_class(class_name, class_mapping)
        
        if not class_obj:
            # Try direct lookup in mapping
            excel_class_upper = class_name.strip().upper()
            for key in class_mapping:
                if excel_class_upper in key.upper() or key.upper() in excel_class_upper:
                    class_obj = class_mapping[key]
                    break
        
        if not class_obj:
            stats["rows_skipped"] += 1
            self.stdout.write(self.style.WARNING(f"Unknown class '{class_name}' for {admission_no}"))
            return

        credit_balance = to_decimal(row["Total_Balance"])  # This is the TOTAL_BALANCE column
        
        # Set frozen original values based on Excel balance
        # These are term-start values that NEVER change during the term
        # Used by dashboard for consistent reporting
        balance_bf_original = credit_balance if credit_balance > 0 else Decimal('0.00')
        prepayment_original = abs(credit_balance) if credit_balance < 0 else Decimal('0.00')

        # Student upsert with credit_balance and frozen fields
        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                "first_name": first_name.title(),
                "middle_name": middle_name.title(),
                "last_name": last_name.title(),
                "current_class": class_obj,
                "credit_balance": credit_balance,  # Store the balance (+ve = debt, -ve = credit)
                "balance_bf_original": balance_bf_original,  # Frozen debt from previous term
                "prepayment_original": prepayment_original,  # Frozen prepayment from previous term
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