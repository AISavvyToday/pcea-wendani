"""
Django signals for the academics app.

Handles automatic term transition when a new term is marked as current.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

from academics.models import Term

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Term)
def handle_term_change(sender, instance, created, **kwargs):
    """
    When a term is marked as current, recalculate frozen balances
    for all active students based on previous term outcomes.
    
    This ensures that when switching to a new term:
    - balance_bf_original reflects outstanding balance from previous term
    - prepayment_original reflects overpayment from previous term
    - credit_balance is set to match for invoice generation
    """
    # Only trigger when a term is set as current
    if not instance.is_current:
        return
    
    # Skip if this is a new term being created (will be handled when it's set current later)
    # Actually, we should process even on create if is_current is True
    
    logger.info(f"Term {instance} marked as current. Initiating balance transition...")
    
    # Find the previous term
    # First try same academic year
    previous_term = Term.objects.filter(
        organization=instance.organization,
        academic_year=instance.academic_year,
        start_date__lt=instance.start_date
    ).order_by('-start_date').first()
    
    # If no previous term in same year, try previous year's last term
    if not previous_term:
        previous_term = Term.objects.filter(
            organization=instance.organization,
            start_date__lt=instance.start_date
        ).exclude(pk=instance.pk).order_by('-start_date').first()
    
    if not previous_term:
        logger.info(
            f"No previous term found for {instance}. "
            f"This appears to be the first term. Skipping balance transition."
        )
        return
    
    logger.info(f"Found previous term: {previous_term}")
    
    # Import here to avoid circular imports
    from finance.services import transition_frozen_balances
    
    try:
        stats = transition_frozen_balances(previous_term, instance)
        logger.info(
            f"Term transition complete: {stats['updated']} students updated, "
            f"{stats['errors']} errors"
        )
    except Exception as e:
        logger.error(f"Error during term transition: {e}", exc_info=True)

