from django.db import migrations


def repair_current_term_and_year(apps, schema_editor):
    AcademicYear = apps.get_model('academics', 'AcademicYear')
    Term = apps.get_model('academics', 'Term')
    Organization = apps.get_model('core', 'Organization')

    org_ids = list(Organization.objects.values_list('id', flat=True))
    scopes = org_ids + [None]

    for org_id in scopes:
        year_qs = AcademicYear.objects.filter(organization_id=org_id)
        term_qs = Term.objects.filter(organization_id=org_id).select_related('academic_year')

        current_years = year_qs.filter(is_current=True).order_by('-year', '-id')
        current_terms = term_qs.filter(is_current=True).order_by('-academic_year__year', '-start_date', '-end_date', 'term', '-id')

        chosen_term = current_terms.first()
        if chosen_term is None:
            chosen_term = term_qs.order_by('-academic_year__year', '-start_date', '-end_date', 'term', '-id').first()

        if chosen_term is not None:
            term_qs.exclude(pk=chosen_term.pk).update(is_current=False)
            if not chosen_term.is_current:
                chosen_term.is_current = True
                chosen_term.save(update_fields=['is_current'])

        chosen_year = current_years.first()
        if chosen_year is None and chosen_term is not None:
            chosen_year = year_qs.filter(pk=chosen_term.academic_year_id).first()
        if chosen_year is None:
            chosen_year = year_qs.order_by('-year', '-id').first()

        if chosen_year is not None:
            year_qs.exclude(pk=chosen_year.pk).update(is_current=False)
            if not chosen_year.is_current:
                chosen_year.is_current = True
                chosen_year.save(update_fields=['is_current'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0012_academicyear_organization_attendance_organization_and_more'),
    ]

    operations = [
        migrations.RunPython(repair_current_term_and_year, noop),
    ]
