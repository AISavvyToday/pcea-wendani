# students/management/commands/import_students.py

import re
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import List, Optional, Tuple

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import FieldDoesNotExist

from academics.models import AcademicYear, Term, Class
from students.models import Student, Parent, StudentParent
from finance.models import Invoice, InvoiceItem
from payments.models import Payment
from payments.services.payment import PaymentService as PaymentsPaymentService
from core.models import TermChoices, FeeCategory, InvoiceStatus, PaymentMethod, PaymentStatus


STREAM_EAST = "East"  # change if your Class.stream choices require something else
OPENING_ITEM_DESC = "Imported opening balance (T3 2025)"


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


def pick_choice_value(choices: List[Tuple[str, str]], preferred: List[str]) -> str:
    values = [c[0] for c in choices]
    for p in preferred:
        if p in values:
            return p
    return values[0]


def get_default_fee_category() -> str:
    # Try common category names if your FeeCategory includes them; else fallback to first choice
    for attr in ("OTHER", "TUITION", "MISC"):
        v = getattr(FeeCategory, attr, None)
        if v and v in [c[0] for c in FeeCategory.choices]:
            return v
    return FeeCategory.choices[0][0]


def get_sent_status_value() -> str:
    # Prefer "sent" if it exists in InvoiceStatus choices; else draft.
    return pick_choice_value(InvoiceStatus.choices, preferred=["sent", "draft"])


def ensure_unallocated_amount_field():
    try:
        Payment._meta.get_field("unallocated_amount")
    except FieldDoesNotExist:
        raise RuntimeError(
            "Payment.unallocated_amount field is missing. "
            "You must add it to payments.models.Payment and run migrations "
            "before importing (your allocation service depends on it)."
        )


class Command(BaseCommand):
    help = "Import students + opening balances (arrears + credits) from Excel file"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to Excel file")
        parser.add_argument("--dry-run", action="store_true", help="Parse and validate but roll back DB changes")
        parser.add_argument("--limit", type=int, default=0, help="Only import first N rows (0 = all)")

    def handle(self, *args, **options):
        ensure_unallocated_amount_field()

        file_path = options["file_path"]
        dry_run = options["dry_run"]
        limit = options["limit"] or 0

        self.stdout.write(self.style.NOTICE(f"Reading {file_path}..."))

        # Read Excel: your sheet has a top line then header row (Year, #, Name...)
        df = pd.read_excel(file_path, skiprows=1)
        df.columns = [str(c).strip() for c in df.columns]

        # Rename columns safely based on actual header row
        df = df.rename(
            columns={
                "Year": "Year",
                "#": "Admission_No",
                "Name": "Name",
                "Class": "Class",
                "Class ": "Class",
                "Contacts": "Contacts",
                "Prepayment": "Prepayment",
                "Balance B/F": "Balance_BF",
                "Balance B/F ": "Balance_BF",
                "Current Balance": "Current_Balance",
                "Total Balance": "Total_Balance",
            }
        )

        required = [
            "Year",
            "Admission_No",
            "Name",
            "Class",
            "Contacts",
            "Prepayment",
            "Balance_BF",
            "Current_Balance",
            "Total_Balance",
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
            "invoices_created": 0,
            "payments_created": 0,
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
Invoices created: {stats['invoices_created']}
Payments created: {stats['payments_created']}
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

        # Student upsert
        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                "first_name": first_name.title(),
                "middle_name": middle_name.title(),
                "last_name": last_name.title(),
                "current_class": class_obj,
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

        # Sheet values
        prepayment = to_decimal(row["Prepayment"])
        balance_bf = to_decimal(row["Balance_BF"])
        current_balance = to_decimal(row["Current_Balance"])

        charges = balance_bf + current_balance
        if charges < 0:
            charges = Decimal("0.00")

        # Create/update opening invoice (do NOT store credit on invoice.prepayment)
        sent_status = get_sent_status_value()

        issue_date = getattr(term, "start_date", None) or date(2025, 9, 1)
        due_date = getattr(term, "fee_deadline", None) or date(2025, 9, 15)

        invoice, inv_created = Invoice.objects.update_or_create(
            student=student,
            term=term,
            defaults={
                "subtotal": charges,
                "discount_amount": Decimal("0.00"),
                "total_amount": charges,
                "balance_bf": balance_bf,
                "prepayment": Decimal("0.00"),
                "amount_paid": Decimal("0.00"),
                "status": sent_status,
                "issue_date": issue_date,
                "due_date": due_date,
                "notes": "Imported opening balance from legacy balances sheet (T3 2025).",
                "generated_by": None,
            },
        )
        if inv_created:
            stats["invoices_created"] += 1

        # Ensure at least 1 invoice item exists for allocation to attach to
        default_category = get_default_fee_category()

        opening_item = invoice.items.filter(description=OPENING_ITEM_DESC).first()
        if not opening_item:
            opening_item = InvoiceItem.objects.create(
                invoice=invoice,
                fee_item=None,  # allowed by your model
                description=OPENING_ITEM_DESC,
                category=default_category,
                amount=charges,
                discount_applied=Decimal("0.00"),
                net_amount=Decimal("0.00"),  # will be overwritten by save()
            )
        else:
            changed = False
            if opening_item.category != default_category:
                opening_item.category = default_category
                changed = True
            if opening_item.amount != charges:
                opening_item.amount = charges
                changed = True
            if opening_item.discount_applied != Decimal("0.00"):
                opening_item.discount_applied = Decimal("0.00")
                changed = True
            if changed:
                opening_item.save()

        # Create payment for prepayment as a COMPLETED Payment (idempotent)
        if prepayment > 0:
            tx_ref = f"IMPORT-T3-2025-{admission_no}"

            existing_payment = Payment.objects.filter(transaction_reference=tx_ref).first()
            if not existing_payment:
                pm_value = pick_choice_value(PaymentMethod.choices, preferred=["cash", "bank_transfer", "mpesa"])

                PaymentsPaymentService.create_manual_payment(
                    student=student,
                    amount=prepayment,
                    payment_method=pm_value,
                    received_by=None,
                    payment_date=timezone.now(),
                    payer_name="Imported",
                    payer_phone="",
                    notes="Imported prepayment/credit from opening balances sheet (T3 2025).",
                    transaction_reference=tx_ref,
                    invoice=invoice if charges > 0 else None,
                )
                stats["payments_created"] += 1

        # Ensure invoice status/balance consistent (will mark overdue if due_date passed)
        invoice.refresh_from_db()
        invoice.update_payment_status()

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