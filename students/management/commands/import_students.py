# students/management/commands/import_students.py

import re
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import List, Optional

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction

from academics.models import AcademicYear, Term, Class
from students.models import Student, Parent, StudentParent
from core.models import TermChoices

STREAM_EAST = "East"


# ----------------------------
# CLASS NORMALIZATION (FIX)
# ----------------------------

CLASS_ALIASES = {
    "PLAY GROUP": "PLAYGROUP",
    "PLAYGROUP": "PLAYGROUP",
    "PG": "PLAYGROUP",

    "PP1": "PP1",
    "PRE PRIMARY 1": "PP1",

    "PP2": "PP2",
    "PRE PRIMARY 2": "PP2",

    "GRADE 1": "GRADE 1",
    "GRADE 2": "GRADE 2",
    "GRADE 3": "GRADE 3",
    "GRADE 4": "GRADE 4",
    "GRADE 5": "GRADE 5",
    "GRADE 6": "GRADE 6",

    "GRADE 7": "GRADE SEVEN",
    "GRADE SEVEN": "GRADE SEVEN",
    "GRADE 8": "GRADE EIGHT",
    "GRADE EIGHT": "GRADE EIGHT",
    "GRADE 9": "GRADE NINE",
    "GRADE NINE": "GRADE NINE",
}


def normalize_excel_class(value: str) -> str:
    """
    Converts:
      'Grade 1 2025'   -> 'GRADE 1'
      'PlayGroup 2025' -> 'PLAYGROUP'
      'PP1 2025'       -> 'PP1'
    """
    if not value:
        return ""

    value = str(value).upper().strip()

    # Remove year (only dealing with 2025)
    value = re.sub(r"\b20\d{2}\b", "", value)

    # Normalize spacing
    value = re.sub(r"\s+", " ", value).strip()

    # Alias mapping
    return CLASS_ALIASES.get(value, value)


# ----------------------------
# HELPERS (UNCHANGED)
# ----------------------------

def to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    try:
        if pd.isna(value):
            return Decimal("0.00")
    except Exception:
        pass

    s = str(value).strip().replace(",", "")
    if not s or s.lower() == "nan":
        return Decimal("0.00")

    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def normalize_ke_phone(digits_only: str) -> Optional[str]:
    d = re.sub(r"\D", "", digits_only or "")
    if not d:
        return None

    if d.startswith("254") and len(d) >= 12:
        return f"+{d[:12]}"

    if d.startswith("0") and len(d) >= 10:
        return f"+254{d[1:10]}"

    if len(d) == 9 and d[0] in {"7", "1"}:
        return f"+254{d}"

    return None


def extract_phones(text: str) -> List[str]:
    phones, seen = [], set()
    patterns = [r"\+254\d{9}", r"\b254\d{9}\b", r"\b0\d{9}\b", r"\b[71]\d{8}\b"]

    for pat in patterns:
        for m in re.findall(pat, text or ""):
            p = normalize_ke_phone(m)
            if p and p not in seen:
                phones.append(p)
                seen.add(p)

    return phones


# ----------------------------
# COMMAND
# ----------------------------

class Command(BaseCommand):
    help = "Import students from Excel"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        df = pd.read_excel(options["file_path"])
        df.columns = [str(c).strip() for c in df.columns]

        required = ["Year", "#", "Name", "Class", "Contacts", "Total Balance"]
        df = df.rename(columns={"#": "Admission_No", "Total Balance": "Total_Balance"})

        df = df.dropna(subset=["Admission_No"])
        df["Class"] = df["Class"].astype(str)

        if options["limit"]:
            df = df.head(options["limit"])

        stats = {"students_created": 0, "students_updated": 0, "rows_skipped": 0}

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
                defaults={"is_current": True},
            )

            class_mapping = self.create_classes(academic_year)

            for _, row in df.iterrows():
                self.import_row(row, class_mapping, stats)

            if options["dry_run"]:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(f"Import complete: {stats}"))

    # ----------------------------
    # CLASS CREATION
    # ----------------------------

    def create_classes(self, academic_year):
        class_config = [
            ("PLAYGROUP", "pp1"),
            ("PP1", "pp1"),
            ("PP2", "pp2"),
            ("GRADE 1", "grade_1"),
            ("GRADE 2", "grade_2"),
            ("GRADE 3", "grade_3"),
            ("GRADE 4", "grade_4"),
            ("GRADE 5", "grade_5"),
            ("GRADE 6", "grade_6"),
            ("GRADE SEVEN", "grade_7"),
            ("GRADE EIGHT", "grade_8"),
            ("GRADE NINE", "grade_9"),
        ]

        mapping = {}
        for key, grade in class_config:
            display = key.title() if "GRADE" in key else key.capitalize()

            obj, _ = Class.objects.get_or_create(
                name=display,
                academic_year=academic_year,
                defaults={"grade_level": grade, "stream": STREAM_EAST},
            )

            mapping[key] = obj

        return mapping

    # ----------------------------
    # ROW IMPORT
    # ----------------------------

    def import_row(self, row, class_mapping, stats):
        admission_no = str(row["Admission_No"]).strip()
        class_raw = row["Class"]

        class_key = normalize_excel_class(class_raw)
        class_obj = class_mapping.get(class_key)

        if not class_obj:
            stats["rows_skipped"] += 1
            self.stdout.write(self.style.WARNING(
                f"Unknown class '{class_raw}' → '{class_key}'"
            ))
            return

        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                "first_name": row["Name"].split()[0].title(),
                "last_name": row["Name"].split()[-1].title(),
                "current_class": class_obj,
                "credit_balance": to_decimal(row["Total_Balance"]),
                "admission_date": date(2025, 1, 6),
                "date_of_birth": date(2015, 1, 1),
                "gender": "M",
                "status": "active",
            },
        )

        stats["students_created" if created else "students_updated"] += 1
