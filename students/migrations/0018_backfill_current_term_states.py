from django.db import migrations


TERMINAL_STATUSES = {"graduated", "transferred", "withdrawn", "expelled"}


def _as_date(value):
    if value is None:
        return None
    return value.date() if hasattr(value, "date") else value


def backfill_current_term_states(apps, schema_editor):
    Student = apps.get_model("students", "Student")
    StudentTermState = apps.get_model("students", "StudentTermState")
    Term = apps.get_model("academics", "Term")

    current_terms = Term.objects.filter(is_current=True, is_active=True)
    for term in current_terms.iterator():
        students = Student.objects.filter(is_active=True, organization_id=term.organization_id)
        for student in students.iterator():
            admission_date = _as_date(student.admission_date)
            if admission_date and admission_date > term.end_date:
                continue

            status_date = _as_date(student.status_date)
            if (
                student.status in TERMINAL_STATUSES
                and status_date
                and status_date < term.start_date
            ):
                StudentTermState.objects.filter(
                    organization_id=term.organization_id,
                    student_id=student.pk,
                    term_id=term.pk,
                    is_active=True,
                ).update(is_active=False)
                continue

            StudentTermState.objects.update_or_create(
                organization_id=term.organization_id,
                student_id=student.pk,
                term_id=term.pk,
                defaults={
                    "class_obj_id": student.current_class_id,
                    "status": student.status,
                    "status_date": student.status_date,
                    "uses_school_transport": student.uses_school_transport,
                    "transport_route_id": student.transport_route_id,
                    "transport_trip_type": "full",
                    "is_active": True,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0017_studenttermstate_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_current_term_states, migrations.RunPython.noop),
    ]
