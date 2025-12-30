# reports/templatetags/custom_filters.py
from django import template

register = template.Library()

@register.filter
def divide(value, arg):
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError):
        return 0

@register.filter
def multiply(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def split_lines(value):
    """Split a string by newlines and return a list of non-empty lines."""
    if not value:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]