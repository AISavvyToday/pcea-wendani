# communications/services/sms_template_service.py
"""
Service for replacing SMS message placeholders with actual data.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


class SMSTemplateService:
    """Service for processing SMS templates with placeholders."""
    
    @staticmethod
    def replace_placeholders(template, context=None):
        """
        Replace placeholders in SMS template with actual values.
        
        Args:
            template: SMS message template with placeholders like {parent.name}
            context: Dictionary containing data for replacement
                    Expected keys: parent, student, invoice, attendance, grade
        
        Returns:
            String with placeholders replaced
        """
        if not template:
            return ""
        
        if not context:
            context = {}
        
        result = template
        
        # Parent placeholders
        parent = context.get('parent')
        if parent:
            result = result.replace('{parent.name}', parent.full_name if hasattr(parent, 'full_name') else str(parent))
            result = result.replace('{parent.first_name}', parent.first_name if hasattr(parent, 'first_name') else '')
            result = result.replace('{parent.phone}', parent.phone_primary if hasattr(parent, 'phone_primary') else '')
        
        # Student placeholders
        student = context.get('student')
        if student:
            result = result.replace('{student.name}', student.full_name if hasattr(student, 'full_name') else str(student))
            result = result.replace('{student.admission_number}', student.admission_number if hasattr(student, 'admission_number') else '')
            result = result.replace('{student.class}', str(student.current_class) if hasattr(student, 'current_class') and student.current_class else '')
            
            # Outstanding balance
            if hasattr(student, 'outstanding_balance'):
                balance = student.outstanding_balance
                if isinstance(balance, Decimal):
                    result = result.replace('{student.outstanding_balance}', f"KSH {balance:,.2f}")
                else:
                    result = result.replace('{student.outstanding_balance}', f"KSH {balance}")
            else:
                result = result.replace('{student.outstanding_balance}', 'KSH 0.00')
        
        # Invoice placeholders
        invoice = context.get('invoice')
        if invoice:
            if hasattr(invoice, 'total_amount'):
                amount = invoice.total_amount
                if isinstance(amount, Decimal):
                    result = result.replace('{invoice.amount}', f"KSH {amount:,.2f}")
                else:
                    result = result.replace('{invoice.amount}', f"KSH {amount}")
            else:
                result = result.replace('{invoice.amount}', 'KSH 0.00')
            
            if hasattr(invoice, 'due_date') and invoice.due_date:
                result = result.replace('{invoice.due_date}', invoice.due_date.strftime('%d/%m/%Y'))
            else:
                result = result.replace('{invoice.due_date}', '')
            
            if hasattr(invoice, 'term') and invoice.term:
                result = result.replace('{invoice.term}', str(invoice.term))
            else:
                result = result.replace('{invoice.term}', '')
        
        # Attendance placeholders
        attendance = context.get('attendance')
        if attendance:
            if isinstance(attendance, dict):
                result = result.replace('{attendance.present_days}', str(attendance.get('present_days', 0)))
                result = result.replace('{attendance.absent_days}', str(attendance.get('absent_days', 0)))
            else:
                # If attendance is a queryset or model instance, calculate
                result = result.replace('{attendance.present_days}', '0')
                result = result.replace('{attendance.absent_days}', '0')
        
        # Grade placeholders
        grade = context.get('grade')
        if grade:
            if isinstance(grade, dict):
                result = result.replace('{grade.marks}', str(grade.get('marks', '')))
                result = result.replace('{grade.position}', str(grade.get('position', '')))
            else:
                if hasattr(grade, 'marks'):
                    result = result.replace('{grade.marks}', str(grade.marks))
                else:
                    result = result.replace('{grade.marks}', '')
                
                if hasattr(grade, 'position'):
                    result = result.replace('{grade.position}', str(grade.position))
                else:
                    result = result.replace('{grade.position}', '')
        
        # Replace any remaining placeholders with empty string
        import re
        result = re.sub(r'\{[^}]+\}', '', result)
        
        return result
    
    @staticmethod
    def get_available_placeholders():
        """Return list of available placeholders for documentation."""
        return [
            {'key': '{parent.name}', 'description': 'Parent full name'},
            {'key': '{parent.first_name}', 'description': 'Parent first name'},
            {'key': '{student.name}', 'description': 'Student full name'},
            {'key': '{student.admission_number}', 'description': 'Student admission number'},
            {'key': '{student.class}', 'description': 'Student current class'},
            {'key': '{student.outstanding_balance}', 'description': 'Student outstanding balance'},
            {'key': '{invoice.amount}', 'description': 'Invoice amount'},
            {'key': '{invoice.due_date}', 'description': 'Invoice due date'},
            {'key': '{invoice.term}', 'description': 'Invoice term'},
            {'key': '{attendance.present_days}', 'description': 'Days present'},
            {'key': '{attendance.absent_days}', 'description': 'Days absent'},
            {'key': '{grade.marks}', 'description': 'Exam marks'},
            {'key': '{grade.position}', 'description': 'Class position'},
        ]

