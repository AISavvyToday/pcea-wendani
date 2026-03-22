from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import Organization, UserRole

from .models import Department, Staff


class StaffOnboardingWorkflowTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Test School', code='TS01')
        self.admin_user = User.objects.create_user(
            email='admin@testschool.com',
            password='secret123',
            first_name='Admin',
            last_name='User',
            role=UserRole.SCHOOL_ADMIN,
            organization=self.organization,
            is_staff=True,
        )
        self.department = Department.objects.create(
            name='Academics',
            code='ACAD',
            organization=self.organization,
        )
        self.client.force_login(self.admin_user)

    def staff_payload(self, **overrides):
        payload = {
            'email': 'teacher1@testschool.com',
            'first_name': 'Terry',
            'last_name': 'Teacher',
            'user_phone_number': '0700000001',
            'role': UserRole.TEACHER,
            'staff_number': 'TS-T-001',
            'staff_type': 'teaching',
            'department': str(self.department.pk),
            'id_number': '12345678',
            'tsc_number': 'TSC001',
            'date_of_birth': '1990-01-15',
            'gender': 'M',
            'phone_number': '0711111111',
            'address': '123 School Lane',
            'date_joined': '2024-01-10',
            'employment_type': 'permanent',
            'qualifications': 'B.Ed',
            'specialization': 'Mathematics',
            'status': 'active',
        }
        payload.update(overrides)
        return payload

    def test_staff_create_creates_linked_user_and_staff_profile(self):
        response = self.client.post(reverse('academics:staff_create'), data=self.staff_payload())

        self.assertRedirects(response, reverse('academics:staff_list'))
        staff = Staff.objects.select_related('user').get(staff_number='TS-T-001')

        self.assertEqual(staff.organization, self.organization)
        self.assertEqual(staff.user.email, 'teacher1@testschool.com')
        self.assertEqual(staff.user.organization, self.organization)
        self.assertEqual(staff.user.role, UserRole.TEACHER)
        self.assertEqual(staff.user.phone_number, '0700000001')
        self.assertTrue(staff.user.must_change_password)

    def test_staff_create_links_existing_org_user_by_email(self):
        existing_user = User.objects.create_user(
            email='teacher1@testschool.com',
            password='secret123',
            first_name='Old',
            last_name='Name',
            role=UserRole.ACCOUNTANT,
            organization=self.organization,
            phone_number='0799999999',
        )

        response = self.client.post(
            reverse('academics:staff_create'),
            data=self.staff_payload(first_name='Updated', last_name='Teacher', role=UserRole.TEACHER),
        )

        self.assertRedirects(response, reverse('academics:staff_list'))
        self.assertEqual(User.objects.filter(email='teacher1@testschool.com').count(), 1)

        existing_user.refresh_from_db()
        self.assertEqual(existing_user.first_name, 'Updated')
        self.assertEqual(existing_user.role, UserRole.TEACHER)
        self.assertEqual(existing_user.staff_profile.staff_number, 'TS-T-001')

    def test_staff_create_rejects_duplicate_email_staff_number_and_id_number(self):
        duplicate_user = User.objects.create_user(
            email='teacher1@testschool.com',
            password='secret123',
            first_name='Existing',
            last_name='Teacher',
            role=UserRole.TEACHER,
            organization=self.organization,
        )
        Staff.objects.create(
            user=duplicate_user,
            organization=self.organization,
            staff_number='TS-T-001',
            staff_type='teaching',
            department=self.department,
            id_number='12345678',
            tsc_number='TSC999',
            phone_number='0722222222',
            date_joined=date(2024, 1, 10),
            employment_type='permanent',
            status='active',
        )

        response = self.client.post(reverse('academics:staff_create'), data=self.staff_payload())

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertIn('email', form.errors)
        self.assertIn('staff_number', form.errors)
        self.assertIn('id_number', form.errors)
        self.assertEqual(Staff.objects.count(), 1)
