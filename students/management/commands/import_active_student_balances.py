from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from students.models import Student
from pathlib import Path
import pandas as pd
from decimal import Decimal, InvalidOperation


class Command(BaseCommand):
    help = "Import balance_bf_original and prepayment_original for active students from Excel"

    BALANCE_BF_FIELD = "balance_bf_original"
    PREPAYMENT_FIELD = "prepayment_original"

    def normalize_admission_number(self, value):
        """
        Normalize admission numbers:
        - Convert to string
        - Strip whitespace
        - Remove trailing .0 from Excel
        """
        if pd.isna(value):
            return None
        value = str(value).strip()
        if value.endswith(".0"):
            value = value[:-2]
        return value

    def safe_decimal(self, value):
        """
        Convert Excel value to Decimal safely.
        Empty / NaN / invalid → Decimal(0)
        """
        try:
            if pd.isna(value) or value == "":
                return Decimal("0")
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return Decimal("0")

    def handle(self, *args, **options):
        BASE_DIR = Path(settings.BASE_DIR)
        excel_path = BASE_DIR / "active_students_balances.xlsx"

        if not excel_path.exists():
            self.stderr.write(
                self.style.ERROR(f"Excel file not found: {excel_path}")
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Reading Excel file: {excel_path}")
        )

        # Expecting 3 columns:
        # admission_number | balance_bf_original | prepayment_original
        df = pd.read_excel(excel_path, header=0)

        updated = 0
        skipped = 0
        not_found = 0
        inactive = 0

        with transaction.atomic():
            for _, row in df.iterrows():
                admission_number = self.normalize_admission_number(row.iloc[0])
                bf_value = self.safe_decimal(row.iloc[1])
                prepay_value = self.safe_decimal(row.iloc[2])

                if not admission_number:
                    skipped += 1
                    continue

                # Enforce business rules
                if bf_value < 0:
                    bf_value = Decimal("0")

                if prepay_value > 0:
                    prepay_value = Decimal("0")

                try:
                    student = Student.objects.get(
                        admission_number__iexact=admission_number
                    )
                except Student.DoesNotExist:
                    not_found += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"Student not found: {admission_number}"
                        )
                    )
                    continue

                if not student.is_active:
                    inactive += 1
                    continue

                student.balance_bf_original = bf_value
                student.prepayment_original = abs(prepay_value)

                student.save(update_fields=[
                    self.BALANCE_BF_FIELD,
                    self.PREPAYMENT_FIELD,
                ])

                updated += 1

        self.stdout.write(self.style.SUCCESS("=== IMPORT SUMMARY ==="))
        self.stdout.write(self.style.SUCCESS(f"Updated students: {updated}"))
        self.stdout.write(self.style.WARNING(f"Skipped rows: {skipped}"))
        self.stdout.write(self.style.WARNING(f"Inactive students ignored: {inactive}"))
        self.stdout.write(self.style.WARNING(f"Students not found: {not_found}"))
