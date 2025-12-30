# students/services.py
import re
import os
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import List, Optional

import pandas as pd
from django.db import transaction
from django.db.models import Q
from .models import Student, Parent, StudentParent
from academics.models import AcademicYear, Term, Class
from core.models import TermChoices


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
            parents_data: list of dicts, each containing parent info and relationship details (can be None)

        Returns:
            Student instance
        """
        # Create student
        student = Student.objects.create(**student_data)

        # Create parents and link them (if provided)
        if parents_data:
            for parent_data in parents_data:
                # Extract parent info and relationship data
                # parent_data should contain parent fields and relationship fields
                parent_info = {}
                relationship_data = {}
                
                # Parent fields
                parent_fields = ['first_name', 'last_name', 'gender', 'id_number', 
                               'phone_primary', 'phone_secondary', 'email', 'address', 
                               'town', 'occupation', 'employer']
                
                for field in parent_fields:
                    if field in parent_data:
                        parent_info[field] = parent_data.pop(field)
                
                # Relationship fields
                relationship_fields = ['relationship', 'is_primary', 'is_emergency_contact', 
                                     'can_pickup', 'receives_notifications']
                for field in relationship_fields:
                    if field in parent_data:
                        relationship_data[field] = parent_data.pop(field)

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
                    relationship=relationship_data.get('relationship', 'guardian'),
                    is_primary=relationship_data.get('is_primary', False),
                    is_emergency_contact=relationship_data.get('is_emergency_contact', False),
                    can_pickup=relationship_data.get('can_pickup', True),
                    receives_notifications=relationship_data.get('receives_notifications', True),
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
    def search_students(query=None, class_id=None, status=None, gender=None, is_boarder=None,
                        stream=None):  # ADD 'stream=None'
        """
        Search and filter students based on various criteria.

        Args:
            query: Search term for name or admission number
            class_id: Filter by class ID
            status: Filter by student status
            gender: Filter by gender
            is_boarder: Filter by boarding status ('yes', 'no', or None)
            stream: Filter by stream (e.g., 'EAST', 'WEST', 'SOUTH') # ADD THIS ARG DESCRIPTION

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

        if stream:  # ADD THIS BLOCK
            students = students.filter(current_class__stream=stream)

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
            'special_needs': students.filter(has_special_needs=True).count(),
            'using_transport': students.filter(uses_school_transport=True).count(),
        }

    @staticmethod
    def generate_admission_number():
        """
        Generate the next sequential admission number for a student.
        Finds the highest numeric admission number and increments it.
        Handles formats like "3389", "PWA3389", etc.
        Ensures minimum starting number is 2245.

        Returns:
            str: Next admission number (numeric only, e.g., "2245")
        """
        import re
        
        # Minimum starting admission number
        MIN_ADMISSION_NUMBER = 2245
        
        # Get all admission numbers
        all_students = Student.objects.all().values_list('admission_number', flat=True)
        
        max_number = MIN_ADMISSION_NUMBER - 1  # Start from minimum - 1, so first number will be 2245
        
        for admission_num in all_students:
            if not admission_num:
                continue
                
            # Extract numeric part (handles "PWA3389", "3389", etc.)
            # Remove any non-digit characters and get the numeric part
            numeric_part = re.sub(r'\D', '', str(admission_num))
            
            if numeric_part:
                try:
                    num = int(numeric_part)
                    if num > max_number:
                        max_number = num
                except ValueError:
                    continue
        
        # Ensure we don't go below minimum
        if max_number < MIN_ADMISSION_NUMBER - 1:
            max_number = MIN_ADMISSION_NUMBER - 1
        
        # Increment and return as string
        next_number = max_number + 1
        return str(next_number)

    # Helper functions for Excel import
    @staticmethod
    def _normalize_class_key(value: str) -> str:
        """Normalize class name for mapping."""
        value = (value or "").strip()
        value = re.sub(r"\s+", " ", value)
        return value.upper()

    @staticmethod
    def _to_decimal(value) -> Decimal:
        """Safe conversion from pandas values to Decimal."""
        if value is None:
            return Decimal("0.00")

        try:
            if pd.isna(value):
                return Decimal("0.00")
        except Exception:
            pass

        s = str(value).strip().replace(",", "")
        if s == "" or s.lower() == "nan":
            return Decimal("0.00")

        try:
            return Decimal(s)
        except (InvalidOperation, ValueError):
            return Decimal("0.00")

    @staticmethod
    def _normalize_ke_phone(digits_only: str) -> Optional[str]:
        """Convert to +254XXXXXXXXX format."""
        d = re.sub(r"\D", "", digits_only or "")
        if not d:
            return None

        if d.startswith("254") and len(d) >= 12:
            d = d[:12]
            return f"+{d}"

        if d.startswith("0") and len(d) >= 10:
            d = d[:10]
            return f"+254{d[1:]}"

        if len(d) == 9 and (d.startswith("7") or d.startswith("1")):
            return f"+254{d}"

        return None

    @staticmethod
    def _extract_phones(contacts: str) -> List[str]:
        """Extract Kenyan phone numbers from contact strings."""
        text = contacts or ""
        phones: List[str] = []
        seen = set()

        patterns = [
            r"\+254\d{9}",
            r"\b254\d{9}\b",
            r"\b0\d{9}\b",
            r"\b[71]\d{8}\b",
        ]
        for pat in patterns:
            for m in re.findall(pat, text):
                p = StudentService._normalize_ke_phone(m)
                if p and p not in seen:
                    phones.append(p)
                    seen.add(p)

        digits = re.sub(r"\D", "", text)
        for m in re.findall(r"254\d{9}", digits):
            p = StudentService._normalize_ke_phone(m)
            if p and p not in seen:
                phones.append(p)
                seen.add(p)

        for m in re.findall(r"0\d{9}", digits):
            p = StudentService._normalize_ke_phone(m)
            if p and p not in seen:
                phones.append(p)
                seen.add(p)

        return phones

    @staticmethod
    def _create_classes(academic_year):
        """Create all classes and return mapping keyed by normalized Excel class names."""
        STREAM_EAST = "East"
        class_config = [
            ("PLAYGROUP", "pp1", STREAM_EAST),
            ("PP1", "pp1", STREAM_EAST),
            ("PP2", "pp2", STREAM_EAST),
            ("GRADE 1", "grade_1", STREAM_EAST),
            ("GRADE 2", "grade_2", STREAM_EAST),
            ("GRADE 3", "grade_3", STREAM_EAST),
            ("GRADE 4", "grade_4", STREAM_EAST),
            ("GRADE 5", "grade_5", STREAM_EAST),
            ("GRADE 6", "grade_6", STREAM_EAST),
            ("GRADE SEVEN-JSS", "grade_7", STREAM_EAST),
            ("GRADE EIGHT-JSS", "grade_8", STREAM_EAST),
            ("GRADE NINE-JSS", "grade_9", STREAM_EAST),
        ]

        mapping = {}
        for excel_name, grade_level, stream in class_config:
            key = StudentService._normalize_class_key(excel_name)

            if key == "PLAYGROUP":
                display_name = "Playgroup"
            elif "JSS" in key:
                base = key.replace("-JSS", "").title()
                display_name = f"{base} (JSS)"
            else:
                display_name = key.title()

            class_obj, _ = Class.objects.get_or_create(
                name=display_name,
                academic_year=academic_year,
                defaults={
                    "grade_level": grade_level,
                    "stream": stream,
                    "capacity": 50,
                },
            )

            try:
                if getattr(class_obj, "stream", None) != stream:
                    class_obj.stream = stream
                    class_obj.save(update_fields=["stream"])
            except Exception:
                pass

            mapping[key] = class_obj

        return mapping

    @staticmethod
    @transaction.atomic
    def import_students_from_excel(file_path, dry_run=False, limit=0):
        """
        Import students from Excel file.
        
        Args:
            file_path: Path to Excel file
            dry_run: If True, validate but don't save changes
            limit: Only import first N rows (0 = all)
            
        Returns:
            dict with stats: students_created, students_updated, parents_created, rows_skipped, errors, error_details
        """
        stats = {
            "students_created": 0,
            "students_updated": 0,
            "parents_created": 0,
            "rows_skipped": 0,
            "errors": 0,
            "error_details": [],
        }

        try:
            # Read Excel file
            df = pd.read_excel(file_path)
            df.columns = [str(c).strip() for c in df.columns]

            # Rename columns
            df = df.rename(
                columns={
                    "Year": "Year",
                    "#": "Admission_No",
                    "Name": "Name",
                    "Class": "Class",
                    "Contacts": "Contacts",
                    "Total Balance": "Total_Balance",
                }
            )

            required = [
                "Year",
                "Admission_No",
                "Name",
                "Class",
                "Contacts",
                "Total_Balance",
            ]
            missing = [c for c in required if c not in df.columns]
            if missing:
                raise ValueError(f"Missing expected columns: {missing}. Found: {list(df.columns)}")

            df = df.dropna(subset=["Admission_No"]).copy()
            df["Admission_No"] = df["Admission_No"].astype(str).str.strip()
            df["Name"] = df["Name"].astype(str).str.strip()
            df["Class"] = df["Class"].astype(str).str.strip()

            if limit > 0:
                df = df.head(limit)

            # Get or create academic year and term
            academic_year, _ = AcademicYear.objects.get_or_create(
                year=2025,
                defaults={
                    "start_date": date(2025, 1, 6),
                    "end_date": date(2025, 11, 28),
                    "is_current": True,
                },
            )

            term, _ = Term.objects.get_or_create(
                academic_year=academic_year,
                term=TermChoices.TERM_3,
                defaults={
                    "start_date": date(2025, 9, 1),
                    "end_date": date(2025, 11, 28),
                    "is_current": True,
                    "fee_deadline": date(2025, 9, 15),
                },
            )

            class_mapping = StudentService._create_classes(academic_year)

            # Process each row
            for idx, row in df.iterrows():
                try:
                    StudentService._import_row(row, class_mapping, stats)
                except Exception as e:
                    stats["errors"] += 1
                    adm = str(row.get("Admission_No", "")).strip()
                    error_msg = f"[{adm}] Import failed: {str(e)}"
                    stats["error_details"].append(error_msg)

            if dry_run:
                transaction.set_rollback(True)

        except Exception as e:
            stats["errors"] += 1
            stats["error_details"].append(f"File processing error: {str(e)}")
            if dry_run:
                transaction.set_rollback(True)

        return stats

    @staticmethod
    def _import_row(row, class_mapping, stats):
        """Import a single row from Excel."""
        admission_no = str(row["Admission_No"]).strip()
        if not admission_no:
            stats["rows_skipped"] += 1
            return

        full_name = str(row["Name"]).strip()
        class_name = str(row["Class"]).strip()
        contacts = str(row["Contacts"]).strip() if pd.notna(row["Contacts"]) else ""

        # Name parsing
        name_parts = full_name.split()
        if len(name_parts) >= 3:
            first_name = name_parts[0]
            last_name = name_parts[-1]
            middle_name = " ".join(name_parts[1:-1])
        elif len(name_parts) == 2:
            first_name, last_name = name_parts
            middle_name = ""
        else:
            first_name = full_name
            last_name = ""
            middle_name = ""

        # Class mapping
        class_key = StudentService._normalize_class_key(class_name)
        class_obj = class_mapping.get(class_key)
        if not class_obj:
            stats["rows_skipped"] += 1
            return

        credit_balance = StudentService._to_decimal(row["Total_Balance"])

        # Student upsert with credit_balance
        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                "first_name": first_name.title(),
                "middle_name": middle_name.title(),
                "last_name": last_name.title(),
                "current_class": class_obj,
                "credit_balance": credit_balance,
                "admission_date": date(2025, 1, 6),
                "date_of_birth": date(2015, 1, 1),  # placeholder
                "gender": "M",  # placeholder
                "status": "active",
            },
        )
        if created:
            stats["students_created"] += 1
        else:
            stats["students_updated"] += 1

        # Parent extraction/link
        if contacts and contacts.strip().lower() not in {"254", "nan"}:
            StudentService._create_parent_from_contacts(student, contacts, stats)

    @staticmethod
    def _create_parent_from_contacts(student, contacts, stats):
        """Create parent from contacts string."""
        phones = StudentService._extract_phones(contacts)
        if not phones:
            return

        primary_phone = phones[0]
        secondary_phone = phones[1] if len(phones) > 1 else ""

        parent = Parent.objects.filter(phone_primary=primary_phone).first()
        if not parent:
            placeholder_first = student.last_name or student.first_name or "Parent"
            parent = Parent.objects.create(
                first_name=placeholder_first.title(),
                last_name="(Parent)",
                phone_primary=primary_phone,
                phone_secondary=secondary_phone,
                relationship="guardian",
            )
            stats["parents_created"] += 1

        StudentParent.objects.get_or_create(
            student=student,
            parent=parent,
            defaults={
                "relationship": "guardian",
                "is_primary": True,
                "receives_notifications": True,
            },
        )