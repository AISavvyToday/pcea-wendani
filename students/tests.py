from datetime import date

from django.test import TestCase
from django.test import RequestFactory
from django.urls import reverse

from academics.models import AcademicYear, Term
from accounts.models import User
from core.models import Organization, UserRole
from core.models import TermChoices
from students.metrics import get_student_status_counters
from students.models import Parent, Student, StudentParent
from students.views import StudentListView


class ParentManagementViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_one = Organization.objects.create(name='Org One', code='ORG1')
        cls.org_two = Organization.objects.create(name='Org Two', code='ORG2')

        cls.admin = User.objects.create_user(
            email='admin@org1.test',
            password='password123',
            first_name='Org',
            last_name='Admin',
            role=UserRole.SCHOOL_ADMIN,
            organization=cls.org_one,
        )
        cls.other_admin = User.objects.create_user(
            email='admin@org2.test',
            password='password123',
            first_name='Other',
            last_name='Admin',
            role=UserRole.SCHOOL_ADMIN,
            organization=cls.org_two,
        )

        cls.parent = Parent.objects.create(
            organization=cls.org_one,
            first_name='Grace',
            last_name='Wanjiku',
            gender='F',
            phone_primary='+254700000001',
            relationship='mother',
            email='grace@example.com',
        )
        cls.foreign_parent = Parent.objects.create(
            organization=cls.org_two,
            first_name='John',
            last_name='Otieno',
            gender='M',
            phone_primary='+254700000099',
            relationship='father',
            email='john@example.com',
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_parent_create_assigns_request_organization_and_redirects(self):
        response = self.client.post(
            reverse('students:parent_create'),
            data={
                'first_name': 'Jane',
                'last_name': 'Mwangi',
                'gender': 'F',
                'id_number': '12345678',
                'phone_primary': '+254711111111',
                'phone_secondary': '',
                'email': 'jane@example.com',
                'address': 'Nairobi',
                'town': 'Nairobi',
                'occupation': 'Engineer',
                'employer': 'Acme',
                'relationship': 'mother',
            },
        )

        self.assertRedirects(response, reverse('students:parent_list'))
        created_parent = Parent.objects.get(phone_primary='+254711111111')
        self.assertEqual(created_parent.organization, self.org_one)
        self.assertEqual(created_parent.first_name, 'Jane')

    def test_parent_edit_updates_org_scoped_parent_only(self):
        response = self.client.post(
            reverse('students:parent_update', kwargs={'pk': self.parent.pk}),
            data={
                'first_name': 'Grace',
                'last_name': 'Updated',
                'gender': 'F',
                'id_number': '',
                'phone_primary': '+254700000001',
                'phone_secondary': '+254722222222',
                'email': 'updated@example.com',
                'address': 'Updated address',
                'town': 'Kiambu',
                'occupation': 'Teacher',
                'employer': 'School',
                'relationship': 'mother',
            },
        )

        self.assertRedirects(response, reverse('students:parent_detail', kwargs={'pk': self.parent.pk}))
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.last_name, 'Updated')
        self.assertEqual(self.parent.email, 'updated@example.com')
        self.assertEqual(self.parent.organization, self.org_one)

    def test_parent_delete_is_blocked_when_children_exist(self):
        student = Student.objects.create(
            organization=self.org_one,
            admission_date=date(2024, 1, 8),
            first_name='Child',
            middle_name='A',
            last_name='One',
            gender='F',
            date_of_birth=date(2018, 5, 10),
            status='active',
        )
        StudentParent.objects.create(
            student=student,
            parent=self.parent,
            relationship='mother',
            is_primary=True,
            can_pickup=True,
            receives_notifications=True,
        )

        response = self.client.post(reverse('students:parent_delete', kwargs={'pk': self.parent.pk}))

        self.assertRedirects(response, reverse('students:parent_detail', kwargs={'pk': self.parent.pk}))
        self.assertTrue(Parent.objects.filter(pk=self.parent.pk).exists())

    def test_cross_organization_parent_access_is_denied_and_list_is_scoped(self):
        list_response = self.client.get(reverse('students:parent_list'))
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, self.parent.full_name)
        self.assertNotContains(list_response, self.foreign_parent.full_name)
        self.assertEqual(list_response.context['total_parents'], 1)

        detail_response = self.client.get(
            reverse('students:parent_detail', kwargs={'pk': self.foreign_parent.pk})
        )
        edit_response = self.client.get(
            reverse('students:parent_update', kwargs={'pk': self.foreign_parent.pk})
        )
        delete_response = self.client.get(
            reverse('students:parent_delete', kwargs={'pk': self.foreign_parent.pk})
        )
        api_response = self.client.get(
            reverse('students:api_parent_children', kwargs={'pk': self.foreign_parent.pk})
        )

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        self.assertEqual(api_response.status_code, 404)


class StudentNewMetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name='Metrics Org', code='MORG')
        cls.user = User.objects.create_user(
            email='metrics-admin@example.com',
            password='password123',
            first_name='Metrics',
            last_name='Admin',
            role=UserRole.SCHOOL_ADMIN,
            organization=cls.organization,
        )
        cls.academic_year = AcademicYear.objects.create(
            organization=cls.organization,
            year=2026,
            start_date=date(2026, 1, 5),
            end_date=date(2026, 11, 27),
            is_current=True,
        )
        cls.current_term = Term.objects.create(
            organization=cls.organization,
            academic_year=cls.academic_year,
            term=TermChoices.TERM_1,
            start_date=date(2026, 1, 5),
            end_date=date(2026, 4, 10),
            is_current=True,
        )

    def setUp(self):
        self.factory = RequestFactory()

    def _create_student(self, *, admission_number, admission_date):
        return Student.objects.create(
            organization=self.organization,
            admission_number=admission_number,
            admission_date=admission_date,
            first_name='Test',
            middle_name='',
            last_name=admission_number,
            gender='M',
            date_of_birth=date(2016, 1, 1),
            status='active',
        )

    def test_new_students_counted_when_admitted_within_current_term(self):
        self._create_student(admission_number='N001', admission_date=date(2026, 2, 1))
        self._create_student(admission_number='N002', admission_date=date(2026, 3, 1))

        request = self.factory.get(reverse('students:list'), {'status': 'new'})
        request.user = self.user
        request.organization = self.organization
        response = StudentListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data['status_counts']['new'], 2)

    def test_students_admitted_outside_current_term_are_excluded_from_new(self):
        self._create_student(admission_number='N010', admission_date=date(2025, 12, 31))
        self._create_student(admission_number='N011', admission_date=date(2026, 4, 11))
        self._create_student(admission_number='N012', admission_date=date(2026, 2, 10))

        request = self.factory.get(reverse('students:list'), {'status': 'new'})
        request.user = self.user
        request.organization = self.organization
        response = StudentListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data['status_counts']['new'], 1)

    def test_no_current_term_shows_warning_and_new_count_is_deterministic_zero(self):
        self.current_term.is_current = False
        self.current_term.save(update_fields=['is_current'])
        self._create_student(admission_number='N020', admission_date=date(2026, 2, 1))

        request = self.factory.get(reverse('students:list'), {'status': 'new'})
        request.user = self.user
        request.organization = self.organization
        response = StudentListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data['status_counts']['new'], 0)
        self.assertIsNotNone(response.context_data['new_students_term_warning'])

        base_queryset = Student.objects.filter(organization=self.organization)
        counters = get_student_status_counters(base_queryset, term=None)
        self.assertEqual(counters['new'], 0)
