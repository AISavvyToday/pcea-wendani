from decimal import Decimal

from django.db.models import Q, Sum, Prefetch
from django.utils import timezone

from core.models import FeeCategory, InvoiceStatus, PaymentSource, PaymentStatus
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from students.models import Student, StudentParent


REPORT_CATEGORY_LABELS = {
    FeeCategory.TUITION: "Tuition",
    FeeCategory.MEALS: "Meals",
    FeeCategory.EXAMINATION: "Examination",
    FeeCategory.ACTIVITY: "Activity",
    FeeCategory.TRANSPORT: "Transport",
    FeeCategory.ADMISSION: "Admission",
    FeeCategory.OTHER: "Educational Activities",
    FeeCategory.BALANCE_BF: "Balance B/F",
    FeeCategory.PREPAYMENT_CREDIT: "Prepayments",
    # Legacy alias still found in some historical data
    'assessment': "Examination",
}

REPORT_CATEGORY_SEQUENCE = [
    FeeCategory.TUITION,
    FeeCategory.MEALS,
    FeeCategory.EXAMINATION,
    FeeCategory.ACTIVITY,
    FeeCategory.TRANSPORT,
    FeeCategory.ADMISSION,
    FeeCategory.OTHER,
    FeeCategory.BALANCE_BF,
    FeeCategory.PREPAYMENT_CREDIT,
]

DETAIL_FILTER_CATEGORY_SEQUENCE = [
    FeeCategory.TUITION,
    FeeCategory.MEALS,
    FeeCategory.EXAMINATION,
    FeeCategory.ACTIVITY,
    FeeCategory.TRANSPORT,
    FeeCategory.ADMISSION,
]

LEGACY_CATEGORY_ALIASES = {
    'assessment': FeeCategory.EXAMINATION,
}

BALANCE_PRESETS = {
    'lt_5000': ('<', Decimal('5000'), 'Under 5,000'),
    'gte_5000_lt_10000': ('range', Decimal('5000'), Decimal('10000'), '5,000 - 10,000'),
    'gte_10000_lt_25000': ('range', Decimal('10000'), Decimal('25000'), '10,000 - 25,000'),
    'gte_25000_lt_50000': ('range', Decimal('25000'), Decimal('50000'), '25,000 - 50,000'),
    'gte_50000_lt_100000': ('range', Decimal('50000'), Decimal('100000'), '50,000 - 100,000'),
    'gte_100000': ('>=', Decimal('100000'), 'Over 100,000'),
}


def get_report_category_label(category):
    normalized = normalize_invoice_detail_category_value(category)
    if normalized in REPORT_CATEGORY_LABELS:
        return REPORT_CATEGORY_LABELS[normalized]

    fee_category_map = dict(FeeCategory.choices)
    if normalized in fee_category_map:
        return fee_category_map[normalized]

    return str(normalized).replace("_", " ").title()


def order_report_categories(categories):
    normalized_categories = [normalize_invoice_detail_category_value(category) for category in categories]
    ordered = [category for category in REPORT_CATEGORY_SEQUENCE if category in normalized_categories]
    extras = sorted(
        [category for category in normalized_categories if category not in ordered],
        key=lambda category: get_report_category_label(category).lower(),
    )
    return ordered + extras


def build_invoice_summary_rows(billed_map, collected_map, show_zero=False):
    categories = set(billed_map.keys()) | set(collected_map.keys())
    rows = []
    total_billed = Decimal("0.00")
    total_collected = Decimal("0.00")
    total_outstanding = Decimal("0.00")

    for category in order_report_categories(categories):
        billed = billed_map.get(category, Decimal("0.00"))
        collected = collected_map.get(category, Decimal("0.00"))
        outstanding = billed - collected
        if (
            not show_zero
            and billed == Decimal("0.00")
            and collected == Decimal("0.00")
            and outstanding == Decimal("0.00")
        ):
            continue

        rows.append(
            {
                "category": category,
                "category_display": get_report_category_label(category),
                "total_billed": billed,
                "collected": collected,
                "outstanding": outstanding,
            }
        )
        total_billed += billed
        total_collected += collected
        total_outstanding += outstanding

    return rows, total_billed, total_collected, total_outstanding


