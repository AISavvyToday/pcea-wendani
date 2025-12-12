# students/services.py
from django.db import transaction
from django.db.models import Q
from .models import Student, Parent, StudentParent


class StudentService:
    """
    Service layer for student-related business logic.
    Handles complex operations like student registration with parents.
    """

    @staticmethod
    @transaction.atomic
    def create_student_with_parents(student_data, parents_data):
        """
        Create a student along with parent records in a single transaction.

        Args:
            student_data: dict with student fields
            parents_data: list of dicts, each containing parent info and relationship details

        Returns:
            Student instance
        """
        # Create student
        student = Student.objects.create(**student_data)

        # Create parents and link them
        for parent_data in parents_data:
            parent_info = parent_data.pop('parent')

            # Check if parent already exists by phone or ID
            parent = None
            if parent_info.get('phone_primary'):
                parent = Parent.objects.filter(
                    phone_primary=parent_info['phone_primary']
                ).first()

            if not parent and parent_info.get('id_number'):
                parent = Parent.objects.filter(
                    id_number=parent_info['id_number']
                ).first()

            # Create parent if doesn't exist
            if not parent:
                parent = Parent.objects.create(**parent_info)

            # Create StudentParent relationship
            StudentParent.objects.create(
                student=student,
                parent=parent,
                **parent_data
            )

        return student

    @staticmethod
    @transaction.atomic
    def update_student_with_parents(student, student_data, parents_data):
        """
        Update student and parent information.

        Args:
            student: Student instance to update
            student_data: dict with updated student fields
            parents_data: list of dicts with parent info (replaces existing parents)

        Returns:
            Updated Student instance
        """
        # Update student fields
        for field, value in student_data.items():
            setattr(student, field, value)
        student.save()

        # Remove existing parent relationships
        student.student_parents.all().delete()

        # Re-create parent relationships
        for parent_data in parents_data:
            parent_info = parent_data.pop('parent')

            # Check if parent exists
            parent = None
            if parent_info.get('id'):
                parent = Parent.objects.filter(id=parent_info['id']).first()
            elif parent_info.get('phone_primary'):
                parent = Parent.objects.filter(
                    phone_primary=parent_info['phone_primary']
                ).first()

            # Create or update parent
            if parent:
                for field, value in parent_info.items():
                    setattr(parent, field, value)
                parent.save()
            else:
                parent = Parent.objects.create(**parent_info)

            # Create StudentParent relationship
            StudentParent.objects.create(
                student=student,
                parent=parent,
                **parent_data
            )

        return student

    @staticmethod
    def search_students(query=None, class_id=None, status=None, gender=None, is_boarder=None):
        """
        Search and filter students based on various criteria.

        Args:
            query: Search term for name or admission number
            class_id: Filter by class ID
            status: Filter by student status
            gender: Filter by gender
            is_boarder: Filter by boarding status ('yes', 'no', or None)

        Returns:
            QuerySet of Student objects
        """
        students = Student.objects.select_related('current_class').prefetch_related('parents')

        if query:
            students = students.filter(
                Q(first_name__icontains=query) |
                Q(middle_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(admission_number__icontains=query)
            )

        if class_id:
            students = students.filter(current_class_id=class_id)

        if status:
            students = students.filter(status=status)

        if gender:
            students = students.filter(gender=gender)

        if is_boarder == 'yes':
            students = students.filter(is_boarder=True)
        elif is_boarder == 'no':
            students = students.filter(is_boarder=False)

        return students.order_by('admission_number')

    @staticmethod
    @transaction.atomic
    def promote_students(student_ids, target_class, academic_year=None, term=None):
        """
        Promote multiple students to a new class.

        Args:
            student_ids: List of student IDs to promote
            target_class: Class instance to promote students to
            academic_year: AcademicYear instance (optional, for tracking)
            term: Term instance (optional, for tracking)

        Returns:
            Number of students promoted
        """
        students = Student.objects.filter(id__in=student_ids, status='active')

        promoted_count = 0
        for student in students:
            # Update current class
            student.current_class = target_class
            student.save()
            promoted_count += 1

        return promoted_count

    @staticmethod
    def get_student_profile_data(student):
        """
        Get comprehensive profile data for student detail view.

        Args:
            student: Student instance

        Returns:
            dict with all profile data including parents
        """
        # Get student-parent relationships
        student_parents = student.student_parents.select_related('parent').all()

        return {
            'student_parents': student_parents,
            'enrollments': [],  # Empty for now until Enrollment model is created
        }

    @staticmethod
    def get_student_summary(student):
        """
        Get a comprehensive summary of student information.

        Args:
            student: Student instance

        Returns:
            dict with student summary data
        """
        return {
            'basic_info': {
                'admission_number': student.admission_number,
                'full_name': student.full_name,
                'age': student.age,
                'gender': student.get_gender_display(),
                'current_class': str(student.current_class) if student.current_class else 'Not Assigned',
                'status': student.get_status_display(),
            },
            'parents': [
                {
                    'name': sp.parent.full_name,
                    'relationship': sp.get_relationship_display(),
                    'phone': sp.parent.phone_primary,
                    'is_primary': sp.is_primary,
                }
                for sp in student.student_parents.select_related('parent').all()
            ],
            'medical': {
                'blood_group': student.blood_group,
                'medical_conditions': student.medical_conditions,
                'emergency_contact': student.emergency_contact_name,
                'emergency_phone': student.emergency_contact_phone,
            },
            'accommodation': {
                'is_boarder': student.is_boarder,
                'dormitory': student.dormitory if student.is_boarder else 'N/A',
                'uses_transport': student.uses_school_transport,
                'transport_route': str(student.transport_route) if student.transport_route else 'N/A',
            },
            'special_needs': {
                'has_special_needs': student.has_special_needs,
                'details': student.special_needs_details if student.has_special_needs else 'None',
            }
        }

    @staticmethod
    def get_class_statistics(class_obj):
        """
        Get statistics for a specific class.

        Args:
            class_obj: Class instance

        Returns:
            dict with class statistics
        """
        students = Student.objects.filter(current_class=class_obj, status='active')

        return {
            'total_students': students.count(),
            'male_count': students.filter(gender='M').count(),
            'female_count': students.filter(gender='F').count(),
            'boarders': students.filter(is_boarder=True).count(),
            'day_scholars': students.filter(is_boarder=False).count(),
            'special_needs': students.filter(has_special_needs=True).count(),
            'using_transport': students.filter(uses_school_transport=True).count(),
        }

    @staticmethod
    def generate_admission_number(year=None):
        """
        Generate the next admission number for a student.
        Format: PWA{YEAR}{SEQUENCE}
        Example: PWA2025001

        Args:
            year: Year for admission (defaults to current year)

        Returns:
            str: Next admission number
        """
        from datetime import date

        if not year:
            year = date.today().year

        # Get the last admission number for this year
        prefix = f"PWA{year}"
        last_student = Student.objects.filter(
            admission_number__startswith=prefix
        ).order_by('-admission_number').first()

        if last_student:
            # Extract sequence number and increment
            last_sequence = int(last_student.admission_number[-3:])
            next_sequence = last_sequence + 1
        else:
            next_sequence = 1

        return f"{prefix}{next_sequence:03d}"