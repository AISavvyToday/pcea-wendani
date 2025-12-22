# reports/views_exports.py
import io
from decimal import Decimal
from datetime import datetime
from decimal import Decimal
from django.db.models import ExpressionWrapper, DecimalField
from django.shortcuts import render
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseBadRequest
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.conf import settings
from django.db.models import Sum, Value, Q
from django.db.models.functions import Coalesce

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment

# WeasyPrint for PDF
from weasyprint import HTML

# Import models used by the reports
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from academics.models import TransportRoute, AcademicYear


# ---------- Helpers ----------
def xlsx_response(workbook_bytes, filename):
    response = HttpResponse(workbook_bytes,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def workbook_to_bytes(wb):
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.getvalue()


def format_money_cell(cell):
    cell.number_format = '#,##0.00'


def add_common_header(ws, title):
    # School name row
    ws.merge_cells('A1:G1')
    ws['A1'] = getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy')
    ws['A1'].font = Font(size=14, bold=True)
    ws['A1'].alignment = Alignment(horizontal='center')

    # Title row
    ws.merge_cells('A2:G2')
    ws['A2'] = title
    ws['A2'].font = Font(size=12, bold=True)
    ws['A2'].alignment = Alignment(horizontal='center')

    # small meta row
    ws.merge_cells('A3:G3')
    ws['A3'] = f'Generated on: {datetime.now().strftime("%d %b %Y %H:%M")}'
    ws['A3'].font = Font(size=9)
    ws['A3'].alignment = Alignment(horizontal='center')


# ---------- Invoice Report Exports ----------
class InvoiceReportExcelView(LoginRequiredMixin, View):
    """Exports invoice summary report to Excel."""

    def get(self, request):
        from .forms import InvoiceReportFilterForm
        form = InvoiceReportFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        academic_year = form.cleaned_data['academic_year']
        term = form.cleaned_data['term']
        show_zero = form.cleaned_data.get('show_zero_rows', False)

        # Select invoices for the academic year & term
        invoices = Invoice.objects.filter(term__academic_year=academic_year, term__term=term)

        # All invoice items for those invoices
        items_qs = InvoiceItem.objects.filter(invoice__in=invoices)

        # Sum billed per category
        billed_qs = items_qs.values('category').annotate(total_billed=Sum('net_amount'))
        billed_map = {row['category']: (row['total_billed'] or Decimal('0.00')) for row in billed_qs}

        # Collected per category
        collected_map = {}
        if PaymentAllocation is not None:
            alloc_qs = PaymentAllocation.objects.filter(invoice_item__invoice__in=invoices).values(
                'invoice_item__category').annotate(collected=Sum('amount'))
            collected_map = {row['invoice_item__category']: (row['collected'] or Decimal('0.00')) for row in alloc_qs}
        else:
            collected_map = {}
            for inv in invoices:
                inv_items = inv.items.all()
                inv_total = sum((i.net_amount or Decimal('0.00')) for i in inv_items)
                paid = inv.amount_paid or Decimal('0.00')
                if inv_total <= Decimal('0.00'):
                    continue
                for it in inv_items:
                    cat = it.category
                    share = ((it.net_amount or Decimal('0.00')) / inv_total) * paid
                    collected_map[cat] = collected_map.get(cat, Decimal('0.00')) + (share or Decimal('0.00'))

        # Build the set of categories present
        categories = set(billed_map.keys()) | set(collected_map.keys())
        preferred_order = ['tuition', 'meals', 'assessment', 'activity', 'transport']
        ordered = []
        for p in preferred_order:
            if p in categories:
                ordered.append(p)
        for c in sorted(categories):
            if c not in ordered:
                ordered.append(c)

        rows = []
        total_billed = Decimal('0.00')
        total_collected = Decimal('0.00')
        total_outstanding = Decimal('0.00')
        for cat in ordered:
            billed = billed_map.get(cat, Decimal('0.00'))
            collected = collected_map.get(cat, Decimal('0.00'))
            outstanding = billed - collected
            if not show_zero and billed == Decimal('0.00') and collected == Decimal('0.00') and outstanding == Decimal(
                    '0.00'):
                continue
            rows.append({
                'category': cat,
                'total_billed': billed,
                'collected': collected,
                'outstanding': outstanding
            })
            total_billed += billed
            total_collected += collected
            total_outstanding += outstanding

        # Build workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Invoice Summary"

        add_common_header(ws, f"Invoice Summary Report - {academic_year.year} Term {term}")

        headers = ['Category', 'Total Billed (KES)', 'Collected (KES)', 'Outstanding (KES)']
        for c, h in enumerate(headers, start=1):
            ws.cell(row=5, column=c, value=h).font = Font(bold=True)

        row_num = 6
        for r in rows:
            ws.cell(row=row_num, column=1, value=r['category'].title())
            ws.cell(row=row_num, column=2, value=float(r['total_billed']))
            format_money_cell(ws.cell(row=row_num, column=2))
            ws.cell(row=row_num, column=3, value=float(r['collected']))
            format_money_cell(ws.cell(row=row_num, column=3))
            ws.cell(row=row_num, column=4, value=float(r['outstanding']))
            format_money_cell(ws.cell(row=row_num, column=4))
            row_num += 1

        # Totals row
        ws.cell(row=row_num, column=1, value='TOTALS').font = Font(bold=True)
        ws.cell(row=row_num, column=2, value=float(total_billed))
        format_money_cell(ws.cell(row=row_num, column=2))
        ws.cell(row=row_num, column=3, value=float(total_collected))
        format_money_cell(ws.cell(row=row_num, column=3))
        ws.cell(row=row_num, column=4, value=float(total_outstanding))
        format_money_cell(ws.cell(row=row_num, column=4))

        # Auto width columns
        for col in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 20

        bytes_data = workbook_to_bytes(wb)
        filename = f"invoice-summary-{academic_year.year}-term{term}-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"
        return xlsx_response(bytes_data, filename)


class InvoiceReportPDFView(LoginRequiredMixin, View):
    """Generates PDF for invoice summary report."""

    def get(self, request):
        from .forms import InvoiceReportFilterForm
        form = InvoiceReportFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        academic_year = form.cleaned_data['academic_year']
        term = form.cleaned_data['term']
        show_zero = form.cleaned_data.get('show_zero_rows', False)

        # Reuse logic from InvoiceReportExcelView to get data
        invoices = Invoice.objects.filter(term__academic_year=academic_year, term__term=term)
        items_qs = InvoiceItem.objects.filter(invoice__in=invoices)

        billed_qs = items_qs.values('category').annotate(total_billed=Sum('net_amount'))
        billed_map = {row['category']: (row['total_billed'] or Decimal('0.00')) for row in billed_qs}

        collected_map = {}
        if PaymentAllocation is not None:
            alloc_qs = PaymentAllocation.objects.filter(invoice_item__invoice__in=invoices).values(
                'invoice_item__category').annotate(collected=Sum('amount'))
            collected_map = {row['invoice_item__category']: (row['collected'] or Decimal('0.00')) for row in alloc_qs}
        else:
            collected_map = {}
            for inv in invoices:
                inv_items = inv.items.all()
                inv_total = sum((i.net_amount or Decimal('0.00')) for i in inv_items)
                paid = inv.amount_paid or Decimal('0.00')
                if inv_total <= Decimal('0.00'):
                    continue
                for it in inv_items:
                    cat = it.category
                    share = ((it.net_amount or Decimal('0.00')) / inv_total) * paid
                    collected_map[cat] = collected_map.get(cat, Decimal('0.00')) + (share or Decimal('0.00'))

        categories = set(billed_map.keys()) | set(collected_map.keys())
        preferred_order = ['tuition', 'meals', 'assessment', 'activity', 'transport']
        ordered = []
        for p in preferred_order:
            if p in categories:
                ordered.append(p)
        for c in sorted(categories):
            if c not in ordered:
                ordered.append(c)

        rows = []
        total_billed = Decimal('0.00')
        total_collected = Decimal('0.00')
        total_outstanding = Decimal('0.00')
        for cat in ordered:
            billed = billed_map.get(cat, Decimal('0.00'))
            collected = collected_map.get(cat, Decimal('0.00'))
            outstanding = billed - collected
            if not show_zero and billed == Decimal('0.00') and collected == Decimal('0.00') and outstanding == Decimal(
                    '0.00'):
                continue
            rows.append({
                'category': cat,
                'total_billed': billed,
                'collected': collected,
                'outstanding': outstanding
            })
            total_billed += billed
            total_collected += collected
            total_outstanding += outstanding

        context = {
            'report_rows': rows,
            'totals': {
                'billed': total_billed,
                'collected': total_collected,
                'outstanding': total_outstanding
            },
            'academic_year': academic_year,
            'term': term,
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'SCHOOL_CONTACT': getattr(settings, 'SCHOOL_CONTACT', ''),
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy',
                           'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy',
                         'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'generated_by': request.user.get_full_name(),
            'generated_on': datetime.now(),
        }

        html_string = render_to_string('reports/pdf/invoice_report_pdf.html', context)
        html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
        pdf_bytes = html.write_pdf()
        filename = f"invoice-summary-{academic_year.year}-term{term}-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# ---------- Fees Collection Exports ----------
class FeesCollectionExcelView(LoginRequiredMixin, View):
    """Exports fees collection report to Excel."""

    def get(self, request):
        from .forms import FeesCollectionFilterForm
        from datetime import datetime as dt
        from django.utils import timezone

        # Initialize form
        form = FeesCollectionFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        # Extract filters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        selected_class = form.cleaned_data.get('student_class') or ''
        selected_bank = form.cleaned_data.get('bank') or ''
        group_by = form.cleaned_data.get('group_by') or 'none'

        # Base queryset
        payments_qs = Payment.objects.all()

        # Fix datetime warnings - convert dates to timezone-aware datetimes
        if start_date:
            start_datetime = timezone.make_aware(dt.combine(start_date, dt.min.time()))
            payments_qs = payments_qs.filter(payment_date__gte=start_datetime)
        if end_date:
            end_datetime = timezone.make_aware(dt.combine(end_date, dt.max.time()))
            payments_qs = payments_qs.filter(payment_date__lte=end_datetime)

        if selected_class:
            payments_qs = payments_qs.filter(
                Q(student__current_class=selected_class) |
                Q(invoice__student__current_class=selected_class)
            )

        if selected_bank:
            bank_filters = Q()
            if hasattr(Payment, 'bank'):
                bank_filters |= Q(bank=selected_bank)
            if hasattr(Payment, 'payment_source'):
                bank_filters |= Q(payment_source=selected_bank)
            if hasattr(Payment, 'payment_method'):
                bank_filters |= Q(payment_method__icontains=selected_bank)
            payments_qs = payments_qs.filter(bank_filters)

        # Build workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Collections"

        title = "Fees Collection Report"
        if start_date and end_date:
            title += f" ({start_date} to {end_date})"
        add_common_header(ws, title)

        headers = ['Payment Date', 'Receipt/Ref', 'Student', 'Admission #', 'Class', 'Amount (KES)', 'Method',
                   'Bank/Source']
        for c, h in enumerate(headers, start=1):
            ws.cell(row=5, column=c, value=h).font = Font(bold=True)

        row_num = 6
        total_amount = Decimal('0.00')

        payments_list = payments_qs.select_related('student', 'invoice').order_by('payment_date')
        for p in payments_list:
            # Get student details
            student_name = None
            student_class_obj = None  # Keep as object first
            admission = None

            if hasattr(p, 'student') and p.student:
                student_name = getattr(p.student, 'full_name', '')
                student_class_obj = getattr(p.student, 'current_class', '')
                admission = getattr(p.student, 'admission_number', '')
            elif hasattr(p, 'invoice') and getattr(p, 'invoice', None) and getattr(p.invoice, 'student', None):
                st = p.invoice.student
                student_name = getattr(st, 'full_name', '')
                student_class_obj = getattr(st, 'current_class', '')
                admission = getattr(st, 'admission_number', '')
            else:
                student_name = getattr(p, 'payer_name', '') or getattr(p, 'payment_source', '') or '—'

            # Convert Class object to string
            student_class = str(student_class_obj) if student_class_obj else ''

            bank_display = getattr(p, 'bank', '') or getattr(p, 'payment_source', '') or getattr(p, 'payment_method', '')

            ws.cell(row=row_num, column=1, value=p.payment_date.strftime('%Y-%m-%d %H:%M') if p.payment_date else '')
            ws.cell(row=row_num, column=2, value=getattr(p, 'receipt_number', getattr(p, 'payment_reference', '')))
            ws.cell(row=row_num, column=3, value=student_name)
            ws.cell(row=row_num, column=4, value=admission or '')
            ws.cell(row=row_num, column=5, value=student_class or '')  # Now a string
            amount_cell = ws.cell(row=row_num, column=6, value=float(p.amount or 0))
            format_money_cell(amount_cell)
            ws.cell(row=row_num, column=7, value=getattr(p, 'payment_method', ''))
            ws.cell(row=row_num, column=8, value=bank_display)

            total_amount += Decimal(p.amount or 0)
            row_num += 1

        # Totals row
        ws.cell(row=row_num, column=5, value='TOTAL').font = Font(bold=True)
        total_cell = ws.cell(row=row_num, column=6, value=float(total_amount))
        format_money_cell(total_cell)

        # Auto width columns
        for col in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 18

        bytes_data = workbook_to_bytes(wb)
        filename = f"fees-collections-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"
        return xlsx_response(bytes_data, filename)

class FeesCollectionPDFView(LoginRequiredMixin, View):
    """Generates PDF for fees collection report."""

    def get(self, request):
        from .forms import FeesCollectionFilterForm

        form = FeesCollectionFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        # Extract filters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        selected_class = form.cleaned_data.get('student_class') or ''
        selected_bank = form.cleaned_data.get('bank') or ''
        group_by = form.cleaned_data.get('group_by') or 'none'

        # Base queryset
        payments_qs = Payment.objects.all()

        if start_date:
            payments_qs = payments_qs.filter(payment_date__gte=start_date)
        if end_date:
            payments_qs = payments_qs.filter(payment_date__lte=end_date)

        if selected_class:
            payments_qs = payments_qs.filter(
                Q(student__current_class=selected_class) |
                Q(invoice__student__current_class=selected_class)
            )

        if selected_bank:
            bank_filters = Q()
            if hasattr(Payment, 'bank'):
                bank_filters |= Q(bank=selected_bank)
            if hasattr(Payment, 'payment_source'):
                bank_filters |= Q(payment_source=selected_bank)
            if hasattr(Payment, 'payment_method'):
                bank_filters |= Q(payment_method__icontains=selected_bank)
            payments_qs = payments_qs.filter(bank_filters)

        # Build rows for template
        rows = []
        total_amount = Decimal('0.00')

        payments_list = payments_qs.select_related('student', 'invoice').order_by('payment_date')
        for p in payments_list:
            # Get student details
            student_name = None
            student_class = None
            admission = None

            if hasattr(p, 'student') and p.student:
                student_name = getattr(p.student, 'full_name', '')
                student_class = getattr(p.student, 'current_class', '')
                admission = getattr(p.student, 'admission_number', '')
            elif hasattr(p, 'invoice') and getattr(p, 'invoice', None) and getattr(p.invoice, 'student', None):
                st = p.invoice.student
                student_name = getattr(st, 'full_name', '')
                student_class = getattr(st, 'current_class', '')
                admission = getattr(st, 'admission_number', '')
            else:
                student_name = getattr(p, 'payer_name', '') or getattr(p, 'payment_source', '') or '—'

            bank_display = getattr(p, 'bank', '') or getattr(p, 'payment_source', '') or getattr(p, 'payment_method',
                                                                                                 '')

            rows.append({
                'date': p.payment_date,
                'reference': getattr(p, 'receipt_number', getattr(p, 'payment_reference', '')),
                'student': student_name,
                'class': student_class or '',
                'admission': admission or '',
                'amount': p.amount or Decimal('0.00'),
                'method': getattr(p, 'payment_method', ''),
                'bank': bank_display,
            })
            total_amount += Decimal(p.amount or 0)

        context = {
            'rows': rows,
            'summary': {
                'total_collected': total_amount,
                'count': len(rows)
            },
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'student_class': selected_class,
                'bank': selected_bank,
                'group_by': group_by,
            },
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'SCHOOL_CONTACT': getattr(settings, 'SCHOOL_CONTACT', ''),
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy',
                           'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy',
                         'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'generated_by': request.user.get_full_name(),
            'generated_on': datetime.now(),
        }

        html_string = render_to_string('reports/pdf/fees_collection_report_pdf.html', context)
        html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
        pdf_bytes = html.write_pdf()
        filename = f"fees-collections-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
