from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.conf import settings

from academics.models import AcademicYear, Term

from .models import Student, StudentTermState


STATUS_VALUES = [choice[0] for choice in Student.STATUS_CHOICES]
SPECIAL_STATUS_NEW = 'new'
DEFAULT_NEW_STUDENT_STATUSES = ('active', 'inactive')
TERM_EVENT_STATUSES = ('graduated', 'transferred')


def get_current_term(organization=None):
    from academics.services.term_state import get_current_term_for_org

    return get_current_term_for_org(organization)


def get_student_base_queryset(organization=None):
    queryset = Student.objects.all()
    if any(getattr(field, 'name', None) == 'is_active' for field in Student._meta.get_fields()):
        queryset = queryset.filter(is_active=True)
    if organization is not None:
        queryset = queryset.filter(organization=organization)
    return queryset


def get_new_students_q(term=None, *, organization=None, fallback_days=None):
    status_values = tuple(
        getattr(settings, 'NEW_STUDENT_STATUSES', DEFAULT_NEW_STUDENT_STATUSES)
    ) or DEFAULT_NEW_STUDENT_STATUSES

    if term:
        return Q(
            status__in=status_values,
            admission_date__gte=term.start_date,
            admission_date__lte=term.end_date,
        )

    if organization is not None:
        current_academic_year = AcademicYear.objects.filter(
            organization=organization,
            is_current=True,
        ).first()
        if current_academic_year:
            return Q(
                status__in=status_values,
                admission_date__gte=current_academic_year.start_date,
                admission_date__lte=current_academic_year.end_date,
            )

    fallback_days = fallback_days if fallback_days is not None else getattr(
        settings, 'NEW_STUDENT_FALLBACK_DAYS', None
    )
    if fallback_days:
        cutoff = timezone.localdate() - timedelta(days=fallback_days)
        return Q(
            status__in=status_values,
            admission_date__gte=cutoff,
            admission_date__lte=timezone.localdate(),
        )

    return Q(pk__in=[])


def apply_student_filters(
    queryset,
    *,
    query=None,
    class_id=None,
    status='active',
    gender=None,
    is_boarder=None,
    stream=None,
    term=None,
    organization=None,
    new_students_fallback_days=None,
):
    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query)
            | Q(middle_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(admission_number__icontains=query)
        )

    if class_id:
        queryset = queryset.filter(current_class_id=class_id)

    if status:
        if status == SPECIAL_STATUS_NEW:
            queryset = queryset.filter(
                get_new_students_q(
                    term=term,
                    organization=organization,
                    fallback_days=new_students_fallback_days,
                )
            )
        elif term and StudentTermState.objects.filter(term=term, is_active=True).exists():
            queryset = queryset.filter(
                term_states__term=term,
                term_states__status=status,
                term_states__is_active=True,
            ).distinct()
        else:
            queryset = queryset.filter(status=status)

    if gender:
        queryset = queryset.filter(gender=gender)

    if is_boarder == 'yes':
        queryset = queryset.filter(is_boarder=True)
    elif is_boarder == 'no':
        queryset = queryset.filter(is_boarder=False)

    if stream:
        queryset = queryset.filter(current_class__stream=stream)

    return queryset


def get_student_status_counters(
    queryset,
    *,
    term=None,
    organization=None,
    new_students_fallback_days=None,
):
    student_ids = queryset.values('pk')
    term_states = StudentTermState.objects.filter(
        term=term,
        student_id__in=student_ids,
        is_active=True,
    ) if term else StudentTermState.objects.none()
    if organization is not None:
        term_states = term_states.filter(organization=organization)

    if term and term_states.exists():
        counts = {}
        for status in STATUS_VALUES:
            status_qs = term_states.filter(status=status)
            if status in TERM_EVENT_STATUSES:
                status_qs = status_qs.filter(
                    Q(status_date__isnull=True)
                    | Q(
                        status_date__date__gte=term.start_date,
                        status_date__date__lte=term.end_date,
                    )
                )
            counts[status] = status_qs.count()
    else:
        counts = {}
        for status in STATUS_VALUES:
            status_qs = queryset.filter(status=status)
            if term and status in TERM_EVENT_STATUSES:
                status_qs = status_qs.filter(
                    status_date__date__gte=term.start_date,
                    status_date__date__lte=term.end_date,
                )
            counts[status] = status_qs.count()

    counts['new'] = queryset.filter(
        get_new_students_q(
            term=term,
            organization=organization,
            fallback_days=new_students_fallback_days,
        )
    ).count()
    return {key: counts.get(key, 0) for key in [*STATUS_VALUES, 'new']}
