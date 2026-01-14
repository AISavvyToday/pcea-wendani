from django.core.management.base import BaseCommand
from django.db import transaction
from students.models import Student
from pathlib import Path
import pandas as pd


class Command(BaseCommand):
    help = "Import Term 3 2025 balances and set bal_bf_original or prepayment_original"

    def handle(self, *args, **options):
        BASE_DIR = Path(__file__).resolve().parents[4]

        excel_path = BASE_DIR / "TERM 3 2025 LIST AND  BALANCES ....... (1) NO GRADE 9.xlsx"

        if not excel_path.exists():
            self.stderr.write(self.style.ERROR(f"Excel file not found: {excel_path}"))
            return

        self.stdout.write(self.style.WARNING(f"Reading file: {excel_path}"))

        # Read Excel
        df = pd.read_excel(excel_path)

        # Normalize column names
        df.columns = df.columns.str.strip()

        REQUIRED_COLUMNS = ["#", "Total Balance"]
        for col in REQUIRED_COLUMNS:
            if col not in df.columns:
                self.stderr.write(self.style.ERROR(f"Missing required column: {col}"))
                return

        updated_bf = 0
        updated_prepayment = 0
        skipped = 0
        not_found = 0

        with transaction.atomic():
            for _, row in df.iterrows():
                admission_number = str(row["#"]).strip()
                total_balance = row["Total Balance"]

                if pd.isna(total_balance) or total_balance == 0:
                    skipped += 1
                    continue

                try:
                    student = Student.objects.get(admission_number__iexact=admission_number)
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

                # NEGATIVE → Prepayment (stored positive)
                elif total_balance < 0:
                    student.prepayment_original = abs(total_balance)
                    student.save(update_fields=["prepayment_original"])
                    updated_prepayment += 1

        self.stdout.write(self.style.SUCCESS("=== IMPORT SUMMARY ==="))
        self.stdout.write(self.style.SUCCESS(f"Balance BF updated: {updated_bf}"))
        self.stdout.write(self.style.SUCCESS(f"Prepayments updated: {updated_prepayment}"))
        self.stdout.write(self.style.WARNING(f"Skipped (0/empty): {skipped}"))
        self.stdout.write(self.style.WARNING(f"Students not found: {not_found}"))
