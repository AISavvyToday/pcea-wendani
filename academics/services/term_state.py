"""Organization-scoped term activation and transition helpers."""

from datetime import date

from django.db import transaction
from django.db.models import Q

from academics.models import AcademicYear, Term, TermTransitionLog
from core.models import TermChoices


PCEA_WENDANI_CODE = "PCEA_WENDANI"
TERM_2_2026_FALLBACK_START = date(2026, 5, 1)
TERM_2_2026_FALLBACK_END = date(2026, 8, 31)
TERMINAL_STUDENT_STATUSES = {"graduated", "transferred", "withdrawn", "expelled"}


def _scope_by_organization(queryset, organization):
    if organization is None:
        return queryset.filter(organization__isnull=True)
    return queryset.filter(organization=organization)


def get_current_term_for_org(organization=None):
    """Return the current term for one organization, falling back to latest org term."""

    def _ordered(queryset):
        return queryset.order_by(
            "-academic_year__year",
            "-start_date",
            "-end_date",
            "term",
            "-id",
        )

    scoped_terms = _scope_by_organization(
        Term.objects.select_related("academic_year"),
        organization,
    )
    current_term = _ordered(scoped_terms.filter(is_current=True, is_active=True)).first()
    if current_term:
        return current_term

    latest_term = _ordered(scoped_terms.filter(is_active=True)).first()
    if latest_term:
        return latest_term

    if organization is not None:
        shared_term = _ordered(
            Term.objects.select_related("academic_year").filter(
                organization__isnull=True,
                is_current=True,
                is_active=True,
            )
        ).first()
        if shared_term:
            return shared_term

    return _ordered(Term.objects.select_related("academic_year").filter(is_active=True)).first()


def resolve_term_for_org(*, organization=None, academic_year=None, term_value=None, term_id=None):
    """Resolve a selected term and ensure it belongs to the current org scope."""
    queryset = Term.objects.select_related("academic_year").filter(is_active=True)
    queryset = _scope_by_organization(queryset, organization)

    if term_id:
        return queryset.filter(pk=term_id).first()

    if academic_year and term_value:
        return queryset.filter(academic_year=academic_year, term=term_value).first()

    return None


def get_previous_term(term):
    scoped_terms = _scope_by_organization(
        Term.objects.select_related("academic_year").filter(
            is_active=True,
            start_date__lt=term.start_date,
        ).exclude(pk=term.pk),
        term.organization,
    )
    return scoped_terms.order_by("-start_date", "-end_date", "-academic_year__year").first()


def _term_finance_state_counts(term, organization):
    from core.models import InvoiceStatus
    from finance.models import Invoice

    invoices = Invoice.objects.filter(
        term=term,
        is_active=True,
    ).exclude(status=InvoiceStatus.CANCELLED)
    if organization:
        invoices = invoices.filter(
            Q(organization=organization)
            | Q(organization__isnull=True, student__organization=organization)
        )
    else:
        invoices = invoices.filter(organization__isnull=True)

    return {
        "new_term_invoices": invoices.count(),
        "new_term_opening_invoices": invoices.filter(
            Q(balance_bf__gt=0) | Q(prepayment__gt=0)
        ).count(),
    }


def ensure_pcea_wendani_term2_2026(organization, *, dry_run=False):
    """
    Ensure the PCEA Wendani 2026 academic year and Term 2 record exist.

    Existing Term 2 dates are preserved. Missing dates use the agreed fallback.
    """
    if not organization:
        raise ValueError("organization is required")

    academic_year = AcademicYear.objects.filter(
        organization=organization,
        year=2026,
    ).first()
    if not academic_year:
        if dry_run:
            academic_year = AcademicYear(
                organization=organization,
                year=2026,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                is_current=True,
            )
        else:
            academic_year = AcademicYear.objects.create(
                organization=organization,
                year=2026,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                is_current=True,
            )

    term = Term.objects.filter(
        organization=organization,
        academic_year=academic_year,
        term=TermChoices.TERM_2,
    ).first()
    if not term:
        if dry_run:
            term = Term(
                organization=organization,
                academic_year=academic_year,
                term=TermChoices.TERM_2,
                start_date=TERM_2_2026_FALLBACK_START,
                end_date=TERM_2_2026_FALLBACK_END,
                is_current=True,
            )
        else:
            term = Term.objects.create(
                organization=organization,
                academic_year=academic_year,
                term=TermChoices.TERM_2,
                start_date=TERM_2_2026_FALLBACK_START,
                end_date=TERM_2_2026_FALLBACK_END,
                is_current=True,
            )

    return academic_year, term


