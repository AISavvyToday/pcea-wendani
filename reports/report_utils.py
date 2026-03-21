from decimal import Decimal

from django.db.models import Sum

from core.models import FeeCategory
from finance.models import InvoiceItem


REPORT_CATEGORY_LABELS = {
    FeeCategory.TUITION: "Tuition",
    FeeCategory.MEALS: "Meals",
    FeeCategory.EXAMINATION: "Examination",
    FeeCategory.ACTIVITY: "Activity",
    FeeCategory.TRANSPORT: "Transport",
    FeeCategory.ADMISSION: "Admission",
    FeeCategory.OTHER: "Other",
    FeeCategory.BALANCE_BF: "Balance B/F",
    FeeCategory.PREPAYMENT_CREDIT: "Prepayments",
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


def get_report_category_label(category):
    if category in REPORT_CATEGORY_LABELS:
        return REPORT_CATEGORY_LABELS[category]

    fee_category_map = dict(FeeCategory.choices)
    if category in fee_category_map:
        return fee_category_map[category]

    return str(category).replace("_", " ").title()


def order_report_categories(categories):
    ordered = [category for category in REPORT_CATEGORY_SEQUENCE if category in categories]
    extras = sorted(
        [category for category in categories if category not in ordered],
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


def get_invoice_detail_category_choices():
    categories_list = [
        (category, get_report_category_label(category))
        for category in DETAIL_FILTER_CATEGORY_SEQUENCE
    ]

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

    for description in sorted(unique_descriptions, key=str.lower):
        categories_list.append((f"{FeeCategory.OTHER}:{description}", f"Other: {description}"))

    categories_list.append((FeeCategory.OTHER, get_report_category_label(FeeCategory.OTHER)))
    return categories_list


def get_invoice_detail_category_display(category, description=""):
    if category == FeeCategory.OTHER and description:
        return description
    return get_report_category_label(category)


def get_selected_category_labels(selected_categories):
    labels = []
    for category in selected_categories or []:
        if category.startswith(f"{FeeCategory.OTHER}:"):
            labels.append(f"Other: {category.split(':', 1)[1]}")
            continue
        labels.append(get_report_category_label(category))
    return labels
