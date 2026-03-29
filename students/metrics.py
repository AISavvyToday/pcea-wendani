from django.db.models import Count, Q

from academics.models import Term

from .models import Student


STATUS_VALUES = [choice[0] for choice in Student.STATUS_CHOICES]
SPECIAL_STATUS_NEW = 'new'


def get_current_term(organization=None):
    queryset = Term.objects.filter(is_current=True).select_related('academic_year')

    def _ordered(queryset_to_order):
        return queryset_to_order.order_by(
            '-academic_year__year',
            '-start_date',
            '-end_date',
            'term',
            '-id',
        )

    if organization is not None:
        org_term = _ordered(queryset.filter(organization=organization)).first()
        if org_term:
            return org_term

    return _ordered(queryset.filter(organization__isnull=True)).first()


def get_student_base_queryset(organization=None):
    queryset = Student.objects.all()
    if any(getattr(field, 'name', None) == 'is_active' for field in Student._meta.get_fields()):
        queryset = queryset.filter(is_active=True)
    if organization is not None:
        queryset = queryset.filter(organization=organization)
    return queryset


def get_new_students_q(term=None):
    if not term:
        return Q(pk__in=[])
    return Q(
        status='active',
        admission_date__gte=term.start_date,
        admission_date__lte=term.end_date,
    )


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
            queryset = queryset.filter(get_new_students_q(term=term))
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


def get_student_status_counters(queryset, *, term=None):
    aggregate_kwargs = {
        status: Count('id', filter=Q(status=status))
        for status in STATUS_VALUES
    }
    counts = queryset.aggregate(**aggregate_kwargs)
    counts['new'] = queryset.filter(get_new_students_q(term=term)).count() if term else 0
    return {key: counts.get(key, 0) for key in [*STATUS_VALUES, 'new']}