@transaction.atomic
def activate_term_for_org(
    *,
    organization,
    term,
    previous_term=None,
    transition=True,
    dry_run=False,
    user=None,
    notes="",
):
    """
    Make ``term`` current for an organization and optionally carry balances once.

    Selecting a historical term activates it for viewing, but transitions only run
    when moving forward into a newer term and no executed log exists yet.
    """
    if term is None:
        raise ValueError("term is required")
    if organization is not None and term.organization_id != organization.id:
        raise ValueError(f'Term "{term}" does not belong to {organization.name}')
    if organization is None and term.organization_id is not None:
        raise ValueError(f'Term "{term}" is organization-scoped')

    current_term = get_current_term_for_org(organization)
    selected_is_already_current = bool(current_term and current_term.pk == term.pk and term.is_current)

    if previous_term is None and current_term and current_term.pk != term.pk:
        previous_term = current_term
    if previous_term is None:
        previous_term = get_previous_term(term)

    should_transition = bool(
        transition
        and previous_term
        and previous_term.pk != term.pk
        and previous_term.start_date < term.start_date
    )

    stats = {
        "activated": not selected_is_already_current,
        "transition_skipped": True,
        "transition_already_logged": False,
        "previous_term_id": str(previous_term.pk) if previous_term else None,
        "new_term_id": str(term.pk) if term.pk else None,
    }

    if should_transition:
        existing_log = TermTransitionLog.objects.filter(
            organization=organization,
            previous_term=previous_term,
            new_term=term,
            dry_run=False,
        ).first()
        if existing_log:
            stats["transition_already_logged"] = True
        else:
            finance_state = _term_finance_state_counts(term, organization)
            if finance_state["new_term_invoices"] or finance_state["new_term_opening_invoices"]:
                materialized_stats = {
                    "skipped": "new_term_already_has_finance_state",
                    **finance_state,
                }
                stats.update(materialized_stats)
                stats["transition_already_materialized"] = True
                if not dry_run:
                    TermTransitionLog.objects.create(
                        organization=organization,
                        previous_term=previous_term,
                        new_term=term,
                        executed_by=user,
                        dry_run=False,
                        stats=materialized_stats,
                        notes=notes or "Existing new-term finance state detected; carry-forward skipped.",
                    )
            else:
                from finance.services import transition_frozen_balances

                transition_stats = transition_frozen_balances(previous_term, term, dry_run=dry_run)
                stats.update(transition_stats)
                stats["transition_skipped"] = False
                if not dry_run:
                    TermTransitionLog.objects.create(
                        organization=organization,
                        previous_term=previous_term,
                        new_term=term,
                        executed_by=user,
                        dry_run=False,
                        stats=transition_stats,
                        notes=notes,
                    )

    if not dry_run:
        year_queryset = _scope_by_organization(AcademicYear.objects.all(), organization)
        year_queryset.filter(is_current=True).exclude(pk=term.academic_year_id).update(is_current=False)
        if not term.academic_year.is_current:
            term.academic_year.is_current = True
            term.academic_year.save(update_fields=["is_current", "updated_at"])

        term_queryset = _scope_by_organization(Term.objects.all(), organization)
        term_queryset.filter(is_current=True).exclude(pk=term.pk).update(is_current=False)
        if not term.is_current:
            term.is_current = True
            term.save(update_fields=["is_current", "updated_at"])

    return stats


def activate_selected_term_from_request(request, *, academic_year=None, term_value=None, term_id=None):
    """Resolve and activate a selected term from a GET/form request."""
    organization = getattr(request, "organization", None)
    term = resolve_term_for_org(
        organization=organization,
        academic_year=academic_year,
        term_value=term_value,
        term_id=term_id,
    )
    if term:
        activate_term_for_org(
            organization=organization,
            term=term,
            transition=True,
            user=getattr(request, "user", None),
            notes="Activated by term-filtered view.",
        )
    return term


