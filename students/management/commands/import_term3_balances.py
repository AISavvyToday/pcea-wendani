from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from students.models import Student
from pathlib import Path
import pandas as pd


class Command(BaseCommand):
    help = "Import Term 3 2025 balances and set balance BF or prepayment"

    BALANCE_BF_FIELD = "balance_bf_original"
    PREPAYMENT_FIELD = "prepayment_original"

    def handle(self, *args, **options):
        BASE_DIR = Path(settings.BASE_DIR)

        excel_path = BASE_DIR / "TERM_3_2025_LIST_AND_BALANCES_NO GRADE_9.xlsx"

        if not excel_path.exists():
            self.stderr.write(self.style.ERROR(f"Excel file not found: {excel_path}"))
            return

        self.stdout.write(self.style.WARNING(f"Reading file: {excel_path}"))

        # Excel has NO headers
        df = pd.read_excel(excel_path, header=None)

        updated_bf = 0
        updated_prepayment = 0
        skipped = 0
        not_found = 0

        with transaction.atomic():
            for _, row in df.iterrows():
                admission_number = str(row[1]).strip()   # Admission number
                total_balance = row.iloc[-1]             # Final balance

                if not admission_number or admission_number.lower() == "nan":
                    skipped += 1
                    continue

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
                    setattr(student, self.BALANCE_BF_FIELD, total_balance)
                    student.save(update_fields=[self.BALANCE_BF_FIELD])
                    updated_bf += 1

                # NEGATIVE → Prepayment (store positive)
                elif total_balance < 0:
                    setattr(student, self.PREPAYMENT_FIELD, abs(total_balance))
                    student.save(update_fields=[self.PREPAYMENT_FIELD])
                    updated_prepayment += 1

        self.stdout.write(self.style.SUCCESS("=== IMPORT SUMMARY ==="))
        self.stdout.write(self.style.SUCCESS(f"Balance BF updated: {updated_bf}"))
        self.stdout.write(self.style.SUCCESS(f"Prepayments updated: {updated_prepayment}"))
        self.stdout.write(self.style.WARNING(f"Skipped rows: {skipped}"))
        self.stdout.write(self.style.WARNING(f"Students not found: {not_found}"))
