from datetime import date

from django.test import TestCase

from accounts.models import User
from academics.forms import StaffOnboardingForm
from academics.models import Department, Staff
from core.models import Organization, UserRole

from .forms import StaffSalaryForm


class StaffSalaryWorkflowTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Payroll School', code='PS01')
        self.other_organization = Organization.objects.create(name='Other School', code='OS01')
        self.department = Department.objects.create(
            name='Finance',
            code='FIN',
            organization=self.organization,
        )

    def onboarding_payload(self, **overrides):
        payload = {
            'email': 'payroll.staff@testschool.com',
            'first_name': 'Paula',
            'last_name': 'Payroll',
            'user_phone_number': '0700001111',
            'role': UserRole.ACCOUNTANT,
            'staff_number': 'PS-A-001',
            'staff_type': 'admin',
            'department': self.department,
            'id_number': '87654321',
            'tsc_number': '',
            'date_of_birth': '1992-02-20',
            'gender': 'F',
            'phone_number': '0712345678',
            'address': 'Payroll Street',
            'date_joined': '2024-02-01',
            'employment_type': 'permanent',
            'qualifications': 'CPA',
            'specialization': 'Payroll',
            'status': 'active',
        }
        payload.update(overrides)
        return payload

    def test_staff_salary_form_shows_staff_created_via_supported_workflow(self):
        form = StaffOnboardingForm(data=self.onboarding_payload(), organization=self.organization)
        self.assertTrue(form.is_valid(), form.errors)
        supported_staff = form.save()

        inconsistent_user = User.objects.create_user(
            email='legacy.staff@testschool.com',
            password='secret123',
            first_name='Legacy',
            last_name='User',
            role=UserRole.ACCOUNTANT,
            organization=self.other_organization,
        )
        inconsistent_staff = Staff.objects.create(
            user=inconsistent_user,
            organization=self.organization,
            staff_number='PS-A-LEGACY',
            staff_type='admin',
            department=self.department,
            id_number='99999999',
            tsc_number='',
            phone_number='0790000000',
            date_joined=date(2024, 2, 1),
            employment_type='permanent',
            status='active',
        )

        salary_form = StaffSalaryForm(organization=self.organization)
        staff_queryset = salary_form.fields['staff'].queryset

        self.assertIn(supported_staff, staff_queryset)
        self.assertNotIn(inconsistent_staff, staff_queryset)