def get_invoice_adjustment_totals(invoices):
    totals = invoices.aggregate(
        total_balance_bf=Sum("balance_bf"),
        total_prepayment=Sum("prepayment"),
    )
    balance_bf = totals.get("total_balance_bf") or Decimal("0.00")
    prepayment = totals.get("total_prepayment") or Decimal("0.00")
    return {
        "balance_bf": balance_bf,
        "prepayment": prepayment,
        "prepayment_display": display_prepayment_amount(prepayment),
    }


def display_prepayment_amount(value):
    return abs(value or Decimal("0.00"))


def normalize_invoice_detail_category_value(category):
    return LEGACY_CATEGORY_ALIASES.get(category, category)


def get_equivalent_invoice_detail_categories(category):
    normalized = normalize_invoice_detail_category_value(category)
    if normalized == FeeCategory.EXAMINATION:
        return [FeeCategory.EXAMINATION, 'assessment']
    return [normalized]


def build_invoice_detail_category_choices(selected_categories=None, include_all_other_descriptions=True):
    categories_list = [
        (category, get_report_category_label(category))
        for category in DETAIL_FILTER_CATEGORY_SEQUENCE
    ]

    if not include_all_other_descriptions and selected_categories:
        unique_descriptions = []
        seen = set()
        for category in selected_categories:
            if not str(category).startswith(f"{FeeCategory.OTHER}:"):
                continue
            description = str(category).split(':', 1)[1].strip()
            lowered = description.lower()
            if description and lowered not in seen:
                seen.add(lowered)
                unique_descriptions.append(description)
    else:
        other_descriptions_raw = (
            InvoiceItem.objects.filter(category=FeeCategory.OTHER, is_active=True)
            .exclude(description__isnull=True)
            .exclude(description="")
            .values_list("description", flat=True)
            .distinct()
        )

        seen_descriptions = set()
        unique_descriptions = []
        for description in other_descriptions_raw:
            if not description:
                continue
            normalized = description.strip()
            lowered = normalized.lower()
            if lowered in seen_descriptions:
                continue
            seen_descriptions.add(lowered)
            unique_descriptions.append(normalized)

        unique_descriptions.sort(key=str.lower)

    other_label = get_report_category_label(FeeCategory.OTHER)
    for description in unique_descriptions:
        categories_list.append((f"{FeeCategory.OTHER}:{description}", f"{other_label}: {description}"))

    categories_list.append((FeeCategory.OTHER, get_report_category_label(FeeCategory.OTHER)))
    return categories_list


def get_invoice_detail_category_choices():
    return build_invoice_detail_category_choices()



def get_invoice_detail_category_display(category, description=""):
    normalized = normalize_invoice_detail_category_value(category)
    if normalized == FeeCategory.OTHER and description:
        return description
    return get_report_category_label(normalized)


def get_selected_category_labels(selected_categories):
    labels = []
    other_label = get_report_category_label(FeeCategory.OTHER)
    for category in selected_categories or []:
        if str(category).startswith(f"{FeeCategory.OTHER}:"):
            labels.append(f"{other_label}: {str(category).split(':', 1)[1]}")
            continue
        labels.append(get_report_category_label(category))
    return labels


def get_invoice_detail_sort_key(category, description=""):
    normalized = normalize_invoice_detail_category_value(category)
    try:
        category_index = REPORT_CATEGORY_SEQUENCE.index(normalized)
    except ValueError:
        category_index = len(REPORT_CATEGORY_SEQUENCE)
    display = get_invoice_detail_category_display(category, description)
    return (category_index, display.lower(), (description or '').lower())


def build_invoice_detail_category_filter(selected_categories):
    category_filters = Q()
    for category_choice in selected_categories or []:
        if str(category_choice).startswith(f"{FeeCategory.OTHER}:"):
            description = str(category_choice).split(':', 1)[1].strip()
            category_filters |= Q(category=FeeCategory.OTHER, description__iexact=description)
            continue

        equivalent_categories = get_equivalent_invoice_detail_categories(category_choice)
        category_filters |= Q(category__in=equivalent_categories)

    return category_filters


