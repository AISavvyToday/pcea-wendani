from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from students.models import Student
from pathlib import Path
import pandas as pd


class Command(BaseCommand):
    help = "Import Term 3 2025 balances and set bal_bf_original or prepayment_original"

    def handle(self, *args, **options):
        BASE_DIR = Path(settings.BASE_DIR)

        excel_path = BASE_DIR / "TERM_3_2025_LIST_AND_BALANCES_NO GRADE_9.xlsx"

        if not excel_path.exists():
            self.stderr.write(self.style.ERROR(f"Excel file not found: {excel_path}"))
            return

        self.stdout.write(self.style.WARNING(f"Reading file: {excel_path}"))

        # Read Excel
        df = pd.read_excel(excel_path)

        # Normalize column names (strip spaces)
        df.columns = df.columns.str.strip()

        # -----------------------------
        # Detect ADMISSION NUMBER column
        # -----------------------------
        ADMISSION_COL_CANDIDATES = {
            "#",
            "ADM NO",
            "ADM",
            "ADMISSION NO",
            "ADMISSION NUMBER",
            "STUDENT NO",
            "STUDENT NUMBER",
        }

        admission_col = None
        for col in df.columns:
            if col.upper() in ADMISSION_COL_CANDIDATES:
                admission_col = col
                break

        if not admission_col:
            self.stderr.write(
                self.style.ERROR(
                    f"Could not detect admission number column. Found columns: {list(df.columns)}"
                )
            )
            return

        # -----------------------------
        # Detect TOTAL BALANCE column
        # -----------------------------
        TOTAL_BALANCE_CANDIDATES = {
            "TOTAL BALANCE",
            "BALANCE",
            "FINAL BALANCE",
            "TOTAL",
            "BALANCE TOTAL",
        }

        balance_col = None
        for col in df.columns:
            if str(col).strip().upper() in TOTAL_BALANCE_CANDIDATES:
                balance_col = col
                break

        if not balance_col:
            self.stderr.write(
                self.style.ERROR(
                    f"Could not detect Total Balance column. Found columns: {list(df.columns)}"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Using admission column '{admission_col}' and balance column '{balance_col}'"
            )
        )

        updated_bf = 0
        updated_prepayment = 0
        skipped = 0
        not_found = 0

        with transaction.atomic():
            for _, row in df.iterrows():
                admission_number = str(row[admission_col]).strip()

                # Skip empty admission numbers
                if not admission_number or admission_number.lower() == "nan":
                    skipped += 1
                    continue

                total_balance = row[balance_col]

                if pd.isna(total_balance) or total_balance == 0:
                    skipped += 1
                    continue

                try:
                    student = Student.objects.get(
                        admission_number__iexact=admission_number
                    )
                except Student.DoesNotExist:
                    not_found += 1
                    self.stderr.write(
                        self.style.WARNING(f"Student not found: {admission_number}")
                    )
                    continue

                # POSITIVE → Balance B/F
                if total_balance > 0:
                    student.bal_bf_original = total_balance
                    student.save(update_fields=["bal_bf_original"])
                    updated_bf += 1

                # NEGATIVE → Prepayment (store positive)
                elif total_balance < 0:
                    student.prepayment_original = abs(total_balance)
                    student.save(update_fields=["prepayment_original"])
                    updated_prepayment += 1

        self.stdout.write(self.style.SUCCESS("=== IMPORT SUMMARY ==="))
        self.stdout.write(self.style.SUCCESS(f"Balance BF updated: {updated_bf}"))
        self.stdout.write(self.style.SUCCESS(f"Prepayments updated: {updated_prepayment}"))
        self.stdout.write(self.style.WARNING(f"Skipped (0/empty): {skipped}"))
        self.stdout.write(self.style.WARNING(f"Students not found: {not_found}"))
