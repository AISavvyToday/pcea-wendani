# students/management/commands/import_students.py

import re
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import List, Optional, Dict

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from academics.models import AcademicYear, Term, Class
from students.models import Student, Parent, StudentParent
from core.models import TermChoices

STREAM_EAST = "East"


def normalize_class_key(value: str) -> str:
    """Normalize class name for consistent matching."""
    if not value or pd.isna(value):
        return ""
    
    value = str(value).strip()
    
    # Remove extra spaces
    value = re.sub(r"\s+", " ", value)
    
    # Convert to uppercase for consistent comparison
    value = value.upper()
    
    return value


def extract_grade_and_year(class_str: str) -> tuple:
    """
    Extract grade level and year from class string.
    Returns (grade_level, year) tuple.
    """
    class_str = str(class_str).upper().strip()
    
    # Extract year (last 4 digits)
    year_match = re.search(r'(20\d{2})', class_str)
    year = year_match.group(1) if year_match else "2025"
    
    # Check for PP/PlayGroup first
    if "PLAYGROUP" in class_str or "PP1" in class_str or "PP2" in class_str:
        if "PP1" in class_str:
            return "pp1", year
        elif "PP2" in class_str:
            return "pp2", year
        else:
            # Default to pp1 for PlayGroup
            return "pp1", year
    
    # Check for grades
    grade_match = re.search(r'GRADE\s*(\d+)', class_str)
    if grade_match:
        grade_num = int(grade_match.group(1))
        if 1 <= grade_num <= 6:
            return f"grade_{grade_num}", year
        elif grade_num == 7:
            return "grade_7", year
        elif grade_num == 8:
            return "grade_8", year
        elif grade_num == 9:
            return "grade_9", year
    
    # Default to grade 1 if no match
    return "grade_1", year


def get_display_class_name(grade_level: str, year: str) -> str:
    """Get the display name for the class based on grade level and year."""
    # Map grade level to display name format
    if grade_level == "pp1":
        return f"PP1 {year}"
    elif grade_level == "pp2":
        return f"PP2 {year}"
    elif grade_level == "play_group":
        return f"PlayGroup {year}"
    elif grade_level.startswith("grade_"):
        grade_num = grade_level.split("_")[1]
        return f"Grade {grade_num} {year}"
    else:
        return f"Grade 1 {year}"  # Default


def to_decimal(value) -> Decimal:
    """Safe conversion from pandas values to Decimal."""
    if value is None:
        return Decimal("0.00")

    try:
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
    """Convert to +254XXXXXXXXX format."""
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
    """Extract Kenyan phone numbers from messy contact strings."""
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

        # Read Excel
        df = pd.read_excel(file_path)
        
        # Clean column names
        df.columns = [str(c).strip() for c in df.columns]
        
        # Rename columns based on actual header
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

        # Verify required columns exist
        required = [
            "Year",
            "Admission_No",
            "Name",
            "Class",
            "Contacts",
            "Total_Balance",
        ]
        
        # Try to find columns with different names
        column_mapping = {}
        for req in required:
            if req not in df.columns:
                # Try to find similar columns
                for col in df.columns:
                    if req.lower() in col.lower() or col.lower() in req.lower():
                        column_mapping[req] = col
                        break
        
        # Apply mapping if found
        if column_mapping:
            df = df.rename(columns={v: k for k, v in column_mapping.items()})
        
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing expected columns in Excel: {missing}. Found: {list(df.columns)}")

        # Clean data
        df = df.dropna(subset=["Admission_No"]).copy()
        df["Admission_No"] = df["Admission_No"].astype(str).str.strip()
        df["Name"] = df["Name"].astype(str).str.strip()
        df["Class"] = df["Class"].astype(str).str.strip()
        
        # Fill missing years with 2025
        if "Year" in df.columns:
            df["Year"] = df["Year"].fillna(2025).astype(int)

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
            # Get or create academic year (use 2025 from Excel or default to 2025)
            year_from_data = df["Year"].iloc[0] if not df.empty else 2025
            academic_year, _ = AcademicYear.objects.get_or_create(
                year=year_from_data,
                defaults={
                    "start_date": date(year_from_data, 1, 6),
                    "end_date": date(year_from_data, 11, 28),
                    "is_current": True,
                },
            )

            term, _ = Term.objects.get_or_create(
                academic_year=academic_year,
                term=TermChoices.TERM_3,
                defaults={
                    "start_date": date(year_from_data, 9, 1),
                    "end_date": date(year_from_data, 11, 28),
                    "is_current": True,
                    "fee_deadline": date(year_from_data, 9, 15),
                },
            )

            for _, row in df.iterrows():
                try:
                    self.import_row(row, academic_year, term, stats)
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

    def import_row(self, row, academic_year, term, stats):
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

        # Get or create class
        class_obj = self.get_or_create_class(class_name, academic_year)
        if not class_obj:
            stats["rows_skipped"] += 1
            self.stdout.write(self.style.WARNING(f"Unknown class '{class_name}' for {admission_no}"))
            return

        credit_balance = to_decimal(row["Total_Balance"])
        
        # Set frozen original values
        balance_bf_original = credit_balance if credit_balance > 0 else Decimal('0.00')
        prepayment_original = abs(credit_balance) if credit_balance < 0 else Decimal('0.00')

        # Student upsert
        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                "first_name": first_name.title(),
                "middle_name": middle_name.title(),
                "last_name": last_name.title(),
                "current_class": class_obj,
                "credit_balance": credit_balance,
                "balance_bf_original": balance_bf_original,
                "prepayment_original": prepayment_original,
                "admission_date": date(academic_year.year, 1, 6),
                "date_of_birth": date(academic_year.year - 6, 1, 1),  # placeholder
                "gender": "M",  # placeholder (you might want to improve this)
                "status": "active",
            },
        )
        
        if created:
            stats["students_created"] += 1
        else:
            stats["students_updated"] += 1

        # Parent extraction/link
        if contacts and contacts.strip().lower() not in {"254", "nan", ""}:
            self.create_parent_from_contacts(student, contacts, stats)

    def get_or_create_class(self, class_name: str, academic_year) -> Optional[Class]:
        """Get or create class based on class name from Excel."""
        if not class_name or pd.isna(class_name):
            return None
        
        # Extract grade level and year
        grade_level, year = extract_grade_and_year(class_name)
        
        # Get display name
        display_name = get_display_class_name(grade_level, str(academic_year.year))
        
        # Try to find existing class
        class_obj = Class.objects.filter(
            name__iexact=display_name,
            academic_year=academic_year
        ).first()
        
        if not class_obj:
            # Create new class
            class_obj = Class.objects.create(
                name=display_name,
                grade_level=grade_level,
                stream=STREAM_EAST,
                academic_year=academic_year,
            )
            self.stdout.write(self.style.NOTICE(f"Created new class: {display_name}"))
        
        return class_obj

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