class FeesCollectionPDFView(LoginRequiredMixin, View):
    """Generates PDF for fees collection report."""

    def get(self, request):
        from .forms import FeesCollectionFilterForm
        from datetime import datetime as dt
        from django.utils import timezone

        form = FeesCollectionFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        # Extract filters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        selected_class = form.cleaned_data.get('student_class') or ''
        selected_bank = form.cleaned_data.get('bank') or ''
        group_by = form.cleaned_data.get('group_by') or 'none'

        # Base queryset
        payments_qs = Payment.objects.all()

        # Fix datetime warnings
        if start_date:
            start_datetime = timezone.make_aware(dt.combine(start_date, dt.min.time()))
            payments_qs = payments_qs.filter(payment_date__gte=start_datetime)
        if end_date:
            end_datetime = timezone.make_aware(dt.combine(end_date, dt.max.time()))
            payments_qs = payments_qs.filter(payment_date__lte=end_datetime)

        if selected_class:
            payments_qs = payments_qs.filter(
                Q(student__current_class=selected_class) |
                Q(invoice__student__current_class=selected_class)
            )

        if selected_bank:
            bank_filters = Q()
            if hasattr(Payment, 'bank'):
                bank_filters |= Q(bank=selected_bank)
            if hasattr(Payment, 'payment_source'):
                bank_filters |= Q(payment_source=selected_bank)
            if hasattr(Payment, 'payment_method'):
                bank_filters |= Q(payment_method__icontains=selected_bank)
            payments_qs = payments_qs.filter(bank_filters)

        # Build rows for template
        rows = []
        total_amount = Decimal('0.00')

        payments_list = payments_qs.select_related('student', 'invoice').order_by('payment_date')
        for p in payments_list:
            # Get student details
            student_name = None
            student_class_obj = None  # Keep as object first
            admission = None

            if hasattr(p, 'student') and p.student:
                student_name = getattr(p.student, 'full_name', '')
                student_class_obj = getattr(p.student, 'current_class', '')
                admission = getattr(p.student, 'admission_number', '')
            elif hasattr(p, 'invoice') and getattr(p, 'invoice', None) and getattr(p.invoice, 'student', None):
                st = p.invoice.student
                student_name = getattr(st, 'full_name', '')
                student_class_obj = getattr(st, 'current_class', '')
                admission = getattr(st, 'admission_number', '')
            else:
                student_name = getattr(p, 'payer_name', '') or getattr(p, 'payment_source', '') or '—'

            # Convert Class object to string
            student_class = str(student_class_obj) if student_class_obj else ''

            bank_display = getattr(p, 'bank', '') or getattr(p, 'payment_source', '') or getattr(p, 'payment_method',
                                                                                                 '')

            rows.append({
                'date': p.payment_date,
                'reference': getattr(p, 'receipt_number', getattr(p, 'payment_reference', '')),
                'student': student_name,
                'class': student_class or '',  # Now a string
                'admission': admission or '',
                'amount': p.amount or Decimal('0.00'),
                'method': getattr(p, 'payment_method', ''),
                'bank': bank_display,
            })
            total_amount += Decimal(p.amount or 0)

        context = {
            'rows': rows,
            'summary': {
                'total_collected': total_amount,
                'count': len(rows)
            },
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'student_class': selected_class,
                'bank': selected_bank,
                'group_by': group_by,
            },
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'SCHOOL_CONTACT': getattr(settings, 'SCHOOL_CONTACT', ''),
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy',
                           'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy',
                         'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'generated_by': request.user.get_full_name(),
            'generated_on': datetime.now(),
        }

        html_string = render_to_string('reports/pdf/fees_collection_report_pdf.html', context)
        html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
        pdf_bytes = html.write_pdf()
        filename = f"fees-collections-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# ---------- Outstanding Balances Exports ----------
