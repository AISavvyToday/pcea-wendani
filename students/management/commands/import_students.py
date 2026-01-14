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


# -------------------------------------------------
# CLASS NORMALIZATION (EXCEL + DB)
# -------------------------------------------------

def normalize_excel_class(value: str) -> str:
    """
    Normalizes BOTH Excel class names and DB class names.

    Examples:
      "Grade 1 2025"   -> "GRADE 1"
      "PP1 2025"       -> "PP1"
      "PlayGroup 2025" -> "PLAYGROUP"
    """
    if not value:
        return ""

    value = str(value).upper().strip()

    # Remove year (we only deal with 2025)
    value = re.sub(r"\b20\d{2}\b", "", value)

    # Normalize spacing
    value = re.sub(r"\s+", " ", value).strip()

    return value


# -------------------------------------------------
# HELPERS (UNCHANGED LOGIC)
# -------------------------------------------------

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


# -------------------------------------------------
# COMMAND
# -------------------------------------------------

class Command(BaseCommand):
    help = "Import students from Excel (STRICT class matching, 2025 only)"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        file_path = options["file_path"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        self.stdout.write(self.style.NOTICE(f"Reading file: {file_path}"))

        df = pd.read_excel(file_path)
        df.columns = [str(c).strip() for c in df.columns]

        df = df.rename(columns={
            "#": "Admission_No",
            "Total Balance": "Total_Balance",
        })

        required = ["Admission_No", "Name", "Class", "Contacts", "Total_Balance"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        df = df.dropna(subset=["Admission_No"])
        df["Admission_No"] = df["Admission_No"].astype(str).str.strip()
        df["Class"] = df["Class"].astype(str).str.strip()

        if limit:
            df = df.head(limit)

        stats = {
            "students_created": 0,
            "students_updated": 0,
            "parents_created": 0,
            "rows_skipped": 0,
        }

        with transaction.atomic():
            academic_year = AcademicYear.objects.get(year=2025)

            term, _ = Term.objects.get_or_create(
                academic_year=academic_year,
                term=TermChoices.TERM_3,
                defaults={"is_current": True},
            )

            # 🔑 LOAD EXISTING CLASSES ONLY
            class_mapping = self.load_existing_classes(academic_year)

            for idx, row in df.iterrows():
                self.import_row(idx + 2, row, class_mapping, stats)

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"""
IMPORT COMPLETE {'(DRY RUN)' if dry_run else ''}
---------------------------------
Students created : {stats['students_created']}
Students updated : {stats['students_updated']}
Parents created  : {stats['parents_created']}
Rows skipped     : {stats['rows_skipped']}
"""
        ))

    # -------------------------------------------------
    # CLASS LOADER (NO CREATION)
    # -------------------------------------------------

    def load_existing_classes(self, academic_year):
        mapping = {}
        classes = Class.objects.filter(academic_year=academic_year)

        for cls in classes:
            key = normalize_excel_class(cls.name)

            if key in mapping:
                self.stdout.write(self.style.WARNING(
                    f"Duplicate class key '{key}' -> {cls.name}"
                ))
                continue

            mapping[key] = cls

        self.stdout.write(self.style.NOTICE(
            f"Loaded {len(mapping)} existing classes for matching"
        ))

        return mapping

    # -------------------------------------------------
    # ROW IMPORT WITH LOGGING
    # -------------------------------------------------

    def import_row(self, excel_row_no, row, class_mapping, stats):
        admission_no = row["Admission_No"]
        class_raw = row["Class"]

        normalized = normalize_excel_class(class_raw)
        class_obj = class_mapping.get(normalized)

        if not class_obj:
            stats["rows_skipped"] += 1
            self.stdout.write(self.style.ERROR(
                f"[ROW {excel_row_no}] SKIPPED | ADM: {admission_no} | "
                f"Class '{class_raw}' → '{normalized}' NOT FOUND IN DB"
            ))
            return

        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                "first_name": row["Name"].split()[0].title(),
                "last_name": row["Name"].split()[-1].title(),
                "current_class": class_obj,
                "credit_balance": to_decimal(row["Total_Balance"]),
                "balance_bf_original": max(to_decimal(row["Total_Balance"]), Decimal("0.00")),
                "prepayment_original": abs(min(to_decimal(row["Total_Balance"]), Decimal("0.00"))),
                "admission_date": date(2025, 1, 6),
                "date_of_birth": date(2015, 1, 1),
                "gender": "M",
                "status": "active",
            },
        )

        stats["students_created" if created else "students_updated"] += 1

        # Parent linking (unchanged)
        contacts = str(row["Contacts"]) if pd.notna(row["Contacts"]) else ""
        phones = extract_phones(contacts)

        if phones:
            parent, p_created = Parent.objects.get_or_create(
                phone_primary=phones[0],
                defaults={
                    "first_name": student.last_name or "Parent",
                    "last_name": "(Parent)",
                    "relationship": "guardian",
                },
            )
            if p_created:
                stats["parents_created"] += 1

            StudentParent.objects.get_or_create(
                student=student,
                parent=parent,
                defaults={"is_primary": True},
            )
