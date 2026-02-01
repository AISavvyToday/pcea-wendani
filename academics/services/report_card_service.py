# academics/services/report_card_service.py
"""
Service for generating report cards.
"""

import logging
from decimal import Decimal
from django.db.models import Avg, Sum, Count
from academics.models import ReportCard, ReportCardItem, Grade, Exam, Subject, Class, Term
from students.models import Student

logger = logging.getLogger(__name__)


class ReportCardService:
    """
    Service for generating and managing report cards.
    """
    
    @staticmethod
    def generate_report_card(student, term, organization=None):
        """
        Generate a report card for a student for a specific term.
        
        Args:
            student: Student instance
            term: Term instance
            organization: Organization instance (optional, will use student's organization)
        
        Returns:
            ReportCard instance
        """
        if not organization:
            organization = student.organization
        
        if not organization:
            raise ValueError("Organization is required")
        
        logger.info(f"Generating report card for {student.admission_number} - {term}")
        
        # Get or create report card
        report_card, created = ReportCard.objects.get_or_create(
            student=student,
            term=term,
            defaults={
                'organization': organization,
                'academic_year': term.academic_year,
                'class_obj': student.current_class,
            }
        )
        
        if not created:
            # Clear existing items
            report_card.items.all().delete()
        
        # Get all exams for this term
        exams = Exam.objects.filter(
            term=term,
            organization=organization,
            is_published=True
        )
        
        # Get all subjects for this student's class
        if student.current_class:
            subjects = Subject.objects.filter(
                class_subjects__class_obj=student.current_class,
                organization=organization
            ).distinct()
        else:
            subjects = Subject.objects.filter(organization=organization)
        
        total_marks = Decimal('0.00')
        subject_count = 0
        
        # Calculate marks per subject (average across all exams)
        for subject in subjects:
            grades = Grade.objects.filter(
                student=student,
                exam__in=exams,
                subject=subject,
                organization=organization
            )
            
            if grades.exists():
                avg_marks = grades.aggregate(avg=Avg('marks'))['avg'] or Decimal('0.00')
                
                # Determine grade letter
                if avg_marks >= 80:
                    grade_letter = 'EE'
                elif avg_marks >= 65:
                    grade_letter = 'ME'
                elif avg_marks >= 50:
                    grade_letter = 'AE'
                elif avg_marks >= 40:
                    grade_letter = 'BE'
                else:
                    grade_letter = 'BE'
                
                # Create report card item
                ReportCardItem.objects.create(
                    report_card=report_card,
                    subject=subject,
                    marks=avg_marks,
                    grade=grade_letter,
                )
                
                total_marks += avg_marks
                subject_count += 1
        
        # Calculate overall average
        if subject_count > 0:
            report_card.average_marks = total_marks / subject_count
            report_card.total_marks = total_marks
            
            # Determine overall grade
            if report_card.average_marks >= 80:
                report_card.overall_grade = 'EE'
            elif report_card.average_marks >= 65:
                report_card.overall_grade = 'ME'
            elif report_card.average_marks >= 50:
                report_card.overall_grade = 'AE'
            elif report_card.average_marks >= 40:
                report_card.overall_grade = 'BE'
            else:
                report_card.overall_grade = 'BE'
        else:
            report_card.average_marks = Decimal('0.00')
            report_card.total_marks = Decimal('0.00')
            report_card.overall_grade = ''
        
        # Calculate position (if class exists)
        if student.current_class:
            position = ReportCardService._calculate_position(student, term, report_card.average_marks, organization)
            report_card.position = position
        
        report_card.save()
        
        logger.info(f"Report card generated: {report_card.overall_grade}, Position: {report_card.position}")
        return report_card
    
    @staticmethod
    def _calculate_position(student, term, average_marks, organization):
        """Calculate student's position in class based on average marks."""
        if not student.current_class:
            return None
        
        # Get all report cards for this class and term
        report_cards = ReportCard.objects.filter(
            term=term,
            class_obj=student.current_class,
            organization=organization,
            average_marks__gt=0
        ).order_by('-average_marks')
        
        position = 1
        for rc in report_cards:
            if rc.student == student:
                return position
            position += 1
        
        return None
    
    @staticmethod
    def generate_report_cards_for_class(class_obj, term, organization=None):
        """
        Generate report cards for all students in a class.
        
        Returns:
            dict with 'created', 'updated', 'errors' counts
        """
        if not organization:
            organization = class_obj.organization
        
        students = Student.objects.filter(
            current_class=class_obj,
            status='active',
            organization=organization
        )
        
        created = 0
        updated = 0
        errors = 0
        
        for student in students:
            try:
                report_card, was_created = ReportCard.objects.get_or_create(
                    student=student,
                    term=term,
                    defaults={'organization': organization}
                )
                
                if was_created:
                    created += 1
                else:
                    updated += 1
                
                ReportCardService.generate_report_card(student, term, organization)
            except Exception as e:
                logger.error(f"Error generating report card for {student.admission_number}: {str(e)}", exc_info=True)
                errors += 1
        
        return {
            'created': created,
            'updated': updated,
            'errors': errors,
            'total': students.count()
        }

