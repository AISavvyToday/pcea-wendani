from datetime import date

from django.test import TestCase

from academics.models import AcademicYear, Term
from core.models import Organization
from students.metrics import get_current_term


class CurrentTermIsolationRegressionTests(TestCase):
    def test_marking_current_term_is_scoped_per_organization(self):
        org_one = Organization.objects.create(name='Org One', code='ORG1X')
        org_two = Organization.objects.create(name='Org Two', code='ORG2X')

        ay_one = AcademicYear.objects.create(
            organization=org_one,
            year=2027,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
            is_current=True,
        )
        ay_two = AcademicYear.objects.create(
            organization=org_two,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=True,
        )

        term_one = Term.objects.create(
            organization=org_one,
            academic_year=ay_one,
            term='term_1',
            start_date=date(2027, 1, 1),
            end_date=date(2027, 4, 30),
            is_current=True,
        )
        term_two = Term.objects.create(
            organization=org_two,
            academic_year=ay_two,
            term='term_1',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 30),
            is_current=True,
        )

        term_one.refresh_from_db()
        term_two.refresh_from_db()
        ay_one.refresh_from_db()
        ay_two.refresh_from_db()

        self.assertTrue(term_one.is_current)
        self.assertTrue(term_two.is_current)
        self.assertTrue(ay_one.is_current)
        self.assertTrue(ay_two.is_current)

    def test_get_current_term_falls_back_to_latest_org_term_when_is_current_is_missing(self):
        org = Organization.objects.create(name='Org Three', code='ORG3X')
        ay = AcademicYear.objects.create(
            organization=org,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=False,
        )
        latest_term = Term.objects.create(
            organization=org,
            academic_year=ay,
            term='term_1',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 30),
            is_current=False,
        )

        self.assertEqual(get_current_term(organization=org), latest_term)
