from datetime import date, datetime

from django.test import TestCase
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from academics.models import AcademicYear, Term
from django.test.utils import override_settings
from django.test import TestCase, override_settings
from django.urls import reverse

from academics.models import AcademicYear, Class
from accounts.models import User
from core.models import GradeLevel, Organization, StreamChoices, UserRole
from academics.models import AcademicYear, Term
from core.models import Organization, UserRole
from core.models import TermChoices
from students.metrics import get_student_status_counters
from students.metrics import get_current_term, get_new_students_q
from students.models import Parent, Student, StudentParent, StudentTermState
from students.views import StudentListView


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
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

    def test_new_tab_marks_rows_as_new_for_current_term(self):
        self._create_student(admission_number='N030', admission_date=date(2026, 2, 1))

        request = self.factory.get(reverse('students:list'), {'status': 'new'})
        request.user = self.user
        request.organization = self.organization
        response = StudentListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        students = list(response.context_data['students'])
        self.assertEqual(len(students), 1)
        self.assertEqual(students[0].list_status, 'new')
        self.assertEqual(students[0].list_status_label, 'New')

    def test_transferred_tab_uses_current_term_status_events(self):
        old_transfer = self._create_student(admission_number='TOLD', admission_date=date(2025, 5, 1))
        old_transfer.status = 'transferred'
        old_transfer.status_date = timezone.make_aware(datetime(2025, 12, 1, 8, 0))
        old_transfer.save()
        current_transfer = self._create_student(admission_number='TCURRENT', admission_date=date(2025, 5, 1))
        current_transfer.status = 'transferred'
        current_transfer.status_date = timezone.make_aware(datetime(2026, 2, 1, 8, 0))
        current_transfer.save()

        StudentTermState.objects.create(
            organization=self.organization,
            student=old_transfer,
            term=self.current_term,
            status='transferred',
            status_date=old_transfer.status_date,
        )
        StudentTermState.objects.create(
            organization=self.organization,
            student=current_transfer,
            term=self.current_term,
            status='transferred',
            status_date=current_transfer.status_date,
        )

        request = self.factory.get(reverse('students:list'), {'status': 'transferred'})
        request.user = self.user
        request.organization = self.organization
        response = StudentListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data['status_counts']['transferred'], 1)
        students = list(response.context_data['students'])
        self.assertEqual([student.admission_number for student in students], ['TCURRENT'])
        self.assertEqual(students[0].list_status, 'transferred')

    def test_no_current_term_falls_back_to_latest_term_for_new_count(self):
        self.current_term.is_current = False
        self.current_term.save(update_fields=['is_current'])
        self._create_student(admission_number='N020', admission_date=date(2026, 2, 1))

        request = self.factory.get(reverse('students:list'), {'status': 'new'})
        request.user = self.user
        request.organization = self.organization
        response = StudentListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data['status_counts']['new'], 1)
        self.assertIsNone(response.context_data['new_students_term_warning'])

        base_queryset = Student.objects.filter(organization=self.organization)
        counters = get_student_status_counters(base_queryset, term=self.current_term)
        self.assertEqual(counters['new'], 1)


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
                'action': 'move',
            },
            follow=True,
        )

        expected_url = (
            f"{reverse('students:bulk_stream_transfer')}"
            f"?source_class={self.source_class.pk}&source_stream={self.source_class.stream}&student_search=Amina"
        )
        self.assertRedirects(response, expected_url)
        self.student_in_source.refresh_from_db()
        self.assertEqual(self.student_in_source.current_class, self.target_class)
        self.assertContains(response, f'Successfully moved 1 student(s) to {self.target_class.name}.')
@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class StudentMetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_one = Organization.objects.create(name='Metrics Org One', code='MORG1')
        cls.org_two = Organization.objects.create(name='Metrics Org Two', code='MORG2')

        cls.admin = User.objects.create_user(
            email='metrics-admin@org1.test',
            password='password123',
            first_name='Metrics',
            last_name='Admin',
            role=UserRole.SCHOOL_ADMIN,
            organization=cls.org_one,
        )

    def _create_student(self, *, organization, admission_date, status='active', suffix='1'):
        return Student.objects.create(
            organization=organization,
            admission_date=admission_date,
            first_name=f'Student{suffix}',
            middle_name='Test',
            last_name='User',
            gender='F',
            date_of_birth=date(2018, 5, 10),
            status=status,
            admission_number=f'ADM-{organization.code}-{suffix}-{admission_date.isoformat()}',
        )

    def test_get_current_term_prefers_org_current_term(self):
        ay = AcademicYear.objects.create(
            organization=self.org_one,
            year=2040,
            start_date=date(2040, 1, 1),
            end_date=date(2040, 12, 31),
            is_current=True,
        )
        term = Term.objects.create(
            organization=self.org_one,
            academic_year=ay,
            term='term_2',
            start_date=date(2040, 5, 1),
            end_date=date(2040, 8, 31),
            is_current=True,
        )

        resolved = get_current_term(organization=self.org_one)

        self.assertEqual(resolved, term)

    def test_get_new_students_q_uses_academic_year_when_current_term_missing(self):
        ay = AcademicYear.objects.create(
            organization=self.org_one,
            year=2041,
            start_date=date(2041, 1, 1),
            end_date=date(2041, 12, 31),
            is_current=True,
        )

        in_year = self._create_student(
            organization=self.org_one,
            admission_date=date(2041, 6, 5),
            suffix='in-year',
        )
        out_of_year = self._create_student(
            organization=self.org_one,
            admission_date=date(2042, 1, 5),
            suffix='out-year',
        )

        matching_ids = set(
            Student.objects.filter(
                get_new_students_q(term=None, organization=self.org_one)
            ).values_list('id', flat=True)
        )

        self.assertIn(in_year.id, matching_ids)
        self.assertNotIn(out_of_year.id, matching_ids)
        self.assertEqual(get_current_term(organization=self.org_one), None)
        self.assertIsNotNone(ay)

    def test_get_new_students_q_includes_term_boundaries(self):
        ay = AcademicYear.objects.create(
            organization=self.org_two,
            year=2042,
            start_date=date(2042, 1, 1),
            end_date=date(2042, 12, 31),
            is_current=False,
        )
        term = Term.objects.create(
            organization=self.org_two,
            academic_year=ay,
            term='term_1',
            start_date=date(2042, 1, 10),
            end_date=date(2042, 4, 10),
            is_current=True,
        )

        at_start = self._create_student(
            organization=self.org_two,
            admission_date=date(2042, 1, 10),
            suffix='start',
        )
        at_end = self._create_student(
            organization=self.org_two,
            admission_date=date(2042, 4, 10),
            suffix='end',
        )
        before_term = self._create_student(
            organization=self.org_two,
            admission_date=date(2042, 1, 9),
            suffix='before',
        )

        matching_ids = set(
            Student.objects.filter(get_new_students_q(term=term)).values_list('id', flat=True)
        )

        self.assertIn(at_start.id, matching_ids)
        self.assertIn(at_end.id, matching_ids)
        self.assertNotIn(before_term.id, matching_ids)

    def test_student_list_shows_warning_when_current_term_unresolved(self):
        self.client.force_login(self.admin)
        AcademicYear.objects.create(
            organization=self.org_one,
            year=2043,
            start_date=date(2043, 1, 1),
            end_date=date(2043, 12, 31),
            is_current=False,
        )

        response = self.client.get(reverse('students:list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Current term could not be resolved for this organization')
        self.assertTrue(response.context['term_resolution_warning'])
