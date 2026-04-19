from decimal import Decimal

from django.db.models import Q, Sum

from finance.models import InvoiceItem
from other_income.models import OtherIncomeInvoice
from payments.models import PaymentAllocation

ZERO = Decimal("0.00")


_BUCKET_CONFIG = {
    "fees": {
        "label": "Fees",
        "categories": ("tuition", "meals", "activity", "examination"),
    },
    "transport": {
        "label": "Transport",
        "categories": ("transport",),
    },
    "admission": {
        "label": "Admission Fee",
        "categories": ("admission",),
    },
    "educational_activities": {
        "label": "Educational Activities",
        "categories": ("other",),
    },
}


def _safe_decimal(value):
    return value if value is not None else ZERO


def _organization_invoice_filter(organization):
    if not organization:
        return Q()
    return (
        Q(invoice__organization=organization)
        | Q(invoice__organization__isnull=True, invoice__student__organization=organization)
    )


def _organization_allocation_filter(organization):
    if not organization:
        return Q()
    return (
        Q(invoice_item__invoice__organization=organization)
        | Q(
            invoice_item__invoice__organization__isnull=True,
            invoice_item__invoice__student__organization=organization,
        )
    )


def _organization_other_income_filter(organization):
    if not organization:
        return Q()
    return Q(organization=organization) | Q(organization__isnull=True)


def build_term_kpis(term, organization=None):
    """Build canonical KPI payload for finance dashboard and summary APIs."""

    invoice_item_qs = (
        InvoiceItem.objects.filter(
            is_active=True,
            invoice__is_active=True,
            invoice__student__is_active=True,
            invoice__student__status="active",
        )
        .exclude(invoice__status="cancelled")
        .filter(_organization_invoice_filter(organization))
    )
    if term:
        invoice_item_qs = invoice_item_qs.filter(invoice__term=term)

    billed_by_category = {
        row["category"]: _safe_decimal(row["total"])
        for row in invoice_item_qs.values("category").annotate(total=Sum("net_amount"))
    }

    allocation_qs = (
        PaymentAllocation.objects.filter(
            is_active=True,
            payment__is_active=True,
            payment__status="completed",
            invoice_item__is_active=True,
            invoice_item__invoice__student__is_active=True,
        )
        .exclude(invoice_item__invoice__status="cancelled")
        .filter(_organization_allocation_filter(organization))
    )
    if term:
        allocation_qs = allocation_qs.filter(invoice_item__invoice__term=term)

    collected_by_category = {
        row["invoice_item__category"]: _safe_decimal(row["total"])
        for row in allocation_qs.values("invoice_item__category").annotate(total=Sum("amount"))
    }

    school_fee_buckets = {}
    for bucket_key, config in _BUCKET_CONFIG.items():
        categories = list(config["categories"])

        billed = sum((billed_by_category.get(category, ZERO) for category in categories), ZERO)
        collected = sum((collected_by_category.get(category, ZERO) for category in categories), ZERO)
        school_fee_buckets[bucket_key] = {
            "label": config["label"],
            "billed": billed,
            "collected": collected,
            "outstanding": billed - collected,
            "raw": {
                "categories": {
                    category: {
                        "billed": billed_by_category.get(category, ZERO),
                        "collected": collected_by_category.get(category, ZERO),
                        "outstanding": billed_by_category.get(category, ZERO)
                        - collected_by_category.get(category, ZERO),
                    }
                    for category in categories
                }
            },
        }

    other_income_qs = (
        OtherIncomeInvoice.objects.filter(is_active=True)
        .exclude(status="cancelled")
        .filter(_organization_other_income_filter(organization))
    )
    if term:
        other_income_qs = other_income_qs.filter(issue_date__gte=term.start_date, issue_date__lte=term.end_date)

    other_income_billed = _safe_decimal(other_income_qs.aggregate(total=Sum("total_amount"))["total"])
    other_income_collected = _safe_decimal(other_income_qs.aggregate(total=Sum("amount_paid"))["total"])
    other_income_outstanding = other_income_billed - other_income_collected

    buckets = {
        **school_fee_buckets,
        "other_income": {
            "label": "Other Income",
            "billed": other_income_billed,
            "collected": other_income_collected,
            "outstanding": other_income_outstanding,
            "raw": {},
        },
    }

    total_billed = sum((bucket["billed"] for bucket in buckets.values()), ZERO)
    total_collected = sum((bucket["collected"] for bucket in buckets.values()), ZERO)
    total_outstanding = sum((bucket["outstanding"] for bucket in buckets.values()), ZERO)

    return {
        "term_id": str(term.id) if term else None,
        "organization_id": str(organization.id) if organization else None,
        "buckets": buckets,
        "totals": {
            "billed": total_billed,
            "collected": total_collected,
            "outstanding": total_outstanding,
        },
        "ui": {
            "cards": {
                "total_billed": total_billed,
                "total_collected": total_collected,
                "total_outstanding": total_outstanding,
            }
        },
        "raw": {
            "school_fees": {
                "billed_by_category": billed_by_category,
                "collected_by_category": collected_by_category,
            }
        },
    }
