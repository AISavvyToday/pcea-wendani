# finance/utils.py
"""
Finance module utility functions.
"""

from decimal import Decimal


def number_to_words(amount):
    """Convert number to words for receipts."""

    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def convert_less_than_thousand(n):
        if n == 0:
            return ''
        elif n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + ('' if n % 10 == 0 else ' ' + ones[n % 10])
        else:
            return ones[n // 100] + ' Hundred' + ('' if n % 100 == 0 else ' and ' + convert_less_than_thousand(n % 100))

    if isinstance(amount, Decimal):
        amount = float(amount)

    amount = int(amount)

    if amount == 0:
        return 'Zero'

    if amount < 0:
        return 'Negative ' + number_to_words(-amount)

    if amount < 1000:
        return convert_less_than_thousand(amount)
    elif amount < 1000000:
        return convert_less_than_thousand(amount // 1000) + ' Thousand' + \
            ('' if amount % 1000 == 0 else ' ' + convert_less_than_thousand(amount % 1000))
    elif amount < 1000000000:
        return convert_less_than_thousand(amount // 1000000) + ' Million' + \
            ('' if amount % 1000000 == 0 else ' ' + number_to_words(amount % 1000000))
    else:
        return convert_less_than_thousand(amount // 1000000000) + ' Billion' + \
            ('' if amount % 1000000000 == 0 else ' ' + number_to_words(amount % 1000000000))


def format_phone_number(phone):
    """Format phone number to international format."""
    if not phone:
        return None
    phone = ''.join(filter(str.isdigit, str(phone)))
    if phone.startswith('0'):
        phone = '254' + phone[1:]
    elif not phone.startswith('254'):
        phone = '254' + phone
    return phone