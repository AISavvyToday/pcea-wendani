# reports/views.py
from django.conf import settings
from django.utils import timezone
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from core.mixins import OrganizationFilterMixin
from django.shortcuts import render
from django.db.models import Sum, F, Value, Case, When, CharField, Q
from django.db.models.functions import TruncDate, Coalesce
from decimal import Decimal
from decimal import Decimal
from django.db.models import ExpressionWrapper, DecimalField
from .forms import (
    InvoiceSummaryReportFilterForm, InvoiceDetailedReportFilterForm, FeesCollectionFilterForm,
    OutstandingBalancesFilterForm, TransportReportFilterForm,
    OtherItemsReportFilterForm,
    TransferredStudentsFilterForm, GraduatedStudentsFilterForm,
    AdmittedStudentsFilterForm
)
from .models import ReportRequest
from payments.models import Payment, PaymentAllocation
from finance.models import Invoice, InvoiceItem
from academics.models import AcademicYear
from transport.models import TransportFee
from students.models import Student
from core.models import InvoiceStatus


class InvoiceReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    """Invoice Summary Report - shows summary by category."""
    template_name = 'reports/invoice_summary_report.html'

    def get(self, request):
        form = InvoiceSummaryReportFilterForm(request.GET or None)

        # School branding context
        context = {
            'form': form,
            'report_rows': None,
            'totals': None,
            'show_print_button': False,
            # School branding
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'now': timezone.now(),
        }

        if form.is_valid():
            academic_year = form.cleaned_data['academic_year']
            term = form.cleaned_data['term']
            show_zero = form.cleaned_data.get('show_zero_rows', False)

            # Select invoices for the academic year & term
            invoices = Invoice.objects.filter(term__academic_year=academic_year, term__term=term)
            
            # Apply organization filter
            organization = getattr(request, 'organization', None)
            if organization:
                invoices = invoices.filter(organization=organization)
            
            # Only include active students
            invoices = invoices.filter(student__status='active')

            # All invoice items for those invoices
            items_qs = InvoiceItem.objects.filter(invoice__in=invoices, is_active=True)

            # Sum billed per category (net_amount preferred, fallback to amount)
            billed_qs = items_qs.values('category').annotate(total_billed=Sum('net_amount'))
            # Build mapping category -> billed amount
            billed_map = {row['category']: (row['total_billed'] or Decimal('0.00')) for row in billed_qs}

            # Collected per category: try to use PaymentAllocation if available
            collected_map = {}
            if PaymentAllocation is not None:
                # annotate by invoice_item__category
                alloc_qs = PaymentAllocation.objects.filter(
                    invoice_item__in=items_qs,
                    is_active=True,
                    payment__is_active=True,
                    payment__status='completed'
                ).values('invoice_item__category').annotate(collected=Sum('amount'))
                collected_map = {row['invoice_item__category']: (row['collected'] or Decimal('0.00')) for row in alloc_qs}
            else:
                # Fallback: use proportion of invoice.amount_paid distributed by item share
                # Compute per-invoice -> item distribution
                collected_map = {}
                for inv in invoices:
                    inv_items = inv.items.filter(is_active=True)
                    inv_total = sum((i.net_amount or Decimal('0.00')) for i in inv_items)
                    paid = inv.amount_paid or Decimal('0.00')
                    if inv_total <= Decimal('0.00'):
                        # Nothing to allocate
                        continue
                    for it in inv_items:
                        cat = it.category
                        share = ((it.net_amount or Decimal('0.00')) / inv_total) * paid
                        collected_map[cat] = collected_map.get(cat, Decimal('0.00')) + (share or Decimal('0.00'))

            # Build the set of categories present
            categories = set(billed_map.keys()) | set(collected_map.keys())

            # Optional: ensure an ordered list of categories (tuition, meals, assessment, activity, transport, other)
            preferred_order = ['tuition', 'meals', 'assessment', 'activity', 'transport', 'other']
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
                if not show_zero and billed == Decimal('0.00') and collected == Decimal('0.00') and outstanding == Decimal('0.00'):
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

            # Calculate balance_bf and prepayment totals from invoices
            balance_bf_total = invoices.aggregate(total=Sum('balance_bf'))['total'] or Decimal('0.00')
            prepayment_total = invoices.aggregate(total=Sum('prepayment'))['total'] or Decimal('0.00')
            invoice_count = invoices.count()

            context.update({
                'report_rows': rows,
                'totals': {
                    'billed': total_billed,
                    'collected': total_collected,
                    'outstanding': total_outstanding,
                    'balance_bf': balance_bf_total,
                    'prepayment': prepayment_total,
                },
                'invoice_count': invoice_count,
                'academic_year': academic_year,
                'term': term,
                'show_print_button': True,
            })

        return render(request, self.template_name, context)


class InvoiceDetailedReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    """Invoice Detailed Report - shows individual students with their invoice details."""
    template_name = 'reports/invoice_detailed_report.html'

    def get(self, request):
        form = InvoiceDetailedReportFilterForm(request.GET or None)

        # populate student_class choices from Class model
        try:
            from academics.models import Class
            raw_classes = Class.objects.values_list('name', flat=True).distinct()
            classes = sorted([c for c in raw_classes if c])
            student_class_choices = [('', 'All Classes')] + [(c, c) for c in classes]
            form.fields['student_class'].choices = student_class_choices
        except Exception:
            pass

        # Populate category choices dynamically from invoice items
        try:
            # Get all unique categories and descriptions from invoice items
            categories_list = []
            # Standard categories
            standard_categories = ['tuition', 'meals', 'assessment', 'activity', 'transport', 'other']
            for cat in standard_categories:
                categories_list.append((cat, cat.title()))
            
            # Get unique descriptions from "other" category items
            other_descriptions = InvoiceItem.objects.filter(
                category='other',
                is_active=True
            ).exclude(description__isnull=True).exclude(description='').values_list('description', flat=True).distinct()
            
            for desc in sorted(set(other_descriptions)):
                if desc:
                    categories_list.append((f'other:{desc}', f'Other: {desc}'))
            
            form.fields['category'].choices = categories_list
        except Exception:
            pass

        # School branding context
        context = {
            'form': form,
            'rows': None,
            'totals': None,
            # School branding
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'now': timezone.now(),
        }

        if not form.is_valid():
            return render(request, self.template_name, context)

        # Extract filters
        academic_year = form.cleaned_data.get('academic_year')
        term = form.cleaned_data.get('term')
        student_class = form.cleaned_data.get('student_class') or ''
        name = form.cleaned_data.get('name') or ''
        admission = form.cleaned_data.get('admission') or ''
        selected_categories = form.cleaned_data.get('category') or []  # Now a list
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        show_all = form.cleaned_data.get('show_all', False)

        # Base queryset: invoices
        invoices_qs = Invoice.objects.filter(
            is_active=True
        ).exclude(
            status=InvoiceStatus.CANCELLED
        ).select_related('student', 'term__academic_year')

        # Apply organization filter
        organization = getattr(request, 'organization', None)
        if organization:
            invoices_qs = invoices_qs.filter(organization=organization)

        # Only include active students
        invoices_qs = invoices_qs.filter(student__status='active')

        # Apply filters
        if not show_all:
            if academic_year:
                invoices_qs = invoices_qs.filter(term__academic_year=academic_year)
                if term:
                    invoices_qs = invoices_qs.filter(term__term=term)
            if student_class:
                invoices_qs = invoices_qs.filter(student__current_class__name=student_class)
            if name:
                invoices_qs = invoices_qs.filter(
                    Q(student__first_name__icontains=name) |
                    Q(student__middle_name__icontains=name) |
                    Q(student__last_name__icontains=name)
                )
            if admission:
                invoices_qs = invoices_qs.filter(student__admission_number__icontains=admission)
            if start_date:
                invoices_qs = invoices_qs.filter(issue_date__gte=start_date)
            if end_date:
                invoices_qs = invoices_qs.filter(issue_date__lte=end_date)

        # Get invoice items filtered by selected categories
        items_qs = InvoiceItem.objects.filter(
            invoice__in=invoices_qs,
            is_active=True
        ).select_related('invoice__student', 'invoice')

        # Filter by selected categories if any
        if selected_categories and not show_all:
            category_filters = Q()
            for cat_choice in selected_categories:
                if cat_choice.startswith('other:'):
                    # Extract description from "other:description" format
                    desc = cat_choice.replace('other:', '', 1)
                    category_filters |= Q(category='other', description__iexact=desc)
                else:
                    # Standard category
                    category_filters |= Q(category=cat_choice)
            items_qs = items_qs.filter(category_filters)

        # Group by student and category/description to get category-specific amounts
        grouped = items_qs.values(
            'invoice__student__pk',
            'invoice__student__first_name',
            'invoice__student__middle_name',
            'invoice__student__last_name',
            'invoice__student__admission_number',
            'invoice__student__current_class__name',
            'category',
            'description',
        ).annotate(
            total_billed=Coalesce(Sum('net_amount'), Value(Decimal('0.00')), output_field=DecimalField())
        ).order_by(
            'invoice__student__first_name',
            'invoice__student__last_name',
            'category',
            'description'
        )

        # Build collected (paid) amounts map per item
        collected_map = {}
        if PaymentAllocation is not None:
            alloc_qs = PaymentAllocation.objects.filter(
                invoice_item__in=items_qs,
                is_active=True,
                payment__is_active=True,
                payment__status='completed'
            ).values(
                'invoice_item__invoice__student__pk',
                'invoice_item__category',
                'invoice_item__description'
            ).annotate(
                collected=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField())
            )

            for row in alloc_qs:
                key = (
                    row['invoice_item__invoice__student__pk'],
                    row['invoice_item__category'],
                    row['invoice_item__description'] or ''
                )
                collected_map[key] = row['collected'] or Decimal('0.00')

        # Build rows
        rows = []
        total_billed = Decimal('0.00')
        total_paid = Decimal('0.00')
        total_balance = Decimal('0.00')
        
        for row in grouped:
            student_pk = row['invoice__student__pk']
            category = row['category']
            description = row.get('description') or ''
            
            # Build category display name
            if category == 'other' and description:
                category_display = description
            else:
                category_display = category.title()
            
            # Get amounts for this specific item
            billed = row['total_billed'] or Decimal('0.00')
            key = (student_pk, category, description)
            paid = collected_map.get(key, Decimal('0.00'))
            balance = billed - paid
            
            # Build full name
            first = row.get('invoice__student__first_name', '')
            middle = row.get('invoice__student__middle_name', '')
            last = row.get('invoice__student__last_name', '')
            full_name = f"{first} {middle} {last}".strip()
            full_name = ' '.join(full_name.split())
            
            rows.append({
                'student__first_name': first,
                'student__middle_name': middle,
                'student__last_name': last,
                'student__full_name': full_name,
                'student__admission_number': row.get('invoice__student__admission_number', ''),
                'student__current_class__name': row.get('invoice__student__current_class__name', ''),
                'description': category_display,
                'total_billed': billed,
                'total_paid': paid,
                'total_balance': balance,
            })
            
            total_billed += billed
            total_paid += paid
            total_balance += balance

        context['rows'] = rows
        context['totals'] = {
            'total_billed': total_billed,
            'total_paid': total_paid,
            'total_balance': total_balance,
        }

        return render(request, self.template_name, context)


class FeesCollectionReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    template_name = 'reports/fees_collection_report.html'

    def get(self, request):
        if Payment is None:
            context = {'error': 'Payment model not found in finance.models. Update reports.views to import the correct model name.'}
            return render(request, self.template_name, context)

        # initialize form with GET params
        form = FeesCollectionFilterForm(request.GET or None)

        # populate dynamic choices for class using available Payment records
        # classes: collect from payment.student.current_class or payment.invoice.student.current_class
        class_qs = Payment.objects.values_list('student__current_class', flat=True).distinct()
        inv_class_qs = Payment.objects.values_list('invoice__student__current_class', flat=True).distinct()
        raw_classes = set([c for c in class_qs if c]) | set([c for c in inv_class_qs if c])
        class_choices = [('', 'All Classes')] + [(c, c) for c in sorted(raw_classes)]
        form.fields['student_class'].choices = class_choices

        # School branding context
        context = {
            'form': form,
            'rows': None,
            'summary': None,
            'grouped': None,
            # School branding
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'now': timezone.now(),
        }

        if not form.is_valid():
            return render(request, self.template_name, context)

        # extract filters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        payment_source = form.cleaned_data.get('payment_source') or ''
        selected_class = form.cleaned_data.get('student_class') or ''
        group_by = form.cleaned_data.get('group_by') or 'none'

        # base queryset
        payments_qs = Payment.objects.all()

        if start_date:
            payments_qs = payments_qs.filter(payment_date__gte=start_date)
        if end_date:
            payments_qs = payments_qs.filter(payment_date__lte=end_date)

        # Filter by payment source
        if payment_source:
            payments_qs = payments_qs.filter(payment_source=payment_source)

        # Filter by class: we check both Payment.student and Payment.invoice.student
        if selected_class:
            payments_qs = payments_qs.filter(
                Q(student__current_class=selected_class) |
                Q(invoice__student__current_class=selected_class)
            )

        # Optionally record the request (non-blocking)
        try:
            ReportRequest.objects.create(
                report_type='collection_analysis',
                created_by=request.user,
                academic_year=None,
                term=None,
                params={
                    'start_date': str(start_date) if start_date else None,
                    'end_date': str(end_date) if end_date else None,
                    'payment_source': payment_source,
                    'class': selected_class,
                    'group_by': group_by
                }
            )
        except Exception:
            # ignore logging errors
            pass

        # Build the payment rows for display (detailed list)
        payments_list_qs = payments_qs.select_related('student', 'invoice').order_by('payment_date')

        rows = []
        total_collected = Decimal('0.00')
        for p in payments_list_qs:
            # get student name and class (try multiple paths)
            student_name = None
            student_class_obj = None
            if hasattr(p, 'student') and p.student:
                student_name = getattr(p.student, 'full_name', None) or getattr(p.student, 'name', None) or str(p.student)
                student_class_obj = getattr(p.student, 'current_class', None)
            elif hasattr(p, 'invoice') and getattr(p, 'invoice', None) and getattr(p.invoice, 'student', None):
                st = p.invoice.student
                student_name = getattr(st, 'full_name', None) or getattr(st, 'name', None) or str(st)
                student_class_obj = getattr(st, 'current_class', None)
            else:
                student_name = getattr(p, 'payer_name', None) or getattr(p, 'payment_source', None) or '—'

            # Convert Class object to string (like in student_list template)
            student_class = str(student_class_obj) if student_class_obj else ''

            bank_display = getattr(p, 'bank', None) or getattr(p, 'payment_source', None) or getattr(p, 'payment_method', None) or ''

            rows.append({
                'date': p.payment_date,
                'reference': getattr(p, 'payment_reference', ''),
                'student': student_name,
                'class': student_class,
                'amount': p.amount or Decimal('0.00'),
                'method': p.get_payment_method_display() if hasattr(p, 'get_payment_method_display') else getattr(p, 'payment_method', ''),
                'bank': bank_display,
            })
            total_collected += p.amount or Decimal('0.00')

        # Build grouping summary if requested
        grouped = None
        if group_by == 'class':
            # annotate a class name for each payment and aggregate
            class_expr = Case(
                When(student__isnull=False, then=F('student__current_class')),
                When(invoice__isnull=False, then=F('invoice__student__current_class')),
                default=Value('Unassigned'),
                output_field=CharField()
            )
            grp_qs = payments_qs.annotate(class_name=class_expr).values('class_name').annotate(total=Coalesce(Sum('amount'), Value(0))).order_by('class_name')
            grouped = [{'group': g['class_name'] or 'Unassigned', 'total': g['total']} for g in grp_qs]
        elif group_by == 'date':
            grp_qs = payments_qs.annotate(pay_date=TruncDate('payment_date')).values('pay_date').annotate(total=Coalesce(Sum('amount'), Value(0))).order_by('pay_date')
            grouped = [{'group': g['pay_date'], 'total': g['total']} for g in grp_qs]

        context.update({
            'rows': rows,
            'summary': {
                'total_collected': total_collected,
                'count': payments_list_qs.count()
            },
            'grouped': grouped,
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'payment_source': payment_source,
                'student_class': selected_class,
                'group_by': group_by,
            },
            'form': form,
        })

        return render(request, self.template_name, context)


class OutstandingBalancesReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    template_name = 'reports/outstanding_report.html'

    def get(self, request):
        form = OutstandingBalancesFilterForm(request.GET or None)

        # populate dynamic class choices from Class model (not from students to avoid duplicates)
        class_choices = [('', 'All Classes')]
        try:
            from academics.models import Class
            # Get distinct class names directly from Class model
            raw_classes = Class.objects.values_list('name', flat=True).distinct()
            classes = sorted([c for c in raw_classes if c])
            class_choices += [(c, c) for c in classes]
            form.fields['student_class'].choices = class_choices
        except Exception:
            # leave defaults if something goes wrong
            pass

        # School branding context
        context = {
            'form': form,
            'rows': None,
            'totals': None,
            # School branding
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
            'BANK_DETAILS': getattr(settings, 'SCHOOL_BANK_DETAILS', {
                'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '1130280029105'},
                'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '01129158350600'},
                'paybills': [
                    {'label': 'PAYBILL (247247)', 'acc_format': '80029#<admission_number>'},
                    {'label': 'PAYBILL (400222)', 'acc_format': '393939#<admission_number>'},
                ]
            }),
            'now': timezone.now(),
        }

        if not form.is_valid():
            return render(request, self.template_name, context)

        # Extract filters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        academic_year = form.cleaned_data.get('academic_year')
        term = form.cleaned_data.get('term')
        student_class = form.cleaned_data.get('student_class')
        balance_op = form.cleaned_data.get('balance_operator') or 'any'
        balance_amt = form.cleaned_data.get('balance_amount') or Decimal('0.00')
        include_zero = form.cleaned_data.get('show_zero_balances')

        # Base queryset: invoices
        invoices = Invoice.objects.select_related('student', 'term__academic_year')

        # Apply organization filter
        organization = getattr(request, 'organization', None)
        if organization:
            invoices = invoices.filter(organization=organization)

        # Only include active students - exclude all non-active statuses
        invoices = invoices.filter(student__status='active')

        # Filter by academic_year/term or date range if provided
        if academic_year:
            invoices = invoices.filter(term__academic_year=academic_year)
            if term:
                invoices = invoices.filter(term__term=term)
        if start_date:
            invoices = invoices.filter(issue_date__gte=start_date)
        if end_date:
            invoices = invoices.filter(issue_date__lte=end_date)

        # Filter by student class if specified (match by class name)
        if student_class:
            invoices = invoices.filter(student__current_class__name=student_class)

        # Aggregate per student
        # Use Coalesce to ensure numeric 0 instead of None
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

        # Values grouped by student (only essential fields)
        grouped_qs = invoices.values(
            'student__pk',
            'student__admission_number',
            'student__first_name',
            'student__middle_name',
            'student__last_name',
            'student__current_class__name',  # Get class name instead of UUID
            'term__academic_year__year',
        ).annotate(**annotations).order_by('-total_balance', 'student__first_name', 'student__last_name')

        # Apply balance filter on annotated field if requested
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

        # If not including zero balances, drop rows with total_balance == 0
        if not include_zero:
            grouped_qs = grouped_qs.exclude(total_balance=Decimal('0.00'))

        rows = list(grouped_qs)

        # Compute grand totals
        totals = {
            'total_billed': sum((r['total_billed'] or Decimal('0.00')) for r in rows),
            'total_paid': sum((r['total_paid'] or Decimal('0.00')) for r in rows),
            'total_balance': sum((r['total_balance'] or Decimal('0.00')) for r in rows),
            'total_balance_bf': sum((r['total_balance_bf'] or Decimal('0.00')) for r in rows),
            'total_prepayment': sum((r['total_prepayment'] or Decimal('0.00')) for r in rows),
        }

        # Optional: record report request
        try:
            ReportRequest.objects.create(
                report_type='outstanding',
                created_by=request.user,
                academic_year=academic_year,
                term=term,
                params={
                    'start_date': str(start_date) if start_date else None,
                    'end_date': str(end_date) if end_date else None,
                    'class': student_class,
                    'balance_op': balance_op,
                    'balance_amt': str(balance_amt)
                }
            )
        except Exception:
            pass

        context.update({
            'rows': rows,
            'totals': totals,
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'academic_year': academic_year,
                'term': term,
                'student_class': student_class,
                'balance_op': balance_op,
                'balance_amt': balance_amt,
            }
        })

        return render(request, self.template_name, context)


class TransportReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    template_name = 'reports/transport_report.html'

    def get(self, request):
        form = TransportReportFilterForm(request.GET or None)

        # populate student_class choices from Class model (not from invoices to avoid duplicates)
        try:
            from academics.models import Class
            # Get distinct class names directly from Class model
            raw_classes = Class.objects.values_list('name', flat=True).distinct()
            classes = sorted([c for c in raw_classes if c])
            student_class_choices = [('', 'All Classes')] + [(c, c) for c in classes]
            form.fields['student_class'].choices = student_class_choices
        except Exception:
            # ignore if access fails
            pass

        # School branding context
        context = {
            'form': form,
            'rows': None,
            'totals': None,
            # School branding
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
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
            'now': timezone.now(),
        }

        if not form.is_valid():
            return render(request, self.template_name, context)

        # filters
        academic_year = form.cleaned_data['academic_year']
        term = form.cleaned_data['term']
        route = form.cleaned_data.get('route')
        student_class = form.cleaned_data.get('student_class') or ''
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        show_zero = form.cleaned_data.get('show_zero_rows', False)

        # base transport items queryset for the selected academic year & term
        items_qs = InvoiceItem.objects.filter(
            invoice__term__academic_year=academic_year,
            invoice__term__term=term,
            category='transport'  # ensure transport items only
        ).select_related('invoice__student', 'transport_route')

        if route:
            items_qs = items_qs.filter(transport_route=route)

        if student_class:
            items_qs = items_qs.filter(invoice__student__current_class__name=student_class)

        if start_date:
            items_qs = items_qs.filter(invoice__issue_date__gte=start_date)
        if end_date:
            items_qs = items_qs.filter(invoice__issue_date__lte=end_date)

        # Aggregate billed transport per student+route+trip_type
        # FIX: Use individual name fields instead of full_name
        grouped = items_qs.values(
            'invoice__student__pk',
            'invoice__student__first_name',  # Changed from full_name
            'invoice__student__middle_name',  # Added
            'invoice__student__last_name',  # Added
            'invoice__student__admission_number',
            'invoice__student__current_class__name',  # Get class name instead of UUID
            'invoice__student__residence',  # Added for destination
            'transport_route__pk',
            'transport_route__name',
            'transport_trip_type',  # Added for trip type
        ).annotate(
            total_billed=Coalesce(Sum('net_amount'), Value(Decimal('0.00')), output_field=DecimalField())
        ).order_by(
            'invoice__student__first_name',
            'invoice__student__last_name'
        )

        # Build a map for collected (paid) amounts per (student_pk, route_pk)
        collected_map = {}

        if PaymentAllocation is not None:
            # Use allocations mapped to invoice items
            # FIX: Added output_field=DecimalField() to Coalesce
            alloc_qs = PaymentAllocation.objects.filter(invoice_item__in=items_qs).values(
                'invoice_item__invoice__student__pk',
                'invoice_item__transport_route__pk'
            ).annotate(
                collected=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField())
            )

            for row in alloc_qs:
                key = (row.get('invoice_item__invoice__student__pk'), row.get('invoice_item__transport_route__pk'))
                collected_map[key] = Decimal(row.get('collected') or 0)
        else:
            # Fallback: proportional allocation of invoice.amount_paid across items in that invoice
            invoice_ids = items_qs.values_list('invoice_id', flat=True).distinct()
            invoices = Invoice.objects.filter(id__in=invoice_ids).select_related('student')
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

        # Build rows for template
        rows = []
        total_billed = Decimal('0.00')
        total_collected = Decimal('0.00')
        total_balance = Decimal('0.00')

        for g in grouped:
            student_pk = g.get('invoice__student__pk')
            # Build full name from individual fields
            first_name = g.get('invoice__student__first_name') or ''
            middle_name = g.get('invoice__student__middle_name') or ''
            last_name = g.get('invoice__student__last_name') or ''
            student_name = f"{first_name} {middle_name} {last_name}".strip()
            # Clean up extra spaces
            student_name = ' '.join(student_name.split())

            admission = g.get('invoice__student__admission_number') or ''
            student_cls = g.get('invoice__student__current_class__name') or 'Not assigned'
            route_pk = g.get('transport_route__pk')
            route_name = g.get('transport_route__name') or ''
            billed = Decimal(g.get('total_billed') or 0)
            collected = collected_map.get((student_pk, route_pk), Decimal('0.00'))
            balance = billed - collected

            if (not show_zero) and billed == Decimal('0.00') and collected == Decimal('0.00') and balance == Decimal(
                    '0.00'):
                continue

            # Get trip type display
            trip_type_raw = g.get('transport_trip_type') or ''
            trip_type_map = {'full': 'Full Trip', 'half': 'Half Trip'}
            trip_type = trip_type_map.get(trip_type_raw, 'Full Trip')
            
            # Get destination from student residence
            destination = g.get('invoice__student__residence') or ''

            rows.append({
                'student_pk': student_pk,
                'student_name': student_name,
                'admission': admission,
                'student_class': student_cls,
                'route_pk': route_pk,
                'route_name': route_name,
                'trip_type': trip_type,
                'destination': destination,
                'billed': billed,
                'collected': collected,
                'balance': balance
            })

            total_billed += billed
            total_collected += collected
            total_balance += balance

        context.update({
            'rows': rows,
            'totals': {
                'billed': total_billed,
                'collected': total_collected,
                'balance': total_balance
            },
            'filters': {
                'academic_year': academic_year,
                'term': term,
                'route': route,
                'student_class': student_class,
                'start_date': start_date,
                'end_date': end_date,
                'show_zero': show_zero,
            }
        })

        # Optionally log the report request
        try:
            ReportRequest.objects.create(
                report_type='transport',
                created_by=request.user,
                academic_year=academic_year,
                term=term,
                params={
                    'route': route.pk if route else None,
                    'student_class': student_class,
                    'start_date': str(start_date) if start_date else None,
                    'end_date': str(end_date) if end_date else None
                }
            )
        except Exception:
            pass

        return render(request, self.template_name, context)


class OtherItemsReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    template_name = 'reports/other_items_report.html'

    def get(self, request):
        from .forms import OtherItemsReportFilterForm
        form = OtherItemsReportFilterForm(request.GET or None)

        # populate student_class choices from Class model
        try:
            from academics.models import Class
            raw_classes = Class.objects.values_list('name', flat=True).distinct()
            classes = sorted([c for c in raw_classes if c])
            student_class_choices = [('', 'All Classes')] + [(c, c) for c in classes]
            form.fields['student_class'].choices = student_class_choices
        except Exception:
            pass

        # School branding context
        context = {
            'form': form,
            'rows': None,
            'totals': None,
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
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
            'now': timezone.now(),
        }

        if not form.is_valid():
            return render(request, self.template_name, context)

        # Extract filters
        academic_year = form.cleaned_data.get('academic_year')
        term = form.cleaned_data.get('term')
        student_class = form.cleaned_data.get('student_class') or ''
        name = form.cleaned_data.get('name') or ''
        admission = form.cleaned_data.get('admission') or ''
        category = form.cleaned_data.get('category') or ''
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        show_all = form.cleaned_data.get('show_all', False)

        # Base queryset: other items only
        items_qs = InvoiceItem.objects.filter(
            category='other'
        ).select_related('invoice__student', 'invoice__term__academic_year')

        # Apply organization filter
        organization = getattr(request, 'organization', None)
        if organization:
            items_qs = items_qs.filter(invoice__organization=organization)

        # Apply filters
        if not show_all:
            if academic_year:
                items_qs = items_qs.filter(invoice__term__academic_year=academic_year)
                if term:
                    items_qs = items_qs.filter(invoice__term__term=term)
            if student_class:
                items_qs = items_qs.filter(invoice__student__current_class__name=student_class)
            if name:
                items_qs = items_qs.filter(
                    Q(invoice__student__first_name__icontains=name) |
                    Q(invoice__student__middle_name__icontains=name) |
                    Q(invoice__student__last_name__icontains=name)
                )
            if admission:
                items_qs = items_qs.filter(invoice__student__admission_number__icontains=admission)
            if category:
                items_qs = items_qs.filter(description__icontains=category)
            if start_date:
                items_qs = items_qs.filter(invoice__issue_date__gte=start_date)
            if end_date:
                items_qs = items_qs.filter(invoice__issue_date__lte=end_date)

        # Group by student and category (description)
        grouped = items_qs.values(
            'invoice__student__pk',
            'invoice__student__first_name',
            'invoice__student__middle_name',
            'invoice__student__last_name',
            'invoice__student__admission_number',
            'invoice__student__current_class__name',
            'description',  # This is the category
        ).annotate(
            total_billed=Coalesce(Sum('net_amount'), Value(Decimal('0.00')), output_field=DecimalField())
        ).order_by(
            'invoice__student__first_name',
            'invoice__student__last_name',
            'description'
        )

        # Build collected (paid) amounts map
        collected_map = {}
        if PaymentAllocation is not None:
            alloc_qs = PaymentAllocation.objects.filter(
                invoice_item__in=items_qs,
                is_active=True,
                payment__is_active=True,
                payment__status='completed'
            ).values(
                'invoice_item__invoice__student__pk',
                'invoice_item__description'
            ).annotate(
                collected=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField())
            )

            for row in alloc_qs:
                key = (
                    row.get('invoice_item__invoice__student__pk'),
                    row.get('invoice_item__description')
                )
                collected_map[key] = Decimal(row.get('collected') or 0)

        # Build rows
        rows = []
        total_billed = Decimal('0.00')
        total_collected = Decimal('0.00')
        total_balance = Decimal('0.00')

        for g in grouped:
            student_pk = g.get('invoice__student__pk')
            first_name = g.get('invoice__student__first_name') or ''
            middle_name = g.get('invoice__student__middle_name') or ''
            last_name = g.get('invoice__student__last_name') or ''
            student_name = f"{first_name} {middle_name} {last_name}".strip()
            student_name = ' '.join(student_name.split())

            admission = g.get('invoice__student__admission_number') or ''
            student_cls = g.get('invoice__student__current_class__name') or 'Not assigned'
            category_desc = g.get('description') or 'Other'
            billed = Decimal(g.get('total_billed') or 0)
            collected = collected_map.get((student_pk, category_desc), Decimal('0.00'))
            balance = billed - collected

            rows.append({
                'student_pk': student_pk,
                'student_name': student_name,
                'admission': admission,
                'student_class': student_cls,
                'category': category_desc,
                'billed': billed,
                'collected': collected,
                'balance': balance
            })

            total_billed += billed
            total_collected += collected
            total_balance += balance

        context.update({
            'rows': rows,
            'totals': {
                'billed': total_billed,
                'collected': total_collected,
                'balance': total_balance
            },
            'filters': {
                'academic_year': academic_year,
                'term': term,
                'student_class': student_class,
                'name': name,
                'admission': admission,
                'category': category,
                'start_date': start_date,
                'end_date': end_date,
                'show_all': show_all,
            }
        })

        # Log report request
        try:
            ReportRequest.objects.create(
                report_type='other_items',
                created_by=request.user,
                academic_year=academic_year,
                term=term,
                params={
                    'student_class': student_class,
                    'name': name,
                    'admission': admission,
                    'category': category,
                    'start_date': str(start_date) if start_date else None,
                    'end_date': str(end_date) if end_date else None
                }
            )
        except Exception:
            pass

        return render(request, self.template_name, context)


class TransferredStudentsReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    template_name = 'reports/transferred_students_report.html'

    def get(self, request):
        form = TransferredStudentsFilterForm(request.GET or None)

        # Populate dynamic class choices from Class model (not from students to avoid duplicates)
        class_choices = [('', 'All Classes')]
        try:
            from academics.models import Class
            # Get distinct class names directly from Class model
            raw_classes = Class.objects.values_list('name', flat=True).distinct()
            classes = sorted([c for c in raw_classes if c])
            class_choices += [(c, c) for c in classes]
            form.fields['student_class'].choices = class_choices
        except Exception:
            pass

        # School branding context
        context = {
            'form': form,
            'rows': None,
            # School branding
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
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
            'now': timezone.now(),
        }

        if not form.is_valid():
            return render(request, self.template_name, context)

        # Extract filters
        academic_year = form.cleaned_data.get('academic_year')
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        student_class = form.cleaned_data.get('student_class')

        # Base queryset: transferred students
        students_qs = Student.objects.filter(status='transferred').select_related('current_class')

        # Filter by academic year (if provided, filter by status_date within that year)
        if academic_year:
            students_qs = students_qs.filter(
                status_date__year=academic_year.year
            )

        # Filter by date range (status_date)
        if start_date:
            students_qs = students_qs.filter(status_date__gte=start_date)
        if end_date:
            students_qs = students_qs.filter(status_date__lte=end_date)

        # Filter by class
        if student_class:
            students_qs = students_qs.filter(current_class__name=student_class)

        # Get invoice data for transferred students
        from finance.models import Invoice
        from django.db.models import Sum, Value
        from django.db.models.functions import Coalesce
        from django.db.models import ExpressionWrapper, DecimalField
        
        invoices = Invoice.objects.filter(
            student__status='transferred',
            student__in=students_qs
        ).select_related('student', 'term__academic_year')
        
        # Apply organization filter
        organization = getattr(request, 'organization', None)
        if organization:
            invoices = invoices.filter(organization=organization)
        
        # Aggregate per student
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
        
        grouped_invoices = invoices.values(
            'student__pk',
            'student__admission_number',
            'student__first_name',
            'student__middle_name',
            'student__last_name',
            'student__current_class__name',
        ).annotate(**annotations)
        
        # Create a map of student PK to invoice totals
        invoice_map = {item['student__pk']: item for item in grouped_invoices}
        
        # Build rows for display with balance information
        rows = []
        totals = {
            'total_balance_bf': Decimal('0.00'),
            'total_prepayment': Decimal('0.00'),
            'total_billed': Decimal('0.00'),
            'total_paid': Decimal('0.00'),
            'total_balance': Decimal('0.00'),
        }
        
        for student in students_qs.order_by('first_name', 'last_name'):
            invoice_data = invoice_map.get(student.pk, {})
            balance_bf = invoice_data.get('total_balance_bf', Decimal('0.00')) or Decimal('0.00')
            prepayment = invoice_data.get('total_prepayment', Decimal('0.00')) or Decimal('0.00')
            total_billed = invoice_data.get('total_billed', Decimal('0.00')) or Decimal('0.00')
            total_paid = invoice_data.get('total_paid', Decimal('0.00')) or Decimal('0.00')
            total_balance = invoice_data.get('total_balance', Decimal('0.00')) or Decimal('0.00')
            
            totals['total_balance_bf'] += balance_bf
            totals['total_prepayment'] += prepayment
            totals['total_billed'] += total_billed
            totals['total_paid'] += total_paid
            totals['total_balance'] += total_balance
            
            rows.append({
                'student_pk': student.pk,
                'name': student.full_name,
                'admission_number': student.admission_number or 'N/A',
                'grade': student.current_class.name if student.current_class else 'Not assigned',
                'transfer_date': student.status_date.date() if student.status_date else None,
                'balance_bf': balance_bf,
                'prepayment': prepayment,
                'total_billed': total_billed,
                'total_paid': total_paid,
                'total_balance': total_balance,
            })

        context.update({
            'rows': rows,
            'totals': totals,
            'filters': {
                'academic_year': academic_year,
                'start_date': start_date,
                'end_date': end_date,
                'student_class': student_class,
            }
        })

        # Optionally log the report request
        try:
            ReportRequest.objects.create(
                report_type='transferred_students',
                created_by=request.user,
                academic_year=academic_year,
                term=None,
                params={
                    'start_date': str(start_date) if start_date else None,
                    'end_date': str(end_date) if end_date else None,
                    'class': student_class,
                }
            )
        except Exception:
            pass

        return render(request, self.template_name, context)


class GraduatedStudentsReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    template_name = 'reports/graduated_students_report.html'

    def get(self, request):
        from .forms import GraduatedStudentsFilterForm
        form = GraduatedStudentsFilterForm(request.GET or None)

        # Populate dynamic class choices from Class model
        class_choices = [('', 'All Classes')]
        try:
            from academics.models import Class
            raw_classes = Class.objects.values_list('name', flat=True).distinct()
            classes = sorted([c for c in raw_classes if c])
            class_choices += [(c, c) for c in classes]
            form.fields['student_class'].choices = class_choices
        except Exception:
            pass

        # School branding context
        context = {
            'form': form,
            'rows': None,
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
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
            'now': timezone.now(),
        }

        if not form.is_valid():
            return render(request, self.template_name, context)

        # Extract filters
        academic_year = form.cleaned_data.get('academic_year')
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        student_class = form.cleaned_data.get('student_class')

        # Base queryset: graduated students
        students_qs = Student.objects.filter(status='graduated').select_related('current_class')

        # Filter by academic year
        if academic_year:
            students_qs = students_qs.filter(
                status_date__year=academic_year.year
            )

        # Filter by date range (status_date)
        if start_date:
            students_qs = students_qs.filter(status_date__gte=start_date)
        if end_date:
            students_qs = students_qs.filter(status_date__lte=end_date)

        # Filter by class
        if student_class:
            students_qs = students_qs.filter(current_class__name=student_class)

        # Get invoice data for graduated students
        from finance.models import Invoice
        from django.db.models import Sum, Value
        from django.db.models.functions import Coalesce
        from django.db.models import ExpressionWrapper, DecimalField
        
        invoices = Invoice.objects.filter(
            student__status='graduated',
            student__in=students_qs
        ).select_related('student', 'term__academic_year')
        
        # Apply organization filter
        organization = getattr(request, 'organization', None)
        if organization:
            invoices = invoices.filter(organization=organization)
        
        # Aggregate per student
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
        
        grouped_invoices = invoices.values(
            'student__pk',
            'student__admission_number',
            'student__first_name',
            'student__middle_name',
            'student__last_name',
            'student__current_class__name',
        ).annotate(**annotations)
        
        # Create a map of student PK to invoice totals
        invoice_map = {item['student__pk']: item for item in grouped_invoices}
        
        # Build rows for display with balance information
        rows = []
        totals = {
            'total_balance_bf': Decimal('0.00'),
            'total_prepayment': Decimal('0.00'),
            'total_billed': Decimal('0.00'),
            'total_paid': Decimal('0.00'),
            'total_balance': Decimal('0.00'),
        }
        
        for student in students_qs.order_by('first_name', 'last_name'):
            invoice_data = invoice_map.get(student.pk, {})
            balance_bf = invoice_data.get('total_balance_bf', Decimal('0.00')) or Decimal('0.00')
            prepayment = invoice_data.get('total_prepayment', Decimal('0.00')) or Decimal('0.00')
            total_billed = invoice_data.get('total_billed', Decimal('0.00')) or Decimal('0.00')
            total_paid = invoice_data.get('total_paid', Decimal('0.00')) or Decimal('0.00')
            total_balance = invoice_data.get('total_balance', Decimal('0.00')) or Decimal('0.00')
            
            totals['total_balance_bf'] += balance_bf
            totals['total_prepayment'] += prepayment
            totals['total_billed'] += total_billed
            totals['total_paid'] += total_paid
            totals['total_balance'] += total_balance
            
            rows.append({
                'student_pk': student.pk,
                'name': student.full_name,
                'admission_number': student.admission_number or 'N/A',
                'grade': student.current_class.name if student.current_class else 'Not assigned',
                'graduation_date': student.status_date.date() if student.status_date else None,
                'balance_bf': balance_bf,
                'prepayment': prepayment,
                'total_billed': total_billed,
                'total_paid': total_paid,
                'total_balance': total_balance,
            })

        context.update({
            'rows': rows,
            'totals': totals,
            'filters': {
                'academic_year': academic_year,
                'start_date': start_date,
                'end_date': end_date,
                'student_class': student_class,
            }
        })

        # Optionally log the report request
        try:
            ReportRequest.objects.create(
                report_type='graduated_students',
                created_by=request.user,
                academic_year=academic_year,
                term=None,
                params={
                    'start_date': str(start_date) if start_date else None,
                    'end_date': str(end_date) if end_date else None,
                    'class': student_class,
                }
            )
        except Exception:
            pass

        return render(request, self.template_name, context)


class AdmittedStudentsReportView(LoginRequiredMixin, OrganizationFilterMixin, View):
    template_name = 'reports/admitted_students_report.html'

    def get(self, request):
        form = AdmittedStudentsFilterForm(request.GET or None)

        # Populate dynamic class choices from Class model (not from students to avoid duplicates)
        class_choices = [('', 'All Classes')]
        try:
            from academics.models import Class
            # Get distinct class names directly from Class model
            raw_classes = Class.objects.values_list('name', flat=True).distinct()
            classes = sorted([c for c in raw_classes if c])
            class_choices += [(c, c) for c in classes]
            form.fields['student_class'].choices = class_choices
        except Exception:
            pass

        # School branding context
        context = {
            'form': form,
            'rows': None,
            # School branding
            'SCHOOL_NAME': getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy'),
            'SCHOOL_LOGO_URL': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
            'SPONSOR_LOGO_URL': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
            'SCHOOL_ADDRESS': 'Box 57517-00200 Nairobi',
            'SCHOOL_CONTACT': '0796675605',
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
            'now': timezone.now(),
        }

        if not form.is_valid():
            return render(request, self.template_name, context)

        # Extract filters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        student_class = form.cleaned_data.get('student_class')

        # Default to current year if no dates provided
        if not start_date:
            start_date = timezone.now().replace(month=1, day=1).date()
        if not end_date:
            end_date = timezone.now().date()

        # Base queryset: students with admission_date
        students_qs = Student.objects.filter(
            admission_date__isnull=False
        ).select_related('current_class')

        # Filter by admission date range
        if start_date:
            students_qs = students_qs.filter(admission_date__gte=start_date)
        if end_date:
            students_qs = students_qs.filter(admission_date__lte=end_date)

        # Filter by class
        if student_class:
            students_qs = students_qs.filter(current_class__name=student_class)

        # Build rows for display
        rows = []
        for student in students_qs.order_by('admission_date', 'first_name', 'last_name'):
            rows.append({
                'student_pk': student.pk,
                'name': student.full_name,
                'admission_number': student.admission_number or 'N/A',
                'admission_date': student.admission_date,
                'grade': student.current_class.name if student.current_class else 'Not assigned',
            })

        context.update({
            'rows': rows,
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'student_class': student_class,
            }
        })

        # Optionally log the report request
        try:
            ReportRequest.objects.create(
                report_type='admitted_students',
                created_by=request.user,
                academic_year=None,
                term=None,
                params={
                    'start_date': str(start_date) if start_date else None,
                    'end_date': str(end_date) if end_date else None,
                    'class': student_class,
                }
            )
        except Exception:
            pass

        return render(request, self.template_name, context)