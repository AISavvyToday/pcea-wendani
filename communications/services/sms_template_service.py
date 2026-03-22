"""Utilities for safe SMS template rendering and placeholder discovery."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)


class SMSTemplateService:
    """Render SMS templates using nested dict/object context safely."""

    PLACEHOLDER_PATTERN = re.compile(r"\{\s*([a-zA-Z0-9_.]+)\s*\}")
    UNKNOWN_PLACEHOLDER_MARKER = "[missing:{placeholder}]"
    MONEY_HINTS = {
        "amount",
        "balance",
        "outstanding_balance",
        "current_term_fee_amount",
        "balance_bf",
        "prepayment",
        "total_due",
        "remaining_balance",
    }
    DATE_HINTS = {
        "due_date",
        "payment_deadline",
        "payment_date",
        "issue_date",
        "date",
    }
    PLACEHOLDER_ALIASES = {
        "student.name": "student.full_name",
        "student_name": "student.full_name",
        "student.full_name": "student.full_name",
        "admission_number": "student.admission_number",
        "student.admission_number": "student.admission_number",
        "student.class": "student.grade_class",
        "student.grade": "student.grade_class",
        "student.grade_class": "student.grade_class",
        "grade": "student.grade_class",
        "student.outstanding_balance": "student.outstanding_balance",
        "outstanding_balance": "student.outstanding_balance",
        "invoice.amount": "invoice.current_term_fee_amount",
        "invoice.current_term_fee_amount": "invoice.current_term_fee_amount",
        "current_term_fee_amount": "invoice.current_term_fee_amount",
        "invoice.balance_bf": "invoice.balance_bf",
        "balance_bf": "invoice.balance_bf",
        "invoice.prepayment": "invoice.prepayment",
        "prepayment": "invoice.prepayment",
        "invoice.total_due": "invoice.total_due",
        "total_due": "invoice.total_due",
        "invoice.due_date": "invoice.due_date",
        "due_date": "invoice.due_date",
        "payment_deadline": "invoice.payment_deadline",
        "invoice.payment_deadline": "invoice.payment_deadline",
        "invoice.link": "invoice.link",
        "invoice_link": "invoice.link",
        "invoice.print_url": "invoice.print_url",
        "invoice_print_url": "invoice.print_url",
        "invoice.paybill_account_1": "invoice.paybill_account_1",
        "invoice.paybill_account_2": "invoice.paybill_account_2",
        "receipt.link": "receipt.link",
        "receipt_link": "receipt.link",
        "receipt.print_url": "receipt.print_url",
        "receipt_print_url": "receipt.print_url",
        "payment.transaction_reference": "payment.transaction_reference",
        "transaction_reference": "payment.transaction_reference",
        "payment.reference": "payment.transaction_reference",
        "payment.date": "payment.payment_date",
        "payment.payment_date": "payment.payment_date",
        "payment_date": "payment.payment_date",
        "payment.remaining_balance": "payment.remaining_balance",
        "remaining_balance": "payment.remaining_balance",
        "parent.name": "parent.full_name",
        "parent.full_name": "parent.full_name",
        "parent.first_name": "parent.first_name",
        "parent.phone": "parent.phone_primary",
        "school.name": "school.name",
    }

    @classmethod
    def replace_placeholders(cls, template: str, context: dict[str, Any] | None = None, preview: bool = False) -> str:
        """Backward-compatible wrapper that renders and returns only the message."""
        rendered = cls.render(template, context=context, preview=preview)
        return rendered["message"]

    @classmethod
    def render(cls, template: str, context: dict[str, Any] | None = None, preview: bool = False) -> dict[str, Any]:
        """Render *template* against *context* and report unresolved placeholders."""
        if not template:
            return {"message": "", "unresolved_placeholders": []}

        context = context or {}
        unresolved: list[str] = []

        def replacer(match: re.Match[str]) -> str:
            placeholder = match.group(1).strip()
            resolved_path = cls.PLACEHOLDER_ALIASES.get(placeholder, placeholder)
            value = cls._resolve_path(context, resolved_path)

            if value is None:
                unresolved.append(placeholder)
                if preview:
                    return match.group(0)
                return ""

            return cls._format_value(value, placeholder)

        message = cls.PLACEHOLDER_PATTERN.sub(replacer, template)
        if not preview:
            message = re.sub(r"\s{2,}", " ", message).strip()

        return {
            "message": message,
            "unresolved_placeholders": sorted(set(unresolved)),
        }

    @classmethod
    def _resolve_path(cls, context: dict[str, Any], path: str) -> Any:
        if path in context:
            return context[path]

        current: Any = context
        for part in path.split('.'):
            if current is None:
                return None

            if isinstance(current, dict):
                current = current.get(part)
                continue

            if hasattr(current, part):
                current = getattr(current, part)
                if callable(current):
                    try:
                        current = current()
                    except TypeError:
                        return None
                continue

            return None

        return current

    @classmethod
    def _format_value(cls, value: Any, placeholder: str) -> str:
        last_segment = placeholder.split('.')[-1]
        if isinstance(value, Decimal) or last_segment in cls.MONEY_HINTS:
            return cls._format_money(value)
        if isinstance(value, (datetime, date)) or last_segment in cls.DATE_HINTS:
            return cls._format_date(value)
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)

    @staticmethod
    def _format_money(value: Any) -> str:
        if value in (None, ""):
            return "KES 0.00"
        try:
            amount = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return str(value)
        return f"KES {amount:,.2f}"

    @staticmethod
    def _format_date(value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return value.strftime('%d %b %Y')
        return str(value)

    @classmethod
    def get_available_placeholders(cls) -> list[dict[str, str]]:
        """Return documented placeholders available to operators."""
        return [
            {"key": "{parent.name}", "description": "Parent/guardian full name"},
            {"key": "{parent.first_name}", "description": "Parent/guardian first name"},
            {"key": "{parent.phone}", "description": "Parent/guardian phone number"},
            {"key": "{student.name}", "description": "Student full name"},
            {"key": "{student.admission_number}", "description": "Student admission number"},
            {"key": "{student.class}", "description": "Student grade/class"},
            {"key": "{student.outstanding_balance}", "description": "Student outstanding balance"},
            {"key": "{invoice.current_term_fee_amount}", "description": "Current term fee amount"},
            {"key": "{invoice.balance_bf}", "description": "Balance brought forward"},
            {"key": "{invoice.prepayment}", "description": "Prepayment/credit applied"},
            {"key": "{invoice.total_due}", "description": "Total amount due"},
            {"key": "{invoice.due_date}", "description": "Invoice due date"},
            {"key": "{invoice.payment_deadline}", "description": "Payment deadline"},
            {"key": "{invoice.link}", "description": "Invoice link"},
            {"key": "{invoice.paybill_account_1}", "description": "Primary paybill account format"},
            {"key": "{invoice.paybill_account_2}", "description": "Secondary paybill account format"},
            {"key": "{receipt.link}", "description": "Receipt link"},
            {"key": "{payment.transaction_reference}", "description": "Payment transaction reference"},
            {"key": "{payment.payment_date}", "description": "Payment date"},
            {"key": "{payment.remaining_balance}", "description": "Remaining balance after payment"},
            {"key": "{school.name}", "description": "School/organization name"},
        ]
