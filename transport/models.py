# transport/models.py
from django.db import models
from decimal import Decimal
from django.core.validators import MinValueValidator
from core.models import BaseModel, TermChoices


class TransportRoute(BaseModel):
    """Transport route with route-specific fees per academic year/term."""
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='transport_routes',
        null=True,
        blank=True,
        help_text="Organization this transport route belongs to"
    )
    
    name = models.CharField(max_length=100, default="Route")
    description = models.TextField(blank=True)
    pickup_points = models.TextField(blank=True, help_text="List of pickup points, one per line")
    dropoff_points = models.TextField(blank=True, help_text="List of drop-off points, one per line")

    class Meta:
        db_table = 'transport_routes'
        ordering = ['name']

    def __str__(self):
        return f"{self.name}"


class TransportFee(BaseModel):
    """
    Transport fee amount for a specific route, academic year, and term.

    - `amount` is the full-trip amount (default).
    - `half_amount` is optional and stores explicitly the half-trip amount if different.
    If `half_amount` is empty, half-trip will be computed as half of `amount`.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='transport_fees',
        null=True,
        blank=True,
        help_text="Organization this transport fee belongs to"
    )
    
    route = models.ForeignKey(TransportRoute, on_delete=models.CASCADE, related_name='fees')
    academic_year = models.ForeignKey('academics.AcademicYear', on_delete=models.CASCADE, related_name='transport_fees')
    term = models.CharField(max_length=10, choices=TermChoices.choices)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Full-trip transport fee for this route, term, and academic year"
    )
    half_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Optional explicit half-trip fee; if empty half-trip is computed as amount/2"
    )

    class Meta:
        db_table = 'transport_fees'
        unique_together = ['route', 'academic_year', 'term']
        ordering = ['route__name', 'academic_year__year', 'term']

    def __str__(self):
        return f"{self.route.name} - {self.academic_year.year} {self.term}: KES {self.amount}"

    def get_amount_for_trip(self, trip_type: str):
        """
        trip_type: 'full' or 'half'
        """
        if trip_type == 'half':
            if self.half_amount is not None:
                return self.half_amount
            # fallback: half the full amount
            return (self.amount / 2) if self.amount is not None else Decimal('0.00')
        return self.amount or Decimal('0.00')

