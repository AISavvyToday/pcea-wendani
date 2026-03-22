from django import template

register = template.Library()

@register.filter
def split(value, delimiter=','):
    """Split a string by delimiter and return list."""
    if not value:
        return []
    return [item.strip() for item in value.split(delimiter)]