def _filter_invoice_detailed_base_queryset(
    organization=None,
    academic_year=None,
    term=None,
    student_class='',
    name='',
    admission='',
    show_all=False,
):
    invoices_qs = (
        Invoice.objects.filter(is_active=True)
        .exclude(status=InvoiceStatus.CANCELLED)
        .select_related('student', 'term__academic_year')
    )

    if organization:
        invoices_qs = invoices_qs.filter(organization=organization)

    invoices_qs = invoices_qs.filter(student__status='active')

    if not show_all:
        if academic_year:
            invoices_qs = invoices_qs.filter(term__academic_year=academic_year)
            if term:
                invoices_qs = invoices_qs.filter(term__term=term)
        if student_class:
            invoices_qs = invoices_qs.filter(student__current_class__name=student_class)
        if name:
            invoices_qs = invoices_qs.filter(
                Q(student__first_name__icontains=name)
                | Q(student__middle_name__icontains=name)
                | Q(student__last_name__icontains=name)
            )
        if admission:
            invoices_qs = invoices_qs.filter(student__admission_number__icontains=admission)

    return invoices_qs


def _apply_invoice_activity_window(invoices_qs, start_date=None, end_date=None):
    if not start_date and not end_date:
        return invoices_qs

    issue_qs = invoices_qs
    if start_date:
        issue_qs = issue_qs.filter(issue_date__gte=start_date)
    if end_date:
        issue_qs = issue_qs.filter(issue_date__lte=end_date)

    allocation_qs = PaymentAllocation.objects.filter(
        invoice_item__invoice__in=invoices_qs,
        is_active=True,
        payment__is_active=True,
        payment__status=PaymentStatus.COMPLETED,
    )
    if start_date:
        allocation_qs = allocation_qs.filter(payment__payment_date__date__gte=start_date)
    if end_date:
        allocation_qs = allocation_qs.filter(payment__payment_date__date__lte=end_date)

    issue_ids = issue_qs.values_list('pk', flat=True)
    activity_ids = allocation_qs.values_list('invoice_item__invoice_id', flat=True).distinct()
    return invoices_qs.filter(Q(pk__in=issue_ids) | Q(pk__in=activity_ids)).distinct()


def build_invoice_detailed_report_data(
    organization=None,
    academic_year=None,
    term=None,
    student_class='',
    payment_source='',
    name='',
    admission='',
    selected_categories=None,
    start_date=None,
    end_date=None,
    show_all=False,
):
    selected_categories = selected_categories or []

    invoices_qs = _filter_invoice_detailed_base_queryset(
        organization=organization,
        academic_year=academic_year,
        term=term,
        student_class=student_class,
        name=name,
        admission=admission,
        show_all=show_all,
    )

    invoices_qs = _apply_invoice_activity_window(
        invoices_qs,
        start_date=start_date if not show_all else None,
        end_date=end_date if not show_all else None,
    )

    items_qs = (
        InvoiceItem.objects.filter(invoice__in=invoices_qs, is_active=True)
        .select_related('invoice__student', 'invoice')
    )

    if selected_categories and not show_all:
        items_qs = items_qs.filter(build_invoice_detail_category_filter(selected_categories))

    grouped = (
        items_qs.values(
            'invoice__student__pk',
            'invoice__student__first_name',
            'invoice__student__middle_name',
            'invoice__student__last_name',
            'invoice__student__admission_number',
            'invoice__student__current_class__name',
            'category',
            'description',
        )
        .annotate(total_billed=Sum('net_amount'))
        .order_by(
            'invoice__student__first_name',
            'invoice__student__last_name',
            'category',
            'description',
        )
    )

    collected_map = {}
    source_map = {}
    matched_source_keys = set()

    allocation_filters = Q(
        invoice_item__in=items_qs,
        is_active=True,
        payment__is_active=True,
        payment__status=PaymentStatus.COMPLETED,
    )

    if not show_all:
        if start_date:
            allocation_filters &= Q(payment__payment_date__date__gte=start_date)
        if end_date:
            allocation_filters &= Q(payment__payment_date__date__lte=end_date)

    alloc_totals_qs = (
        PaymentAllocation.objects.filter(allocation_filters)
        .values(
            'invoice_item__invoice__student__pk',
            'invoice_item__category',
            'invoice_item__description',
        )
        .annotate(collected=Sum('amount'))
    )

    for row in alloc_totals_qs:
        key = (
            row['invoice_item__invoice__student__pk'],
            normalize_invoice_detail_category_value(row['invoice_item__category']),
            row['invoice_item__description'] or '',
        )
        collected_map[key] = row['collected'] or Decimal('0.00')

    alloc_sources_qs = (
        PaymentAllocation.objects.filter(allocation_filters)
        .values(
            'invoice_item__invoice__student__pk',
            'invoice_item__category',
            'invoice_item__description',
            'payment__payment_source',
        )
        .distinct()
    )

    source_choices = dict(PaymentSource.choices)
    for row in alloc_sources_qs:
        key = (
            row['invoice_item__invoice__student__pk'],
            normalize_invoice_detail_category_value(row['invoice_item__category']),
            row['invoice_item__description'] or '',
        )
        source_value = row.get('payment__payment_source')
        if source_value:
            source_label = source_choices.get(source_value, source_value)
            source_map.setdefault(key, set()).add(source_label)
        if payment_source and source_value == payment_source:
            matched_source_keys.add(key)

    rows = []
    total_billed = Decimal('0.00')
    total_paid = Decimal('0.00')
    total_balance = Decimal('0.00')

    for row in grouped:
        student_pk = row['invoice__student__pk']
        raw_category = row['category']
        normalized_category = normalize_invoice_detail_category_value(raw_category)
        description = row.get('description') or ''
        key = (student_pk, normalized_category, description)

        if payment_source and key not in matched_source_keys:
            continue

        billed = row['total_billed'] or Decimal('0.00')
        paid = collected_map.get(key, Decimal('0.00'))
        balance = billed - paid

        first = row.get('invoice__student__first_name', '')
        middle = row.get('invoice__student__middle_name', '')
        last = row.get('invoice__student__last_name', '')
        full_name = ' '.join(part for part in [first, middle, last] if part).strip()

        payment_source_display = (
            source_choices.get(payment_source, payment_source)
            if payment_source
            else (', '.join(sorted(source_map.get(key, set()))) or '—')
        )

        rows.append({
            'student__first_name': first,
            'student__middle_name': middle,
            'student__last_name': last,
            'student__full_name': full_name,
            'student__admission_number': row.get('invoice__student__admission_number', ''),
            'student__current_class__name': row.get('invoice__student__current_class__name', ''),
            'payment_source': payment_source_display,
            'raw_category': raw_category,
            'raw_description': description,
            'description': get_invoice_detail_category_display(raw_category, description),
            'total_billed': billed,
            'total_paid': paid,
            'total_balance': balance,
        })

        total_billed += billed
        total_paid += paid
        total_balance += balance

    rows.sort(
        key=lambda row: (
            row['student__full_name'].lower(),
            get_invoice_detail_sort_key(row.get('raw_category'), row.get('raw_description', '')),
        )
    )

    return {
        'rows': rows,
        'totals': {
            'total_billed': total_billed,
            'total_paid': total_paid,
            'total_balance': total_balance,
        },
        'selected_payment_source': payment_source,
    }


