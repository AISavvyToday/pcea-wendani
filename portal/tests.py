from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from academics.models import AcademicYear, Term
from core.models import Gender, Organization, TermChoices, UserRole
from students.models import Student


class DashboardStudentCounterSyncTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Counter Org', code='counter-org')
        self.other_organization = Organization.objects.create(name='Other Org', code='other-org')

        self.user = User.objects.create_user(
            email='admin@example.com',
            password='password123',
            first_name='Admin',
            last_name='User',
            role=UserRole.SCHOOL_ADMIN,
            organization=self.organization,
            is_staff=True,
        )

        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            organization=self.organization,
            academic_year=self.academic_year,
            term=TermChoices.TERM_1,
            start_date=date(2026, 1, 6),
            end_date=date(2026, 4, 4),
            is_current=True,
        )

        Student.objects.create(
            organization=self.organization,
            admission_number='ADM001',
            admission_date=date(2026, 1, 10),
            first_name='New',
            last_name='Active',
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 5, 1),
            status='active',
        )
        Student.objects.create(
            organization=self.organization,
            admission_number='ADM002',
            admission_date=date(2025, 9, 10),
            first_name='Existing',
            last_name='Active',
            gender=Gender.MALE,
            date_of_birth=date(2015, 7, 1),
            status='active',
        )
        Student.objects.create(
            organization=self.organization,
            admission_number='ADM003',
            admission_date=date(2025, 5, 1),
            first_name='Grad',
            last_name='Student',
            gender=Gender.FEMALE,
            date_of_birth=date(2014, 6, 1),
            status='graduated',
        )
        Student.objects.create(
            organization=self.organization,
            admission_number='ADM004',
            admission_date=date(2025, 6, 1),
            first_name='Transfer',
            last_name='Student',
            gender=Gender.MALE,
            date_of_birth=date(2014, 8, 1),
            status='transferred',
        )
        Student.objects.create(
            organization=self.other_organization,
            admission_number='ADM999',
            admission_date=date(2026, 1, 12),
            first_name='Ignored',
            last_name='Student',
            gender=Gender.FEMALE,
            date_of_birth=date(2016, 9, 1),
            status='active',
        )

    def test_dashboard_student_card_matches_student_list_counters(self):
        self.client.force_login(self.user)

        dashboard_response = self.client.get(reverse('portal:dashboard_admin'))
        students_response = self.client.get(reverse('students:list'))

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(students_response.status_code, 200)

        student_card = next(
            card for card in dashboard_response.context['stat_cards']
            if card['title'] == 'Total Students(Active only)'
        )
        status_counts = students_response.context['status_counts']

        self.assertEqual(int(student_card['value'].replace(',', '')), status_counts['active'])
        self.assertIn(f"New-{status_counts['new']}", student_card['helper_lines'])
        self.assertIn(
            f"Graduated-{status_counts['graduated']}, Transferred-{status_counts['transferred']}",
            student_card['helper_lines'],
        )
