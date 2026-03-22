from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Organization, UserRole
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
