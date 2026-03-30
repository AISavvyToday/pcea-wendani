from datetime import date

from django.test import TestCase, override_settings
from django.urls import reverse

from academics.models import AcademicYear, Class, Term
from accounts.models import User
from core.models import GradeLevel, Organization, StreamChoices, TermChoices, UserRole
from students.metrics import get_student_status_counters
from students.models import Club, ClubMembership, Student


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
class StudentsRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name='Regression School', code='RGS')
        cls.admin = User.objects.create_user(
            email='admin@regression.test',
            password='password123',
            first_name='Regression',
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
        cls.grade4_east = Class.objects.create(
            organization=cls.organization,
            name='Grade 4 East',
            grade_level=GradeLevel.GRADE_4,
            stream=StreamChoices.EAST,
            academic_year=cls.academic_year,
        )
        cls.grade4_west = Class.objects.create(
            organization=cls.organization,
            name='Grade 4 West',
            grade_level=GradeLevel.GRADE_4,
            stream=StreamChoices.WEST,
            academic_year=cls.academic_year,
        )
        cls.grade5_east = Class.objects.create(
            organization=cls.organization,
            name='Grade 5 East',
            grade_level=GradeLevel.GRADE_5,
            stream=StreamChoices.EAST,
            academic_year=cls.academic_year,
        )
        cls.grade6_east = Class.objects.create(
            organization=cls.organization,
            name='Grade 6 East',
            grade_level=GradeLevel.GRADE_6,
            stream=StreamChoices.EAST,
            academic_year=cls.academic_year,
        )
        cls.amina = Student.objects.create(
            organization=cls.organization,
            admission_number='ADM-001',
            admission_date=date(2026, 1, 7),
            first_name='Amina',
            last_name='Njeri',
            gender='F',
            date_of_birth=date(2015, 2, 1),
            status='active',
            current_class=cls.grade4_east,
        )
        cls.brian = Student.objects.create(
            organization=cls.organization,
            admission_number='ADM-002',
            admission_date=date(2026, 1, 7),
            first_name='Brian',
            last_name='Mwangi',
            gender='M',
            date_of_birth=date(2015, 4, 1),
            status='active',
            current_class=cls.grade4_west,
        )
        cls.zawadi = Student.objects.create(
            organization=cls.organization,
            admission_number='ADM-003',
            admission_date=date(2026, 1, 8),
            first_name='Zawadi',
            last_name='Otieno',
            gender='F',
            date_of_birth=date(2014, 4, 1),
            status='active',
            current_class=cls.grade6_east,
        )
        cls.chess = Club.objects.create(
            organization=cls.organization,
            name='Chess Club',
            code='CHESS',
            description='Strategy club',
        )
        ClubMembership.objects.create(club=cls.chess, student=cls.amina, is_active=True)
        ClubMembership.objects.create(club=cls.chess, student=cls.brian, is_active=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_club_members_can_be_exported_to_excel_and_pdf(self):
        excel_response = self.client.get(reverse('students:club_members_export_excel', args=[self.chess.pk]))
        pdf_response = self.client.get(reverse('students:club_members_export_pdf', args=[self.chess.pk]))

        self.assertEqual(excel_response.status_code, 200)
        self.assertIn('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', excel_response['Content-Type'])
        self.assertIn('club-members-Chess Club.xlsx', excel_response['Content-Disposition'])
        self.assertGreater(len(excel_response.content), 100)

        self.assertEqual(pdf_response.status_code, 200)
        self.assertIn('application/pdf', pdf_response['Content-Type'])
        self.assertIn('club-members-Chess Club.pdf', pdf_response['Content-Disposition'])
        self.assertGreater(len(pdf_response.content), 100)

    def test_club_membership_search_filters_by_name_admission_and_class(self):
        url = reverse('students:club_detail', args=[self.chess.pk])

        for term in ('Zawadi', 'ADM-003', 'Grade 6 East'):
            response = self.client.get(url, {'student_search': term})
            self.assertEqual(response.status_code, 200)
            form_queryset = response.context['membership_form'].fields['students'].queryset
            self.assertEqual([student.full_name for student in form_queryset], ['Zawadi Otieno'])

    def test_bulk_stream_search_filters_by_name_admission_and_class(self):
        url = reverse('students:bulk_stream_transfer')

        response_by_name = self.client.get(url, {'student_search': 'Amina'})
        response_by_admission = self.client.get(url, {'student_search': 'ADM-001'})
        response_by_class = self.client.get(url, {'student_search': 'Grade 4 East'})

        for response in (response_by_name, response_by_admission, response_by_class):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Amina Njeri')
            self.assertNotContains(response, 'Brian Mwangi')

    def test_bulk_stream_students_are_shown_in_ascending_grade_order(self):
        response = self.client.get(reverse('students:bulk_stream_transfer'))
        html = response.content.decode()
        self.assertLess(html.index('ADM-001 - Amina Njeri'), html.index('ADM-003 - Zawadi Otieno'))

    def test_bulk_stream_move_succeeds(self):
        response = self.client.post(
            reverse('students:bulk_stream_transfer'),
            data={
                'source_class': str(self.grade4_east.pk),
                'source_stream': self.grade4_east.stream,
                'student_search': 'Amina',
                'target_class': str(self.grade5_east.pk),
                'students': [str(self.amina.pk)],
                'action': 'move',
            },
            follow=True,
        )

        self.assertRedirects(response, reverse('students:bulk_stream_transfer') + f'?source_class={self.grade4_east.pk}&source_stream={self.grade4_east.stream}&student_search=Amina')
        self.amina.refresh_from_db()
        self.assertEqual(self.amina.current_class, self.grade5_east)
        self.assertContains(response, 'Successfully moved 1 student(s) to Grade 5 East.')

    def test_new_students_counter_uses_current_term(self):
        Student.objects.create(
            organization=self.organization,
            admission_number='ADM-084',
            admission_date=date(2026, 2, 1),
            first_name='New',
            last_name='Student',
            gender='M',
            date_of_birth=date(2016, 1, 1),
            status='active',
            current_class=self.grade4_east,
        )
        base_queryset = Student.objects.filter(organization=self.organization, is_active=True)

        counters = get_student_status_counters(base_queryset, term=self.current_term, organization=self.organization)

        self.assertEqual(counters['new'], 4)

    def test_new_students_counter_falls_back_to_current_academic_year_when_term_missing(self):
        self.current_term.is_current = False
        self.current_term.save(update_fields=['is_current'])
        base_queryset = Student.objects.filter(organization=self.organization, is_active=True)

        counters = get_student_status_counters(base_queryset, term=None, organization=self.organization)

        self.assertEqual(counters['new'], 3)
