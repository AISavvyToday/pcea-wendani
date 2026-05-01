"""Django signals for the academics app."""
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

from academics.models import Term

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Term)
def handle_term_change(sender, instance, created, **kwargs):
    """
    Term activation is intentionally explicit.

    Balance carry-forward is handled by academics.services.term_state so viewing
    or saving a term cannot accidentally re-run a financial transition.
    """
    if instance.is_current:
        logger.debug("Term %s saved as current; explicit activation service owns transitions.", instance)