class OutstandingBalancesExcelView(LoginRequiredMixin, View):
    """Exports outstanding balances report to Excel."""

    def get(self, request):
        from .forms import OutstandingBalancesFilterForm
        form = OutstandingBalancesFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        # extract filters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        academic_year = form.cleaned_data.get('academic_year')
        term = form.cleaned_data.get('term')
        student_class = form.cleaned_data.get('student_class')
        balance_op = form.cleaned_data.get('balance_operator') or 'any'
        balance_amt = form.cleaned_data.get('balance_amount') or Decimal('0.00')
        include_zero = form.cleaned_data.get('show_zero_balances')

        invoices = Invoice.objects.select_related('student', 'term__academic_year')

        if academic_year:
            invoices = invoices.filter(term__academic_year=academic_year)
            if term:
                invoices = invoices.filter(term__term=term)
        if start_date:
            invoices = invoices.filter(issue_date__gte=start_date)
        if end_date:
            invoices = invoices.filter(issue_date__lte=end_date)
        if student_class:
            invoices = invoices.filter(student__current_class=student_class)

        annotations = {
            'total_billed': ExpressionWrapper(
                Coalesce(Sum('total_amount'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
            'total_paid': ExpressionWrapper(
                Coalesce(Sum('amount_paid'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
            'total_balance': ExpressionWrapper(
                Coalesce(Sum('balance'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
            'total_balance_bf': ExpressionWrapper(
                Coalesce(Sum('balance_bf'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
            'total_prepayment': ExpressionWrapper(
                Coalesce(Sum('prepayment'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
        }

        grouped_qs = invoices.values(
            'student__pk',
            'student__admission_number',
            'student__first_name',
            'student__middle_name',
            'student__last_name',
            'student__current_class',
            'term__academic_year__year',
        ).annotate(**annotations).order_by('-total_balance', 'student__first_name', 'student__last_name')

        # balance filter
        if balance_op != 'any' and balance_amt is not None:
            lookup = {
                '=': 'total_balance',
                '>': 'total_balance__gt',
                '<': 'total_balance__lt',
                '>=': 'total_balance__gte',
                '<=': 'total_balance__lte',
            }.get(balance_op, None)
            if lookup:
                grouped_qs = grouped_qs.filter(**{lookup: balance_amt})

        if not include_zero:
            grouped_qs = grouped_qs.exclude(total_balance=Decimal('0.00'))

        rows = list(grouped_qs)

        # Build Excel
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Outstanding Balances"

        title = "Outstanding Balances Report"
        if academic_year:
            title += f" - {academic_year.year}"
            if term:
                title += f" Term {term}"
        add_common_header(ws, title)

        headers = ['Year', 'Admission No', 'Name', 'Class', 'Emergency Contact', 'Balance B/F', 'Prepayment',
                   'Total Billed',
                   'Paid', 'Balance']
        for c, h in enumerate(headers, start=1):
            ws.cell(row=5, column=c, value=h).font = Font(bold=True)

        row_num = 6
        for r in rows:
            ws.cell(row=row_num, column=1, value=r.get('term__academic_year__year'))
            ws.cell(row=row_num, column=2, value=r.get('student__admission_number'))

            # Build full name from first, middle, last
            first = r.get('student__first_name', '')
            middle = r.get('student__middle_name', '')
            last = r.get('student__last_name', '')
            full_name = f"{first} {middle} {last}".strip()
            full_name = ' '.join(full_name.split())
            ws.cell(row=row_num, column=3, value=full_name)



            # Money columns
            money_columns = [6, 7, 8, 9, 10]
            values = [
                float(r.get('total_balance_bf') or 0),
                float(r.get('total_prepayment') or 0),
                float(r.get('total_billed') or 0),
                float(r.get('total_paid') or 0),
                float(r.get('total_balance') or 0)
            ]

            for col_idx, value in zip(money_columns, values):
                cell = ws.cell(row=row_num, column=col_idx, value=value)
                format_money_cell(cell)

            row_num += 1

        # Totals row
        totals = {
            'total_balance_bf': sum((r['total_balance_bf'] or Decimal('0.00')) for r in rows),
            'total_prepayment': sum((r['total_prepayment'] or Decimal('0.00')) for r in rows),
            'total_billed': sum((r['total_billed'] or Decimal('0.00')) for r in rows),
            'total_paid': sum((r['total_paid'] or Decimal('0.00')) for r in rows),
            'total_balance': sum((r['total_balance'] or Decimal('0.00')) for r in rows),
        }

        ws.cell(row=row_num, column=1, value='TOTALS').font = Font(bold=True)
        for col_idx, value in zip(money_columns, [
            float(totals['total_balance_bf']),
            float(totals['total_prepayment']),
            float(totals['total_billed']),
            float(totals['total_paid']),
            float(totals['total_balance'])
        ]):
            cell = ws.cell(row=row_num, column=col_idx, value=value)
            format_money_cell(cell)

        # Auto width columns
        for col in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 18

        bytes_data = workbook_to_bytes(wb)
        filename = f"outstanding-balances-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"
        return xlsx_response(bytes_data, filename)


class OutstandingBalancesPDFView(LoginRequiredMixin, View):
    """Generates PDF for outstanding balances report."""

    def get(self, request):
        from .forms import OutstandingBalancesFilterForm
        form = OutstandingBalancesFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        # Use the same queryset logic as Excel view
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        academic_year = form.cleaned_data.get('academic_year')
        term = form.cleaned_data.get('term')
        student_class = form.cleaned_data.get('student_class')
        balance_op = form.cleaned_data.get('balance_operator') or 'any'
        balance_amt = form.cleaned_data.get('balance_amount') or Decimal('0.00')
        include_zero = form.cleaned_data.get('show_zero_balances')

        invoices = Invoice.objects.select_related('student', 'term__academic_year')
        if academic_year:
            invoices = invoices.filter(term__academic_year=academic_year)
            if term:
                invoices = invoices.filter(term__term=term)
        if start_date:
            invoices = invoices.filter(issue_date__gte=start_date)
        if end_date:
            invoices = invoices.filter(issue_date__lte=end_date)


        annotations = {
            'total_billed': ExpressionWrapper(
                Coalesce(Sum('total_amount'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
            'total_paid': ExpressionWrapper(
                Coalesce(Sum('amount_paid'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
            'total_balance': ExpressionWrapper(
                Coalesce(Sum('balance'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
            'total_balance_bf': ExpressionWrapper(
                Coalesce(Sum('balance_bf'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
            'total_prepayment': ExpressionWrapper(
                Coalesce(Sum('prepayment'), Value(Decimal('0.00'))),
                output_field=DecimalField()
            ),
        }

        grouped_qs = invoices.values(
            'student__pk',
            'student__admission_number',
            'student__first_name',
            'student__middle_name',
            'student__last_name',
            'term__academic_year__year',
        ).annotate(**annotations).order_by('-total_balance', 'student__first_name', 'student__last_name')

        if balance_op != 'any' and balance_amt is not None:
            lookup = {
                '=': 'total_balance',
                '>': 'total_balance__gt',
                '<': 'total_balance__lt',
                '>=': 'total_balance__gte',
                '<=': 'total_balance__lte',
            }.get(balance_op, None)
            if lookup:
                grouped_qs = grouped_qs.filter(**{lookup: balance_amt})

        if not include_zero:
            grouped_qs = grouped_qs.exclude(total_balance=Decimal('0.00'))

        rows = list(grouped_qs)
        totals = {
            'total_balance_bf': sum((r['total_balance_bf'] or Decimal('0.00')) for r in rows),
            'total_prepayment': sum((r['total_prepayment'] or Decimal('0.00')) for r in rows),
            'total_billed': sum((r['total_billed'] or Decimal('0.00')) for r in rows),
            'total_paid': sum((r['total_paid'] or Decimal('0.00')) for r in rows),
            'total_balance': sum((r['total_balance'] or Decimal('0.00')) for r in rows),
        }

        # Process rows to include full_name and contact_info
        processed_rows = []
        for r in rows:
            # Build full name
            first = r.get('student__first_name', '')
            middle = r.get('student__middle_name', '')
            last = r.get('student__last_name', '')
            full_name = f"{first} {middle} {last}".strip()
            full_name = ' '.join(full_name.split())



            processed_rows.append({
                'term__academic_year__year': r.get('term__academic_year__year'),
                'student__admission_number': r.get('student__admission_number'),
                'student__first_name': first,
                'student__middle_name': middle,
                'student__last_name': last,
                'total_balance_bf': r.get('total_balance_bf'),
                'total_prepayment': r.get('total_prepayment'),
                'total_billed': r.get('total_billed'),
                'total_paid': r.get('total_paid'),
                'total_balance': r.get('total_balance'),
            })

        context = {
            'rows': processed_rows,
            'totals': totals,
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'academic_year': academic_year,
                'term': term,
                'student_class': student_class,
                'balance_op': balance_op,
                'balance_amt': balance_amt,
            },
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'SCHOOL_CONTACT': getattr(settings, 'SCHOOL_CONTACT', ''),
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy',
                           'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy',
                         'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'generated_by': request.user.get_full_name(),
            'generated_on': datetime.now(),
        }

        html_string = render_to_string('reports/pdf/outstanding_report_pdf.html', context)
        html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
        pdf_bytes = html.write_pdf()
        filename = f"outstanding-balances-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
# ---------- Transport Report Exports ----------
class TransportReportExcelView(LoginRequiredMixin, View):
    """Exports transport report to Excel."""

    def get(self, request):
        from .forms import TransportReportFilterForm
        form = TransportReportFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        academic_year = form.cleaned_data['academic_year']
        term = form.cleaned_data['term']
        route = form.cleaned_data.get('route')
        student_class = form.cleaned_data.get('student_class') or ''
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        show_zero = form.cleaned_data.get('show_zero_rows', False)

        items_qs = InvoiceItem.objects.filter(
            invoice__term__academic_year=academic_year,
            invoice__term__term=term,
            category='transport'
        ).select_related('invoice__student', 'transport_route')

        if route:
            items_qs = items_qs.filter(transport_route=route)

        if start_date:
            items_qs = items_qs.filter(invoice__issue_date__gte=start_date)
        if end_date:
            items_qs = items_qs.filter(invoice__issue_date__lte=end_date)

        grouped = items_qs.values(
            'invoice__student__pk',
            'invoice__student__full_name',
            'invoice__student__admission_number',
            'transport_route__pk',
            'transport_route__name'
        ).annotate(total_billed=Coalesce(Sum('net_amount'), Value(0))).order_by('invoice__student__full_name')

        # Build collected_map
        collected_map = {}
        try:
            alloc_qs = PaymentAllocation.objects.filter(invoice_item__in=items_qs).values(
                'invoice_item__invoice__student__pk',
                'invoice_item__transport_route__pk'
            ).annotate(collected=Coalesce(Sum('amount'), Value(0)))
            for row in alloc_qs:
                key = (row.get('invoice_item__invoice__student__pk'), row.get('invoice_item__transport_route__pk'))
                collected_map[key] = Decimal(row.get('collected') or 0)
        except Exception:
            collected_map = {}
            invoice_ids = items_qs.values_list('invoice_id', flat=True).distinct()
            invoices = Invoice.objects.filter(id__in=invoice_ids)
            for inv in invoices:
                inv_items = items_qs.filter(invoice=inv)
                inv_total_transport = sum((i.net_amount or Decimal('0.00')) for i in inv_items)
                paid = inv.amount_paid or Decimal('0.00')
                if inv_total_transport <= Decimal('0.00'):
                    for it in inv_items:
                        key = (inv.student.pk, it.transport_route.pk if it.transport_route else None)
                        collected_map[key] = collected_map.get(key, Decimal('0.00'))
                    continue
                for it in inv_items:
                    proportion = (it.net_amount or Decimal('0.00')) / inv_total_transport
                    alloc_amount = (paid * proportion).quantize(Decimal('0.01'))
                    key = (inv.student.pk, it.transport_route.pk if it.transport_route else None)
                    collected_map[key] = collected_map.get(key, Decimal('0.00')) + alloc_amount

        # Build rows
        rows = []
        total_billed = Decimal('0.00')
        total_collected = Decimal('0.00')
        total_balance = Decimal('0.00')

        for g in grouped:
            student_pk = g.get('invoice__student__pk')
            billed = Decimal(g.get('total_billed') or 0)
            route_pk = g.get('transport_route__pk')
            collected = collected_map.get((student_pk, route_pk), Decimal('0.00'))
            balance = billed - collected
            if (not show_zero) and billed == Decimal('0.00') and collected == Decimal('0.00'):
                continue
            rows.append({
                'student_name': g.get('invoice__student__full_name') or '',
                'admission': g.get('invoice__student__admission_number') or '',
                'route_name': g.get('transport_route__name') or '',
                'billed': billed,
                'collected': collected,
                'balance': balance,
            })
            total_billed += billed
            total_collected += collected
            total_balance += balance

        # Build workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Transport Report"

        title = f"Transport Report - {academic_year.year} Term {term}"
        if route:
            title += f" - {route.name}"
        add_common_header(ws, title)

        headers = ['Student Name', 'Admission #', 'Class/Grade', 'Route/Destination', 'Transport Amount', 'Paid',
                   'Balance']
        for c, h in enumerate(headers, start=1):
            ws.cell(row=5, column=c, value=h).font = Font(bold=True)

        row_num = 6
        for r in rows:
            ws.cell(row=row_num, column=1, value=r['student_name'])
            ws.cell(row=row_num, column=2, value=r['admission'])
            ws.cell(row=row_num, column=3, value=r['student_class'])
            ws.cell(row=row_num, column=4, value=r['route_name'])

            # Money columns
            c5 = ws.cell(row=row_num, column=5, value=float(r['billed']))
            format_money_cell(c5)
            c6 = ws.cell(row=row_num, column=6, value=float(r['collected']))
            format_money_cell(c6)
            c7 = ws.cell(row=row_num, column=7, value=float(r['balance']))
            format_money_cell(c7)

            row_num += 1

        # Totals
        ws.cell(row=row_num, column=1, value='TOTALS').font = Font(bold=True)
        c5 = ws.cell(row=row_num, column=5, value=float(total_billed))
        format_money_cell(c5)
        c6 = ws.cell(row=row_num, column=6, value=float(total_collected))
        format_money_cell(c6)
        c7 = ws.cell(row=row_num, column=7, value=float(total_balance))
        format_money_cell(c7)

        for col in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 18

        bytes_data = workbook_to_bytes(wb)
        filename = f"transport-report-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"
        return xlsx_response(bytes_data, filename)


class TransportReportPDFView(LoginRequiredMixin, View):
    """Generates PDF for transport report."""

    def get(self, request):
        from .forms import TransportReportFilterForm
        form = TransportReportFilterForm(request.GET or None)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid filters")

        academic_year = form.cleaned_data['academic_year']
        term = form.cleaned_data['term']
        route = form.cleaned_data.get('route')
        student_class = form.cleaned_data.get('student_class') or ''
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        show_zero = form.cleaned_data.get('show_zero_rows', False)

        items_qs = InvoiceItem.objects.filter(
            invoice__term__academic_year=academic_year,
            invoice__term__term=term,
            category='transport'
        ).select_related('invoice__student', 'transport_route')

        if route:
            items_qs = items_qs.filter(transport_route=route)

        if start_date:
            items_qs = items_qs.filter(invoice__issue_date__gte=start_date)
        if end_date:
            items_qs = items_qs.filter(invoice__issue_date__lte=end_date)

        grouped = items_qs.values(
            'invoice__student__pk',
            'invoice__student__full_name',
            'invoice__student__admission_number',
            'transport_route__pk',
            'transport_route__name'
        ).annotate(total_billed=Coalesce(Sum('net_amount'), Value(0))).order_by('invoice__student__full_name')

        # Build collected_map
        collected_map = {}
        try:
            alloc_qs = PaymentAllocation.objects.filter(invoice_item__in=items_qs).values(
                'invoice_item__invoice__student__pk',
                'invoice_item__transport_route__pk'
            ).annotate(collected=Coalesce(Sum('amount'), Value(0)))
            for row in alloc_qs:
                key = (row.get('invoice_item__invoice__student__pk'), row.get('invoice_item__transport_route__pk'))
                collected_map[key] = Decimal(row.get('collected') or 0)
        except Exception:
            collected_map = {}
            invoice_ids = items_qs.values_list('invoice_id', flat=True).distinct()
            invoices = Invoice.objects.filter(id__in=invoice_ids)
            for inv in invoices:
                inv_items = items_qs.filter(invoice=inv)
                inv_total_transport = sum((i.net_amount or Decimal('0.00')) for i in inv_items)
                paid = inv.amount_paid or Decimal('0.00')
                if inv_total_transport <= Decimal('0.00'):
                    for it in inv_items:
                        key = (inv.student.pk, it.transport_route.pk if it.transport_route else None)
                        collected_map[key] = collected_map.get(key, Decimal('0.00'))
                    continue
                for it in inv_items:
                    proportion = (it.net_amount or Decimal('0.00')) / inv_total_transport
                    alloc_amount = (paid * proportion).quantize(Decimal('0.01'))
                    key = (inv.student.pk, it.transport_route.pk if it.transport_route else None)
                    collected_map[key] = collected_map.get(key, Decimal('0.00')) + alloc_amount

        rows = []
        total_billed = Decimal('0.00')
        total_collected = Decimal('0.00')
        total_balance = Decimal('0.00')
        for g in grouped:
            student_pk = g.get('invoice__student__pk')
            billed = Decimal(g.get('total_billed') or 0)
            route_pk = g.get('transport_route__pk')
            collected = collected_map.get((student_pk, route_pk), Decimal('0.00'))
            balance = billed - collected
            if (not show_zero) and billed == Decimal('0.00') and collected == Decimal('0.00'):
                continue
            rows.append({
                'student_name': g.get('invoice__student__full_name') or '',
                'admission': g.get('invoice__student__admission_number') or '',
                'route_name': g.get('transport_route__name') or '',
                'billed': billed,
                'collected': collected,
                'balance': balance
            })
            total_billed += billed
            total_collected += collected
            total_balance += balance

        context = {
            'rows': rows,
            'totals': {'billed': total_billed, 'collected': total_collected, 'balance': total_balance},
            'filters': {
                'academic_year': academic_year,
                'term': term,
                'route': route,
                'student_class': student_class,
                'start_date': start_date,
                'end_date': end_date,
                'show_zero': show_zero,
            },
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': request.build_absolute_uri(settings.STATIC_URL + 'assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'SCHOOL_CONTACT': getattr(settings, 'SCHOOL_CONTACT', ''),
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy',
                           'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy',
                         'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'generated_by': request.user.get_full_name(),
            'generated_on': datetime.now(),
        }

        html_string = render_to_string('reports/pdf/transport_report_pdf.html', context)
        html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
        pdf_bytes = html.write_pdf()
        filename = f"transport-report-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response