def get_parent_contact_display(student):
    parent = getattr(student, 'primary_parent', None)
    if not parent:
        return '—'

    name = (getattr(parent, 'full_name', '') or '').strip()
    phone = (getattr(parent, 'phone_primary', '') or '').strip()
    if name and phone:
        return f'{name} ({phone})'
    return name or phone or '—'


def build_parent_contact_map(student_ids, organization=None):
    if not student_ids:
        return {}

    student_parent_qs = StudentParent.objects.select_related('parent').order_by('-is_primary', 'id')
    students_qs = (
        Student.objects.filter(pk__in=set(student_ids))
        .prefetch_related(Prefetch('student_parents', queryset=student_parent_qs))
    )
    if organization:
        students_qs = students_qs.filter(organization=organization)

    return {student.pk: get_parent_contact_display(student) for student in students_qs}


def build_outstanding_balances_report_data(
    organization=None,
    start_date=None,
    end_date=None,
    academic_year=None,
    term=None,
    student_class=None,
    balance_filter='',
    balance_op='any',
    balance_amt=Decimal('0.00'),
    include_zero=False,
):
    invoices = (
        Invoice.objects.filter(is_active=True)
        .exclude(status=InvoiceStatus.CANCELLED)
        .select_related('student', 'term__academic_year')
    )

    if organization:
        invoices = invoices.filter(organization=organization)

    invoices = invoices.filter(student__status='active')

    if academic_year:
        invoices = invoices.filter(term__academic_year=academic_year)
        if term:
            invoices = invoices.filter(term__term=term)

    if student_class:
        invoices = invoices.filter(student__current_class__name=student_class)

    as_of_date = end_date or start_date
    if as_of_date:
        invoices = invoices.filter(Q(issue_date__isnull=True) | Q(issue_date__lte=as_of_date))

    grouped_qs = list(
        invoices.values(
            'student__pk',
            'student__admission_number',
            'student__first_name',
            'student__middle_name',
            'student__last_name',
            'student__current_class__name',
            'term__academic_year__year',
        ).annotate(
            total_billed=Sum('total_amount'),
            total_balance_bf=Sum('balance_bf'),
            total_prepayment=Sum('prepayment'),
        )
    )

    payment_allocations = PaymentAllocation.objects.filter(
        invoice_item__invoice__in=invoices,
        is_active=True,
        payment__is_active=True,
        payment__status=PaymentStatus.COMPLETED,
    )
    if as_of_date:
        payment_allocations = payment_allocations.filter(payment__payment_date__date__lte=as_of_date)

    paid_map = {
        (
            row['invoice_item__invoice__student__pk'],
            row['invoice_item__invoice__term__academic_year__year'],
        ): row['total_paid'] or Decimal('0.00')
        for row in payment_allocations.values(
            'invoice_item__invoice__student__pk',
            'invoice_item__invoice__term__academic_year__year',
        ).annotate(total_paid=Sum('amount'))
    }

    parent_contact_map = build_parent_contact_map(
        student_ids=[row['student__pk'] for row in grouped_qs],
        organization=organization,
    )

    balance_filter_spec = BALANCE_PRESETS.get(balance_filter) if balance_filter else None
    balance_filter_label = balance_filter_spec[2] if balance_filter_spec else ''

    rows = []
    for row in grouped_qs:
        key = (row['student__pk'], row['term__academic_year__year'])
        total_billed = row.get('total_billed') or Decimal('0.00')
        total_balance_bf = row.get('total_balance_bf') or Decimal('0.00')
        total_prepayment = row.get('total_prepayment') or Decimal('0.00')
        total_paid = paid_map.get(key, Decimal('0.00'))
        total_balance = (total_balance_bf + total_billed) - total_prepayment - total_paid

        row_data = {
            **row,
            'parent_contact': parent_contact_map.get(row['student__pk'], '—'),
            'total_billed': total_billed,
            'total_paid': total_paid,
            'total_balance_bf': total_balance_bf,
            'total_prepayment': total_prepayment,
            'total_balance': total_balance,
        }

        if balance_filter_spec:
            if balance_filter_spec[0] == 'range':
                _, min_amt, max_amt, _ = balance_filter_spec
                if not (total_balance >= min_amt and total_balance < max_amt):
                    continue
            else:
                op, amt, _ = balance_filter_spec
                if op == '=' and not total_balance == amt:
                    continue
                if op == '>' and not total_balance > amt:
                    continue
                if op == '<' and not total_balance < amt:
                    continue
                if op == '>=' and not total_balance >= amt:
                    continue
                if op == '<=' and not total_balance <= amt:
                    continue
        elif balance_op and balance_op != 'any':
            if balance_op == '=' and not total_balance == balance_amt:
                continue
            if balance_op == '>' and not total_balance > balance_amt:
                continue
            if balance_op == '<' and not total_balance < balance_amt:
                continue
            if balance_op == '>=' and not total_balance >= balance_amt:
                continue
            if balance_op == '<=' and not total_balance <= balance_amt:
                continue

        if not include_zero and total_balance == Decimal('0.00'):
            continue

        rows.append(row_data)

    rows.sort(
        key=lambda row: (
            -(row.get('total_balance') or Decimal('0.00')),
            (row.get('student__first_name') or '').lower(),
            (row.get('student__last_name') or '').lower(),
        )
    )

    totals = {
        'total_billed': sum((row['total_billed'] or Decimal('0.00')) for row in rows),
        'total_paid': sum((row['total_paid'] or Decimal('0.00')) for row in rows),
        'total_balance': sum((row['total_balance'] or Decimal('0.00')) for row in rows),
        'total_balance_bf': sum((row['total_balance_bf'] or Decimal('0.00')) for row in rows),
        'total_prepayment': sum((row['total_prepayment'] or Decimal('0.00')) for row in rows),
    }

    return {
        'rows': rows,
        'totals': totals,
        'filters': {
            'start_date': start_date,
            'end_date': end_date,
            'as_of_date': as_of_date,
            'academic_year': academic_year,
            'term': term,
            'student_class': student_class,
            'balance_op': balance_op,
            'balance_amt': balance_amt,
            'balance_filter_label': balance_filter_label,
        },
    }
