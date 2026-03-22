from dataclasses import dataclass
from typing import Optional

from django.db.models import Count, Prefetch, Q

from .models import OtherIncomeInvoice, OtherIncomeItem, OtherIncomePayment


@dataclass(frozen=True)
class OtherIncomeReportFilters:
    search: str = ''
    status: str = ''
    issue_date_from: Optional[object] = None
    issue_date_to: Optional[object] = None
    due_date_from: Optional[object] = None
    due_date_to: Optional[object] = None
    payment_date_from: Optional[object] = None
    payment_date_to: Optional[object] = None
    payment_method: str = ''


def other_income_report_queryset(organization=None):
    """
    Base queryset for all future other-income reports.

    The upcoming HTML, Excel, and PDF outputs should all use this same queryset
    and filter pipeline so the business-approved template is applied against one
    consistent data source.
    """
    queryset = OtherIncomeInvoice.objects.filter(is_active=True).select_related(
        'organization',
        'generated_by',
    ).prefetch_related(
        Prefetch(
            'items',
            queryset=OtherIncomeItem.objects.filter(is_active=True).order_by('created_at', 'description'),
        ),
        Prefetch(
            'payments',
            queryset=OtherIncomePayment.objects.filter(is_active=True).order_by('payment_date', 'created_at'),
        ),
    )

    if organization:
        queryset = queryset.filter(Q(organization=organization) | Q(organization__isnull=True))

    return queryset.order_by('-issue_date', '-created_at')


def apply_other_income_report_filters(queryset, filters: OtherIncomeReportFilters):
    """Apply only currently-supported, confirmed data filters."""
    if filters.search:
        queryset = queryset.filter(
            Q(invoice_number__icontains=filters.search) |
            Q(client_name__icontains=filters.search) |
            Q(client_contact__icontains=filters.search) |
            Q(description__icontains=filters.search) |
            Q(payments__payment_reference__icontains=filters.search) |
            Q(payments__receipt_number__icontains=filters.search) |
            Q(payments__transaction_reference__icontains=filters.search) |
            Q(payments__payer_name__icontains=filters.search)
        )

    if filters.status:
        queryset = queryset.filter(status=filters.status)
    if filters.issue_date_from:
        queryset = queryset.filter(issue_date__gte=filters.issue_date_from)
    if filters.issue_date_to:
        queryset = queryset.filter(issue_date__lte=filters.issue_date_to)
    if filters.due_date_from:
        queryset = queryset.filter(due_date__gte=filters.due_date_from)
    if filters.due_date_to:
        queryset = queryset.filter(due_date__lte=filters.due_date_to)
    if filters.payment_date_from:
        queryset = queryset.filter(payments__payment_date__date__gte=filters.payment_date_from)
    if filters.payment_date_to:
        queryset = queryset.filter(payments__payment_date__date__lte=filters.payment_date_to)
    if filters.payment_method:
        queryset = queryset.filter(payments__payment_method=filters.payment_method)

    return queryset.distinct()


def build_other_income_report_dataset(*, organization=None, filters=None, limit=None):
    """
    Build the reusable dataset that future report templates will render.

    Row shape intentionally contains the inventory requested by the business
    team before final template delivery:
    - invoice header
    - line items
    - payment history
    - status / balance / issue date / due date
    - payment + invoice dimensions for future grouping/totals decisions
    """
    filters = filters or OtherIncomeReportFilters()
    queryset = apply_other_income_report_filters(other_income_report_queryset(organization), filters)
    if limit:
        queryset = queryset[:limit]

    rows = []
    for invoice in queryset:
        items = list(invoice.items.all())
        payments = list(invoice.payments.all())
        payment_methods = sorted({payment.payment_method for payment in payments if payment.payment_method})

        rows.append({
            'invoice': {
                'id': str(invoice.pk),
                'invoice_number': invoice.invoice_number,
                'client_name': invoice.client_name,
                'client_contact': invoice.client_contact,
                'description': invoice.description,
                'status': invoice.status,
                'subtotal': invoice.subtotal,
                'total_amount': invoice.total_amount,
                'amount_paid': invoice.amount_paid,
                'balance': invoice.balance,
                'issue_date': invoice.issue_date,
                'due_date': invoice.due_date,
                'organization': getattr(invoice.organization, 'name', ''),
            },
            'line_items': [
                {
                    'description': item.description,
                    'amount': item.amount,
                }
                for item in items
            ],
            'payment_history': [
                {
                    'payment_reference': payment.payment_reference,
                    'receipt_number': payment.receipt_number,
                    'amount': payment.amount,
                    'payment_method': payment.payment_method,
                    'payment_date': payment.payment_date,
                    'payer_name': payment.payer_name,
                    'payer_contact': payment.payer_contact,
                    'transaction_reference': payment.transaction_reference,
                }
                for payment in payments
            ],
            'dimensions': {
                'status': invoice.status,
                'payment_methods': payment_methods,
                'has_payments': bool(payments),
                'item_count': len(items),
                'payment_count': len(payments),
            },
        })

    return rows


def build_other_income_report_inventory(*, organization=None, filters=None):
    """
    Summary metadata for the staging page so the team can verify what is already
    reusable before the final layout is supplied.
    """
    filters = filters or OtherIncomeReportFilters()
    queryset = apply_other_income_report_filters(other_income_report_queryset(organization), filters)
    summary = queryset.aggregate(
        invoice_count=Count('id', distinct=True),
        line_item_count=Count('items__id', distinct=True),
        payment_count=Count('payments__id', distinct=True),
    )

    statuses = [
        status for status in queryset.exclude(status='').values_list('status', flat=True).distinct().order_by('status')
    ]
    payment_methods = [
        method for method in
        queryset.exclude(payments__payment_method='').values_list('payments__payment_method', flat=True).distinct().order_by('payments__payment_method')
        if method
    ]

    return {
        'counts': summary,
        'available_columns': [
            'invoice_number',
            'client_name',
            'client_contact',
            'description',
            'status',
            'subtotal',
            'total_amount',
            'amount_paid',
            'balance',
            'issue_date',
            'due_date',
            'line_items.description',
            'line_items.amount',
            'payment_history.payment_reference',
            'payment_history.receipt_number',
            'payment_history.amount',
            'payment_history.payment_method',
            'payment_history.payment_date',
            'payment_history.transaction_reference',
        ],
        'available_grouping_dimensions': [
            'invoice status',
            'issue date',
            'due date',
            'payment date',
            'payment method',
            'client',
            'invoice number',
        ],
        'statuses': statuses,
        'payment_methods': payment_methods,
    }
