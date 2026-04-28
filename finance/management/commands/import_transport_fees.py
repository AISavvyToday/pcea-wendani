import os
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from academics.models import AcademicYear, Term
from core.models import FeeCategory, InvoiceStatus, Organization, TermChoices
from finance.models import FeeItem, FeeStructure, Invoice, InvoiceItem
from students.models import Student
from transport.models import TransportRoute


class Command(BaseCommand):
    help = "Import transport fees from Excel into invoices for one organization and term."

    REQUIRED_COLUMNS = (
        'Admission #',
        'Route/Destination',
        'Transport Amount',
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='transport-report.xlsx',
            help='Path to transport report Excel file.',
        )
        parser.add_argument(
            '--organization-code',
            type=str,
            required=True,
            help='Organization code to scope the import to, for example WENDANI.',
        )
        parser.add_argument(
            '--academic-year',
            type=int,
            help='Academic year, for example 2026. Defaults to the current organization term year.',
        )
        parser.add_argument(
            '--term',
            type=str,
            choices=[choice[0] for choice in TermChoices.choices],
            help='Term code, for example term_2. Defaults to the current organization term.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes.',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        organization_code = (options['organization_code'] or '').strip()
        academic_year_value = options.get('academic_year')
        term_value = options.get('term')
        dry_run = options['dry_run']

        if not os.path.exists(file_path):
            raise CommandError(f"File not found: {file_path}")

        organization = self._resolve_organization(organization_code)
        term = self._resolve_term(
            organization=organization,
            academic_year_value=academic_year_value,
            term_value=term_value,
        )
        dataframe = self._load_dataframe(file_path)

        self.stdout.write(
            f"Using organization: {organization.name} ({organization.code})"
        )
        self.stdout.write(
            f"Using term: {term} [{term.start_date} to {term.end_date}]"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made."))

        summary = {
            'rows_seen': 0,
            'rows_with_amount': 0,
            'processed': 0,
            'added': 0,
            'skipped_zero_amount': 0,
            'skipped_blank_admission': 0,
            'skipped_existing_transport': 0,
            'skipped_inactive_student': 0,
            'missing_students': 0,
            'missing_invoices': 0,
            'missing_routes': 0,
            'matched_routes': 0,
            'errors': 0,
            'transport_total': Decimal('0.00'),
        }
        preview_lines = []

        for row_number, row in enumerate(dataframe.to_dict('records'), start=5):
            try:
                summary['rows_seen'] += 1
                raw_admission = row.get('Admission #')
                route_name = self._clean_text(row.get('Route/Destination'))
                transport_amount = self._to_decimal(row.get('Transport Amount'))
                admission_variations = self._admission_variations(raw_admission)

                if not admission_variations:
                    summary['skipped_blank_admission'] += 1
                    continue

                if transport_amount <= Decimal('0.00'):
                    summary['skipped_zero_amount'] += 1
                    continue

                summary['rows_with_amount'] += 1
                student, matched_admission = self._find_student(
                    admission_variations=admission_variations,
                    organization=organization,
                )
                if not student:
                    summary['missing_students'] += 1
                    preview_lines.append(
                        f"Row {row_number}: student not found for admission {raw_admission!r}"
                    )
                    continue

                if student.status != 'active':
                    summary['skipped_inactive_student'] += 1
                    preview_lines.append(
                        f"Row {row_number}: skipped {matched_admission} because student status is {student.status}"
                    )
                    continue

                invoice = self._find_invoice(student=student, term=term, organization=organization)
                if not invoice:
                    summary['missing_invoices'] += 1
                    preview_lines.append(
                        f"Row {row_number}: no invoice found for {matched_admission} in {term}"
                    )
                    continue

                existing_transport = invoice.items.filter(
                    is_active=True,
                    category=FeeCategory.TRANSPORT,
                )
                if existing_transport.exists():
                    summary['skipped_existing_transport'] += 1
                    preview_lines.append(
                        f"Row {row_number}: invoice {invoice.invoice_number} already has transport"
                    )
                    continue

                route = self._resolve_transport_route(organization=organization, route_name=route_name)
                if route:
                    summary['matched_routes'] += 1
                else:
                    summary['missing_routes'] += 1

                summary['processed'] += 1
                summary['transport_total'] += transport_amount
                old_total = invoice.total_amount or Decimal('0.00')
                new_total = old_total + transport_amount

                if len(preview_lines) < 20:
                    preview_lines.append(
                        f"Row {row_number}: {matched_admission} -> {invoice.invoice_number} "
                        f"transport {transport_amount} route={route_name or '-'} total {old_total} -> {new_total}"
                    )

                if dry_run:
                    continue

                self._apply_transport_to_invoice(
                    invoice=invoice,
                    student=student,
                    organization=organization,
                    term=term,
                    route=route,
                    route_name=route_name,
                    transport_amount=transport_amount,
                )
                summary['added'] += 1
            except Exception as exc:
                summary['errors'] += 1
                preview_lines.append(f"Row {row_number}: error {exc}")

        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write('TRANSPORT IMPORT SUMMARY')
        self.stdout.write(f"Organization: {organization.name} ({organization.code})")
        self.stdout.write(f"Term: {term}")
        self.stdout.write(f"Rows in workbook: {summary['rows_seen']}")
        self.stdout.write(f"Rows with transport amount: {summary['rows_with_amount']}")
        self.stdout.write(f"Rows ready to import: {summary['processed']}")
        self.stdout.write(f"Rows imported: {summary['added']}")
        self.stdout.write(f"Total transport to add: KES {summary['transport_total']:,.2f}")
        self.stdout.write(f"Matched transport routes: {summary['matched_routes']}")
        self.stdout.write(f"Unmatched route names: {summary['missing_routes']}")
        self.stdout.write(f"Skipped blank/totals rows: {summary['skipped_blank_admission']}")
        self.stdout.write(f"Skipped zero amount: {summary['skipped_zero_amount']}")
        self.stdout.write(f"Skipped existing transport: {summary['skipped_existing_transport']}")
        self.stdout.write(f"Skipped inactive students: {summary['skipped_inactive_student']}")
        self.stdout.write(f"Missing students: {summary['missing_students']}")
        self.stdout.write(f"Missing invoices: {summary['missing_invoices']}")
        self.stdout.write(f"Errors: {summary['errors']}")

        if preview_lines:
            self.stdout.write('')
            self.stdout.write('Preview:')
            for line in preview_lines:
                self.stdout.write(f"  - {line}")

        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Dry run complete. No invoice was changed.'))
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('Transport import complete.'))

    def _resolve_organization(self, organization_code):
        queryset = Organization.objects.filter(code__iexact=organization_code)
        organization = queryset.first()
        if organization:
            return organization
        raise CommandError(f"Organization not found for code: {organization_code}")

    def _resolve_term(self, *, organization, academic_year_value=None, term_value=None):
        queryset = Term.objects.select_related('academic_year').filter(
            Q(organization=organization) | Q(organization__isnull=True)
        )
        if academic_year_value is not None:
            queryset = queryset.filter(academic_year__year=academic_year_value)
        if term_value:
            queryset = queryset.filter(term=term_value)
        else:
            queryset = queryset.filter(is_current=True)

        queryset = queryset.order_by(
            '-organization_id',
            '-academic_year__year',
            '-start_date',
            'term',
        )
        term = queryset.first()
        if term:
            return term

        label = f"{academic_year_value or 'current'} {term_value or 'current term'}"
        raise CommandError(f"Term not found for organization {organization.code} and selection {label}.")

    def _load_dataframe(self, file_path):
        try:
            dataframe = pd.read_excel(file_path, header=3)
        except Exception as exc:
            raise CommandError(f"Error reading Excel file: {exc}") from exc

        dataframe.columns = [self._clean_text(column) for column in dataframe.columns]
        missing_columns = [column for column in self.REQUIRED_COLUMNS if column not in dataframe.columns]
        if missing_columns:
            raise CommandError(
                f"Workbook is missing required columns: {', '.join(missing_columns)}"
            )

        return dataframe.dropna(how='all')

    def _clean_text(self, value):
        if value is None:
            return ''
        if pd.isna(value):
            return ''
        text = str(value).strip()
        if text.endswith('.0') and text[:-2].isdigit():
            return text[:-2]
        return text

    def _to_decimal(self, value):
        if value is None or pd.isna(value):
            return Decimal('0.00')
        text = self._clean_text(value).replace(',', '')
        if not text:
            return Decimal('0.00')
        try:
            return Decimal(text)
        except (InvalidOperation, TypeError):
            return Decimal('0.00')

    def _admission_variations(self, raw_admission):
        cleaned = self._clean_text(raw_admission)
        if not cleaned:
            return []

        variations = [cleaned]
        if '/' in cleaned:
            compact = cleaned.replace('/', '')
            if compact not in variations:
                variations.append(compact)
        elif cleaned.startswith('PWA'):
            suffix = cleaned[3:]
            if suffix.isdigit():
                slash_variant = f'PWA/{suffix}/'
                if slash_variant not in variations:
                    variations.append(slash_variant)
        return variations

    def _find_student(self, *, admission_variations, organization):
        base_queryset = Student.objects.filter(organization=organization)
        if hasattr(Student, 'is_active'):
            base_queryset = base_queryset.filter(is_active=True)

        for admission in admission_variations:
            student = base_queryset.filter(admission_number=admission).first()
            if student:
                return student, admission

        return None, None

    def _find_invoice(self, *, student, term, organization):
        queryset = Invoice.objects.filter(
            student=student,
            term=term,
            is_active=True,
        ).exclude(status=InvoiceStatus.CANCELLED)
        queryset = queryset.filter(
            Q(organization=organization) |
            Q(organization__isnull=True, student__organization=organization)
        )
        return queryset.order_by('-created_at').first()

    def _resolve_transport_route(self, *, organization, route_name):
        if not route_name:
            return None
        queryset = TransportRoute.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            name__iexact=route_name,
            is_active=True,
        ).order_by('-organization_id', 'name')
        return queryset.first()

    def _get_transport_fee_item(self, *, organization, term, route_name, transport_amount):
        fee_structure, _ = FeeStructure.objects.get_or_create(
            organization=organization,
            name=f"Transport Import {term.academic_year.year} {term.get_term_display()}",
            academic_year=term.academic_year,
            term=term.term,
            defaults={
                'description': 'Transport items imported into already-generated invoices.',
                'grade_levels': [],
            },
        )
        description = f"Transport Fee - {route_name}" if route_name else 'Transport Fee'
        fee_item = FeeItem.objects.filter(
            fee_structure=fee_structure,
            category=FeeCategory.TRANSPORT,
            description=description,
            amount=transport_amount,
        ).first()
        if fee_item:
            return fee_item
        return FeeItem.objects.create(
            fee_structure=fee_structure,
            category=FeeCategory.TRANSPORT,
            description=description,
            amount=transport_amount,
            is_optional=True,
            applies_to_all=False,
        )

    def _apply_transport_to_invoice(
        self,
        *,
        invoice,
        student,
        organization,
        term,
        route,
        route_name,
        transport_amount,
    ):
        description = f"Transport Fee - {route_name}" if route_name else 'Transport Fee'
        fee_item = self._get_transport_fee_item(
            organization=organization,
            term=term,
            route_name=route_name,
            transport_amount=transport_amount,
        )

        with transaction.atomic():
            InvoiceItem.objects.create(
                invoice=invoice,
                fee_item=fee_item,
                description=description,
                category=FeeCategory.TRANSPORT,
                amount=transport_amount,
                discount_applied=Decimal('0.00'),
                net_amount=transport_amount,
                transport_route=route,
                transport_trip_type='full',
            )

            invoice.subtotal = (invoice.subtotal or Decimal('0.00')) + transport_amount
            invoice.total_amount = (invoice.total_amount or Decimal('0.00')) + transport_amount
            invoice.save(update_fields=['subtotal', 'total_amount', 'balance', 'status', 'updated_at'])

            student_updates = []
            if not student.uses_school_transport:
                student.uses_school_transport = True
                student_updates.append('uses_school_transport')
            if route and student.transport_route_id != route.id:
                student.transport_route = route
                student_updates.append('transport_route')
            if student_updates:
                student.save(update_fields=[*student_updates, 'updated_at'])
