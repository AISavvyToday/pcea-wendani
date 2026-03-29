from datetime import date

from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from academics.models import AcademicYear, Class
from accounts.models import User
from core.models import GradeLevel, Organization, StreamChoices, UserRole
from students.models import Parent, Student, StudentParent


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


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
class BulkStreamTransferViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name='Transfer School', code='TRF')
        cls.admin = User.objects.create_user(
            email='admin@transfer.test',
            password='password123',
            first_name='Transfer',
            last_name='Admin',
            role=UserRole.SCHOOL_ADMIN,
            organization=cls.organization,
        )
        cls.current_year = AcademicYear.objects.create(
            organization=cls.organization,
            year=2026,
            start_date=date(2026, 1, 5),
            end_date=date(2026, 12, 1),
            is_current=True,
        )
        cls.source_class = Class.objects.create(
            organization=cls.organization,
            name='Grade 4 East',
            grade_level=GradeLevel.GRADE_4,
            stream=StreamChoices.EAST,
            academic_year=cls.current_year,
        )
        cls.other_class = Class.objects.create(
            organization=cls.organization,
            name='Grade 4 West',
            grade_level=GradeLevel.GRADE_4,
            stream=StreamChoices.WEST,
            academic_year=cls.current_year,
        )
        cls.target_class = Class.objects.create(
            organization=cls.organization,
            name='Grade 5 East',
            grade_level=GradeLevel.GRADE_5,
            stream=StreamChoices.EAST,
            academic_year=cls.current_year,
        )
        cls.student_in_source = Student.objects.create(
            organization=cls.organization,
            admission_number='ADM-001',
            admission_date=date(2026, 1, 7),
            first_name='Amina',
            middle_name='',
            last_name='Njeri',
            gender='F',
            date_of_birth=date(2015, 2, 1),
            status='active',
            current_class=cls.source_class,
        )
        cls.student_in_other = Student.objects.create(
            organization=cls.organization,
            admission_number='ADM-002',
            admission_date=date(2026, 1, 7),
            first_name='Brian',
            middle_name='',
            last_name='Mwangi',
            gender='M',
            date_of_birth=date(2015, 4, 1),
            status='active',
            current_class=cls.other_class,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_get_search_filters_by_name_admission_and_class(self):
        url = reverse('students:bulk_stream_transfer')

        response_by_name = self.client.get(url, {'student_search': 'Amina'})
        response_by_admission = self.client.get(url, {'student_search': 'ADM-001'})
        response_by_class = self.client.get(url, {'student_search': 'Grade 4 East'})

        for response in (response_by_name, response_by_admission, response_by_class):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Amina Njeri')
            self.assertNotContains(response, 'Brian Mwangi')

    def test_post_moves_students_and_shows_success_message(self):
        response = self.client.post(
            reverse('students:bulk_stream_transfer'),
            data={
                'source_class': str(self.source_class.pk),
                'source_stream': self.source_class.stream,
                'student_search': 'Amina',
                'target_class': str(self.target_class.pk),
                'students': [str(self.student_in_source.pk)],
            },
            follow=True,
        )

        self.assertRedirects(response, reverse('students:bulk_stream_transfer'))
        self.student_in_source.refresh_from_db()
        self.assertEqual(self.student_in_source.current_class, self.target_class)
        self.assertContains(response, f'Successfully moved 1 student(s) to {self.target_class.name}.')
