from datetime import date

from django.test import TestCase

from academics.models import AcademicYear, Class
from core.models import GradeLevel, Organization, StreamChoices
from students.forms import StudentForm
from students.models import Club, ClubMembership, Student
from students.services import StudentService


class StudentStreamAndClubWorkflowTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Test School', code='TS001')
        self.academic_year = AcademicYear.objects.create(
            organization=self.organization,
            year=2026,
            start_date=date(2026, 1, 5),
            end_date=date(2026, 11, 20),
            is_current=True,
        )
        self.grade5_east = Class.objects.create(
            organization=self.organization,
            name='Grade 5 East',
            academic_year=self.academic_year,
            grade_level=GradeLevel.GRADE_5,
            stream=StreamChoices.EAST,
        )
        self.grade5_west = Class.objects.create(
            organization=self.organization,
            name='Grade 5 West',
            academic_year=self.academic_year,
            grade_level=GradeLevel.GRADE_5,
            stream=StreamChoices.WEST,
        )
        self.grade6_east = Class.objects.create(
            organization=self.organization,
            name='Grade 6 East',
            academic_year=self.academic_year,
            grade_level=GradeLevel.GRADE_6,
            stream=StreamChoices.EAST,
        )
        self.grade6_west = Class.objects.create(
            organization=self.organization,
            name='Grade 6 West',
            academic_year=self.academic_year,
            grade_level=GradeLevel.GRADE_6,
            stream=StreamChoices.WEST,
        )
        self.student_east = Student.objects.create(
            organization=self.organization,
            admission_number='1001',
            admission_date=date(2026, 1, 5),
            first_name='Alice',
            last_name='East',
            gender='F',
            date_of_birth=date(2015, 5, 1),
            current_class=self.grade5_east,
            status='active',
        )
        self.student_east_two = Student.objects.create(
            organization=self.organization,
            admission_number='1002',
            admission_date=date(2026, 1, 5),
            first_name='Brian',
            last_name='East',
            gender='M',
            date_of_birth=date(2015, 6, 1),
            current_class=self.grade6_east,
            status='active',
        )
        self.student_west = Student.objects.create(
            organization=self.organization,
            admission_number='1003',
            admission_date=date(2026, 1, 5),
            first_name='Carla',
            last_name='West',
            gender='F',
            date_of_birth=date(2015, 7, 1),
            current_class=self.grade5_west,
            status='active',
        )
        self.music_club = Club.objects.create(organization=self.organization, name='Music Club')
        self.science_club = Club.objects.create(organization=self.organization, name='Science Club')

    def test_search_students_filters_by_stream(self):
        east_students = StudentService.search_students(
            stream=StreamChoices.EAST,
            organization=self.organization,
        )

        self.assertQuerysetEqual(
            east_students,
            [self.student_east, self.student_east_two],
            transform=lambda student: student,
            ordered=True,
        )

    def test_bulk_reassign_stream_moves_multiple_students_to_matching_stream_classes(self):
        result = StudentService.bulk_reassign_stream(
            student_ids=[self.student_east.id, self.student_east_two.id],
            target_stream=StreamChoices.WEST,
            organization=self.organization,
        )

        self.student_east.refresh_from_db()
        self.student_east_two.refresh_from_db()

        self.assertEqual(result['moved_count'], 2)
        self.assertEqual(result['missing_targets'], [])
        self.assertEqual(self.student_east.current_class, self.grade5_west)
        self.assertEqual(self.student_east_two.current_class, self.grade6_west)

    def test_student_form_assigns_and_removes_club_memberships(self):
        assign_form = StudentForm(
            data={
                'admission_number': self.student_east.admission_number,
                'admission_date': self.student_east.admission_date.isoformat(),
                'first_name': self.student_east.first_name,
                'middle_name': '',
                'last_name': self.student_east.last_name,
                'gender': self.student_east.gender,
                'date_of_birth': self.student_east.date_of_birth.isoformat(),
                'birth_certificate_number': '',
                'current_class': str(self.grade5_east.id),
                'clubs': [str(self.music_club.id), str(self.science_club.id)],
                'blood_group': '',
                'medical_conditions': '',
                'emergency_contact_name': '',
                'emergency_contact_phone': '',
                'previous_school': '',
                'previous_class': '',
                'status': self.student_east.status,
                'status_reason': '',
                'transport_pickup_person': '',
                'upi_number': '',
                'assessment_number': '',
                'residence': '',
            },
            files={},
            instance=self.student_east,
            organization=self.organization,
        )
        self.assertTrue(assign_form.is_valid(), assign_form.errors)
        assign_form.save()

        self.assertCountEqual(
            self.student_east.clubs.order_by('name').values_list('name', flat=True),
            ['Music Club', 'Science Club'],
        )
        self.assertEqual(ClubMembership.objects.filter(student=self.student_east).count(), 2)

        remove_form = StudentForm(
            data={
                'admission_number': self.student_east.admission_number,
                'admission_date': self.student_east.admission_date.isoformat(),
                'first_name': self.student_east.first_name,
                'middle_name': '',
                'last_name': self.student_east.last_name,
                'gender': self.student_east.gender,
                'date_of_birth': self.student_east.date_of_birth.isoformat(),
                'birth_certificate_number': '',
                'current_class': str(self.grade5_east.id),
                'clubs': [str(self.science_club.id)],
                'blood_group': '',
                'medical_conditions': '',
                'emergency_contact_name': '',
                'emergency_contact_phone': '',
                'previous_school': '',
                'previous_class': '',
                'status': self.student_east.status,
                'status_reason': '',
                'transport_pickup_person': '',
                'upi_number': '',
                'assessment_number': '',
                'residence': '',
            },
            files={},
            instance=self.student_east,
            organization=self.organization,
        )
        self.assertTrue(remove_form.is_valid(), remove_form.errors)
        remove_form.save()

        self.assertCountEqual(
            self.student_east.clubs.values_list('name', flat=True),
            ['Science Club'],
        )
        self.assertEqual(ClubMembership.objects.filter(student=self.student_east).count(), 1)
