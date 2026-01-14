# students/management/commands/import_students.py

import re
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import Optional

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction

from academics.models import AcademicYear, Term, Class
from students.models import Student, Parent, StudentParent
from core.models import TermChoices


# =========================
# CONSTANTS
# =========================

ACADEMIC_YEAR_VALUE = 2025


GRADE_ALIASES = {
    "PLAYGROUP": "playgroup",
    "PG": "playgroup",

    "PP1": "pp1",
    "PRE PRIMARY 1": "pp1",

    "PP2": "pp2",
    "PRE PRIMARY 2": "pp2",

    "GRADE 1": "grade_1",
    "GRADE ONE": "grade_1",

    "GRADE 2": "grade_2",
    "GRADE TWO": "grade_2",

    "GRADE 3": "grade_3",
    "GRADE THREE": "grade_3",

    "GRADE 4": "grade_4",
    "GRADE FOUR": "grade_4",

    "GRADE 5": "grade_5",
    "GRADE FIVE": "grade_5",

    "GRADE 6": "grade_6",
    "GRADE SIX": "grade_6",

    "GRADE 7": "grade_7",
    "GRADE SEVEN": "grade_7",

    "GRADE 8": "grade_8",
    "GRADE EIGHT": "grade_8",

    "GRADE 9": "grade_9",
    "GRADE NINE": "grade_9",
}


# =========================
# HELPERS
# =========================

def to_decimal(value) -> Decimal:
    try:
        if pd.isna(value):
            return Decimal("0.00")
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip().upper()


def extract_grade_level(class_cell: str) -> Optional[str]:
    """
    Extract grade_level from messy Excel class values.
    """
    if not class_cell:
        return None

    text = normalize_text(class_cell)

    # Remove year
    text = re.sub(r"\b20\d{2}\b", "", text).strip()

    # Remove JSS noise
    text = text.replace("JSS", "").strip()

    # Try direct alias match
    for key, grade_level in GRADE_ALIASES.items():
        if text.startswith(key):
            return grade_level

    # Try numeric fallback (GRADE 7, GRADE 8)
    m = re.search(r"GRADE\s*(\d)", text)
    if m:
        return f"grade_{m.group(1)}"

    return None


# =========================
# COMMAND
# =========================

class Command(BaseCommand):
    help = "FINAL grade_level-based student importer (uses existing classes only)"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        file_path = options["file_path"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        df = pd.read_excel(file_path)
        df.columns = [str(c).strip() for c in df.columns]

        required = ["#", "Name", "Class", "Contacts", "Total Balance"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing column: {col}")

        df = df.rename(
            columns={
                "#": "Admission_No",
                "Total Balance": "Total_Balance",
            }
        )

        if limit:
            df = df.head(limit)

        stats = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "parents_created": 0,
        }

        with transaction.atomic():
            academic_year = AcademicYear.objects.get(year=ACADEMIC_YEAR_VALUE)

            term = Term.objects.get(
                academic_year=academic_year,
                term=TermChoices.TERM_3,
            )

            # Build EXISTING class map by grade_level
            class_map = {
                c.grade_level: c
                for c in Class.objects.filter(academic_year=academic_year)
            }

            self.stdout.write(self.style.NOTICE(
                f"Loaded classes: {list(class_map.keys())}"
            ))

            for idx, row in df.iterrows():
                admission_no = str(row["Admission_No"]).strip()
                full_name = str(row["Name"]).strip()
                class_raw = str(row["Class"]).strip()

                if not admission_no:
                    stats["skipped"] += 1
                    self.stdout.write(self.style.WARNING(
                        f"[ROW {idx}] Skipped: Missing admission number"
                    ))
                    continue

                grade_level = extract_grade_level(class_raw)

                if not grade_level:
                    stats["skipped"] += 1
                    self.stdout.write(self.style.WARNING(
                        f"[{admission_no}] Skipped: Cannot extract grade from '{class_raw}'"
                    ))
                    continue

                class_obj = class_map.get(grade_level)

                if not class_obj:
                    stats["skipped"] += 1
                    self.stdout.write(self.style.WARNING(
                        f"[{admission_no}] Skipped: No existing Class for grade_level '{grade_level}'"
                    ))
                    continue

                name_parts = full_name.split()
                first_name = name_parts[0]
                last_name = name_parts[-1] if len(name_parts) > 1 else ""

                credit_balance = to_decimal(row["Total_Balance"])

                student, created = Student.objects.update_or_create(
                    admission_number=admission_no,
                    defaults={
                        "first_name": first_name.title(),
                        "last_name": last_name.title(),
                        "current_class": class_obj,
                        "credit_balance": credit_balance,
                        "balance_bf_original": credit_balance if credit_balance > 0 else Decimal("0.00"),
                        "prepayment_original": abs(credit_balance) if credit_balance < 0 else Decimal("0.00"),
                        "admission_date": date(2025, 1, 6),
                        "date_of_birth": date(2015, 1, 1),
                        "gender": "M",
                        "status": "active",
                    },
                )

                stats["created" if created else "updated"] += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"""
IMPORT COMPLETE {'(DRY RUN)' if dry_run else ''}
---------------------------
Created: {stats['created']}
Updated: {stats['updated']}
Skipped: {stats['skipped']}
Parents created: {stats['parents_created']}
"""
        ))
