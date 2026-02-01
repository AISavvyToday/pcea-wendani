# communications/utils.py
"""
Utility functions for communications module.
"""

import re


def normalize_phone_number(phone):
    """
    Normalize Kenyan phone number to format: +254XXXXXXXXX
    
    Handles formats:
    - +254XXXXXXXXX (already normalized)
    - 254XXXXXXXXX
    - 0XXXXXXXXX
    - XXXXXXXXX (assumes 254 prefix needed)
    """
    if not phone:
        return None
    
    # Remove all spaces, dashes, and other non-digit characters except +
    phone = re.sub(r'[^\d+]', '', phone)
    
    # Remove leading + if present for processing
    has_plus = phone.startswith('+')
    if has_plus:
        phone = phone[1:]
    
    # Handle different formats
    if phone.startswith('254'):
        # Already has country code
        normalized = '+254' + phone[3:]
    elif phone.startswith('0'):
        # Remove leading 0 and add country code
        normalized = '+254' + phone[1:]
    elif len(phone) == 9:
        # 9 digits, add country code
        normalized = '+254' + phone
    else:
        # Assume it's already in correct format or return as is
        normalized = '+' + phone if not has_plus else phone
    
    # Validate: should be +254 followed by 9 digits
    if re.match(r'^\+254\d{9}$', normalized):
        return normalized
    
    return None


def parse_phone_numbers(phone_input):
    """
    Parse comma-separated phone numbers and normalize them.
    
    Args:
        phone_input: String with comma-separated phone numbers
        
    Returns:
        List of normalized phone numbers (invalid ones are filtered out)
    """
    if not phone_input:
        return []
    
    phones = [p.strip() for p in phone_input.split(',')]
    normalized = []
    
    for phone in phones:
        norm_phone = normalize_phone_number(phone)
        if norm_phone:
            normalized.append(norm_phone)
    
    return normalized