def find_organization_for_pcea():
    from core.models import Organization

    return Organization.objects.filter(
        Q(code__iexact=PCEA_WENDANI_CODE)
        | Q(name__iexact="PCEA Wendani Academy")
        | Q(name__icontains="Wendani")
    ).first()


def _as_date(value):
    if value is None:
        return None
    return value.date() if hasattr(value, "date") else value


def student_belongs_to_term(student, term):
    """Return whether a student's current snapshot belongs in ``term``."""
    admission_date = _as_date(getattr(student, "admission_date", None))
    if admission_date and admission_date > term.end_date:
        return False, "admitted_after_term"

    status = getattr(student, "status", None)
    status_date = _as_date(getattr(student, "status_date", None))
    if status in TERMINAL_STUDENT_STATUSES and status_date and status_date < term.start_date:
        return False, "terminal_before_term"

    return True, ""


def sync_student_term_state(student, *, term=None, organization=None, dry_run=False):
    """Create/update the current term-scoped state for one student."""
    from students.models import StudentTermState

    organization = organization or getattr(student, "organization", None)
    term = term or get_current_term_for_org(organization)
    if not term:
        return {"skipped": "no_term"}

    belongs_to_term, reason = student_belongs_to_term(student, term)
    existing = StudentTermState.objects.filter(
        student=student,
        term=term,
        organization=organization,
    )

    if not belongs_to_term:
        if dry_run:
            return {"skipped": reason, "would_deactivate": existing.filter(is_active=True).count()}
        deactivated = existing.filter(is_active=True).update(is_active=False)
        return {"skipped": reason, "deactivated": deactivated}

    defaults = StudentTermState.defaults_from_student(student)
    defaults["organization"] = organization
    defaults["is_active"] = True

    if dry_run:
        return {
            "created": not existing.exists(),
            "updated": existing.exists(),
        }

    _, created = StudentTermState.objects.update_or_create(
        organization=organization,
        student=student,
        term=term,
        defaults=defaults,
    )
    return {"created": created, "updated": not created}


def backfill_student_term_states(term, *, organization=None, dry_run=False):
    """Create/update term-scoped student state snapshots from current student data."""
    from students.models import Student, StudentTermState

    organization = organization or term.organization
    students = Student.objects.filter(is_active=True)
    if organization:
        students = students.filter(organization=organization)
    else:
        students = students.filter(organization__isnull=True)

    stats = {
        "students": students.count(),
        "created": 0,
        "updated": 0,
        "deactivated": 0,
        "skipped_terminal_before_term": 0,
        "skipped_admitted_after_term": 0,
    }
    for student in students.select_related("current_class", "transport_route"):
        belongs_to_term, reason = student_belongs_to_term(student, term)
        if not belongs_to_term:
            if reason == "terminal_before_term":
                stats["skipped_terminal_before_term"] += 1
            elif reason == "admitted_after_term":
                stats["skipped_admitted_after_term"] += 1
            existing = StudentTermState.objects.filter(
                student=student,
                term=term,
                organization=organization,
                is_active=True,
            )
            stats["deactivated"] += existing.count()
            if not dry_run:
                existing.update(is_active=False)
            continue

        defaults = StudentTermState.defaults_from_student(student)
        defaults["organization"] = organization
        defaults["is_active"] = True
        transport_item = student.invoices.filter(
            term=term,
            items__category="transport",
            items__is_active=True,
        ).values(
            "items__transport_route",
            "items__transport_trip_type",
        ).first()
        if transport_item and transport_item.get("items__transport_route"):
            defaults["uses_school_transport"] = True
            defaults["transport_route_id"] = transport_item["items__transport_route"]
            defaults["transport_trip_type"] = transport_item.get("items__transport_trip_type") or "full"
        if dry_run:
            if StudentTermState.objects.filter(student=student, term=term, organization=organization).exists():
                stats["updated"] += 1
            else:
                stats["created"] += 1
            continue

        _, created = StudentTermState.objects.update_or_create(
            organization=organization,
            student=student,
            term=term,
            defaults=defaults,
        )
        if created:
            stats["created"] += 1
        else:
            stats["updated"] += 1

    return stats


