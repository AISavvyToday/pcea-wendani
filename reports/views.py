# reports/views.py
from django.conf import settings
from django.utils import timezone
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.db.models import Sum, F, Value, Case, When, CharField, Q
from django.db.models.functions import TruncDate, Coalesce
from decimal import Decimal
from decimal import Decimal
from django.db.models import ExpressionWrapper, DecimalField
from .forms import (
    InvoiceReportFilterForm, FeesCollectionFilterForm,
    OutstandingBalancesFilterForm, TransportReportFilterForm
)
from .models import ReportRequest
from payments.models import Payment, PaymentAllocation
from finance.models import Invoice, InvoiceItem
from academics.models import AcademicYear, TransportFee


class InvoiceReportView(LoginRequiredMixin, View):
    template_name = 'reports/invoice_report.html'

    def get(self, request):
        form = InvoiceReportFilterForm(request.GET or None)

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
            'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'SCHOOL_CONTACT': getattr(settings, 'SCHOOL_CONTACT', ''),
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

            # Save a ReportRequest (optional)
            ReportRequest.objects.create(
                report_type='invoice_summary',
                created_by=request.user,
                academic_year=academic_year,
                term=term,
                params={'show_zero_rows': show_zero}
            )

            # Select invoices for the academic year & term
            invoices = Invoice.objects.filter(term__academic_year=academic_year, term__term=term)

            # All invoice items for those invoices
            items_qs = InvoiceItem.objects.filter(invoice__in=invoices)

            # Sum billed per category (net_amount preferred, fallback to amount)
            billed_qs = items_qs.values('category').annotate(total_billed=Sum('net_amount'))
            # Build mapping category -> billed amount
            billed_map = {row['category']: (row['total_billed'] or Decimal('0.00')) for row in billed_qs}

            # Collected per category: try to use PaymentAllocation if available
            collected_map = {}
            if PaymentAllocation is not None:
                # annotate by invoice_item__category
                alloc_qs = PaymentAllocation.objects.filter(invoice_item__invoice__in=invoices).values('invoice_item__category').annotate(collected=Sum('amount'))
                collected_map = {row['invoice_item__category']: (row['collected'] or Decimal('0.00')) for row in alloc_qs}
            else:
                # Fallback: use proportion of invoice.amount_paid distributed by item share
                # Compute per-invoice -> item distribution
                collected_map = {}
                for inv in invoices:
                    inv_items = inv.items.all()
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

            # Optional: ensure an ordered list of categories (tuition, meals, assessment, activity, transport, others)
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


