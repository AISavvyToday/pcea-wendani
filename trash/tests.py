from datetime import date
from django.utils import timezone

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.template.loader import render_to_string

from academics.models import AcademicYear, Class
from core.models import Organization
from students.models import Student
from trash.views import TrashDashboardView

User = get_user_model()


class TrashSidebarAndViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name='Trash Org', code='TRASH')
        self.user = User.objects.create_user(
            email='admin@trash.test',
            password='secret123',
            first_name='Trash',
            last_name='Admin',
            organization=self.organization,
            role='super_admin',
        )
        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_current=True,
        )
        self.classroom = Class.objects.create(
            organization=self.organization,
            name='Grade 1 Blue',
            grade_level='grade_1',
            stream='BLUE',
            academic_year=self.academic_year,
        )
        self.student = Student.objects.create(
            organization=self.organization,
            admission_number='TR001',
            admission_date=date(2026, 1, 5),
            first_name='Deleted',
            last_name='Student',
            gender='F',
            date_of_birth=date(2018, 5, 1),
            current_class=self.classroom,
            status='inactive',
            is_active=False,
            deleted_by=self.user,
            deleted_at=timezone.now(),
        )

    def test_sidebar_contains_trash_link_for_admins(self):
        html = render_to_string('base/_sidebar.html', {'user': self.user, 'is_admin': True})
        self.assertIn("Trash", html)
        self.assertIn("/trash/", html)

    def test_dashboard_lists_deleted_records(self):
        request = self.factory.get('/trash/')
        request.user = self.user
        request.organization = self.organization

        view = TrashDashboardView()
        view.request = request
        context = view.get_context_data()

        self.assertEqual(context['selected_type'], 'all')
        self.assertTrue(any(record['type'] == 'student' for record in context['records']))