def copy_missing_transport_fees(previous_term, new_term, *, dry_run=False):
    """Copy active route fees into the new term where the route has no fee yet."""
    from transport.models import TransportFee

    organization = new_term.organization or previous_term.organization
    source_fees = TransportFee.objects.filter(
        academic_year=previous_term.academic_year,
        term=previous_term.term,
        is_active=True,
    )
    if organization:
        source_fees = source_fees.filter(organization=organization)
    else:
        source_fees = source_fees.filter(organization__isnull=True)

    stats = {"source": source_fees.count(), "created": 0, "skipped": 0}
    for fee in source_fees.select_related("route"):
        exists = TransportFee.objects.filter(
            route=fee.route,
            academic_year=new_term.academic_year,
            term=new_term.term,
            is_active=True,
        )
        if organization:
            exists = exists.filter(organization=organization)
        else:
            exists = exists.filter(organization__isnull=True)

        if exists.exists():
            stats["skipped"] += 1
            continue

        stats["created"] += 1
        if not dry_run:
            TransportFee.objects.create(
                organization=organization,
                route=fee.route,
                academic_year=new_term.academic_year,
                term=new_term.term,
                amount=fee.amount,
                half_amount=fee.half_amount,
            )

    return stats


def hydrate_invoice_transport_metadata(term, *, organization=None, dry_run=False):
    """Populate missing route/trip metadata on transport invoice items for a term."""
    from decimal import Decimal

    from finance.models import InvoiceItem
    from transport.models import TransportFee

    organization = organization or term.organization
    items = InvoiceItem.objects.filter(
        invoice__term=term,
        category="transport",
        is_active=True,
    ).select_related("invoice__student", "transport_route")
    if organization:
        items = items.filter(
            Q(invoice__organization=organization)
            | Q(invoice__organization__isnull=True, invoice__student__organization=organization)
        )

    stats = {"items": items.count(), "updated": 0, "missing_fee": 0, "missing_route": 0}
    for item in items:
        student = item.invoice.student
        state = student.term_states.filter(term=term, is_active=True).first()
        route = item.transport_route or getattr(state, "transport_route", None) or student.transport_route
        trip_type = item.transport_trip_type or getattr(state, "transport_trip_type", None) or "full"

        if not route:
            stats["missing_route"] += 1
            continue

        fee_qs = TransportFee.objects.filter(
            route=route,
            academic_year=term.academic_year,
            term=term.term,
            is_active=True,
        )
        if organization:
            fee_qs = fee_qs.filter(organization=organization)
        fee = fee_qs.first()

        amount = item.amount or Decimal("0.00")
        if fee:
            amount = fee.get_amount_for_trip(trip_type)
        else:
            stats["missing_fee"] += 1

        changed = (
            item.transport_route_id != route.id
            or item.transport_trip_type != trip_type
            or item.amount != amount
        )
        if changed:
            stats["updated"] += 1
            if not dry_run:
                item.transport_route = route
                item.transport_trip_type = trip_type
                item.amount = amount
                trip_display = "Half Trip" if trip_type == "half" else "Full Trip"
                item.description = f"Transport ({route.name} - {trip_display})"
                item.save(update_fields=[
                    "transport_route",
                    "transport_trip_type",
                    "amount",
                    "description",
                    "net_amount",
                    "updated_at",
                ])

    return stats


def recalculate_term_invoices(term, *, organization=None, dry_run=False):
    """Re-save active invoices so balance/status/student outstanding are consistent."""
    from core.models import InvoiceStatus
    from finance.models import Invoice

    organization = organization or term.organization
    invoices = Invoice.objects.filter(
        term=term,
        is_active=True,
    ).exclude(status=InvoiceStatus.CANCELLED).select_related("student")
    if organization:
        invoices = invoices.filter(
            Q(organization=organization)
            | Q(organization__isnull=True, student__organization=organization)
        )
    else:
        invoices = invoices.filter(organization__isnull=True)

    stats = {"invoices": invoices.count(), "updated": 0, "status_changed": 0, "balance_changed": 0}
    for invoice in invoices:
        old_status = invoice.status
        old_balance = invoice.balance
        if dry_run:
            invoice._recalculate_balance()
            invoice._recalculate_status()
        else:
            invoice.save()
            invoice.refresh_from_db(fields=["status", "balance"])

        if invoice.status != old_status:
            stats["status_changed"] += 1
        if invoice.balance != old_balance:
            stats["balance_changed"] += 1
        if invoice.status != old_status or invoice.balance != old_balance:
            stats["updated"] += 1

    return stats