class FeesCollectionReportView(LoginRequiredMixin, View):
    template_name = 'reports/fees_collection_report.html'

    def get(self, request):
        if Payment is None:
            context = {'error': 'Payment model not found in finance.models. Update reports.views to import the correct model name.'}
            return render(request, self.template_name, context)

        # initialize form with GET params
        form = FeesCollectionFilterForm(request.GET or None)

        # populate dynamic choices for class & bank using available Payment records
        # classes: collect from payment.student.current_class or payment.invoice.student.current_class
        class_qs = Payment.objects.values_list('student__current_class', flat=True).distinct()
        inv_class_qs = Payment.objects.values_list('invoice__student__current_class', flat=True).distinct()
        raw_classes = set([c for c in class_qs if c]) | set([c for c in inv_class_qs if c])
        class_choices = [('', 'All Classes')] + [(c, c) for c in sorted(raw_classes)]
        form.fields['student_class'].choices = class_choices

        # banks: try Payment.bank, otherwise Payment.payment_source, otherwise distinct payment_source
        banks = set()
        # try bank field
        if hasattr(Payment, 'bank'):
            banks.update([b for b in Payment.objects.values_list('bank', flat=True).distinct() if b])
        if hasattr(Payment, 'payment_source'):
            banks.update([b for b in Payment.objects.values_list('payment_source', flat=True).distinct() if b])
        # sometimes payment.payment_method or payment.account_name may be used; add fallbacks if needed
        form.fields['bank'].choices = [('', 'All Banks')] + [(b, b) for b in sorted(banks)]

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
            'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'SCHOOL_CONTACT': getattr(settings, 'SCHOOL_CONTACT', ''),
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
        selected_class = form.cleaned_data.get('student_class') or ''
        selected_bank = form.cleaned_data.get('bank') or ''
        group_by = form.cleaned_data.get('group_by') or 'none'

        # base queryset
        payments_qs = Payment.objects.all()

        if start_date:
            payments_qs = payments_qs.filter(payment_date__gte=start_date)
        if end_date:
            payments_qs = payments_qs.filter(payment_date__lte=end_date)

        # Filter by class: we check both Payment.student and Payment.invoice.student
        if selected_class:
            payments_qs = payments_qs.filter(
                Q(student__current_class=selected_class) |
                Q(invoice__student__current_class=selected_class)
            )

        # Filter by bank: try multiple fields
        if selected_bank:
            bank_filters = Q()
            if hasattr(Payment, 'bank'):
                bank_filters |= Q(bank=selected_bank)
            if hasattr(Payment, 'payment_source'):
                bank_filters |= Q(payment_source=selected_bank)
            # maybe also payment.account_name or payment.payment_method strings; include contains fallback
            if hasattr(Payment, 'payment_method'):
                bank_filters |= Q(payment_method__icontains=selected_bank)
            payments_qs = payments_qs.filter(bank_filters)

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
                    'class': selected_class,
                    'bank': selected_bank,
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
            student_class = None
            if hasattr(p, 'student') and p.student:
                student_name = getattr(p.student, 'full_name', None) or getattr(p.student, 'name', None) or str(p.student)
                student_class = getattr(p.student, 'current_class', None)
            elif hasattr(p, 'invoice') and getattr(p, 'invoice', None) and getattr(p.invoice, 'student', None):
                st = p.invoice.student
                student_name = getattr(st, 'full_name', None) or getattr(st, 'name', None) or str(st)
                student_class = getattr(st, 'current_class', None)
            else:
                student_name = getattr(p, 'payer_name', None) or getattr(p, 'payment_source', None) or '—'

            bank_display = getattr(p, 'bank', None) or getattr(p, 'payment_source', None) or getattr(p, 'payment_method', None) or ''

            rows.append({
                'date': p.payment_date,
                'reference': getattr(p, 'payment_reference', ''),
                'student': student_name,
                'class': student_class or '',
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
                'student_class': selected_class,
                'bank': selected_bank,
                'group_by': group_by,
            },
            'form': form,
        })

        return render(request, self.template_name, context)


class OutstandingBalancesReportView(LoginRequiredMixin, View):
    template_name = 'reports/outstanding_report.html'

    def get(self, request):
        form = OutstandingBalancesFilterForm(request.GET or None)

        # populate dynamic class choices from invoices/students
        class_choices = [('', 'All Classes')]
        try:
            raw_classes = Invoice.objects.values_list('student__current_class', flat=True).distinct()
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
            'SCHOOL_ADDRESS': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'SCHOOL_CONTACT': getattr(settings, 'SCHOOL_CONTACT', ''),
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

        # Filter by academic_year/term or date range if provided
        if academic_year:
            invoices = invoices.filter(term__academic_year=academic_year)
            if term:
                invoices = invoices.filter(term__term=term)
        if start_date:
            invoices = invoices.filter(issue_date__gte=start_date)
        if end_date:
            invoices = invoices.filter(issue_date__lte=end_date)

        # Filter by student class if specified
        if student_class:
            invoices = invoices.filter(student__current_class=student_class)

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
            'student__current_class',
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


class TransportReportView(LoginRequiredMixin, View):
    template_name = 'reports/transport_report.html'

    def get(self, request):
        form = TransportReportFilterForm(request.GET or None)

        # populate student_class choices dynamically from invoices/students (if available)
        try:
            classes_qs = Invoice.objects.values_list('student__current_class', flat=True).distinct()
            classes = sorted([c for c in classes_qs if c])
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
            items_qs = items_qs.filter(invoice__student__current_class=student_class)

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
            'invoice__student__current_class',
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
            student_cls = g.get('invoice__student__current_class') or ''
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