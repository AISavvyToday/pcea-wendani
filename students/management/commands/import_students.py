# students/management/commands/import_students.py

import re
from decimal import Decimal
from datetime import date
from django.core.management.base import BaseCommand
from django.db import transaction
import pandas as pd

from academics.models import AcademicYear, Term, Class
from students.models import Student, Parent, StudentParent
from finance.models import Invoice
from core.models import GradeLevel, TermChoices


class Command(BaseCommand):
    help = 'Import students from Excel file'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to Excel file')

    def handle(self, *args, **options):
        file_path = options['file_path']
        
        self.stdout.write(self.style.NOTICE(f'Reading {file_path}...'))
        
        # Read Excel file
        df = pd.read_excel(file_path, skiprows=1)
        df.columns = ['Year', 'Admission_No', 'Name', 'Class', 'Contacts', 
                      'Prepayment', 'Balance_BF', 'Current_Balance', 'Total_Balance']
        
        # Clean data
        df = df.dropna(subset=['Admission_No'])
        df['Admission_No'] = df['Admission_No'].astype(str).str.strip()
        df['Name'] = df['Name'].astype(str).str.strip()
        df['Class'] = df['Class'].astype(str).str.strip()
        
        with transaction.atomic():
            # 1. Create Academic Year 2025
            academic_year, created = AcademicYear.objects.get_or_create(
                year=2025,
                defaults={
                    'start_date': date(2025, 1, 6),
                    'end_date': date(2025, 11, 28),
                    'is_current': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS('Created Academic Year 2025'))
            
            # 2. Create Term 3
            term, created = Term.objects.get_or_create(
                academic_year=academic_year,
                term=TermChoices.TERM_3,
                defaults={
                    'start_date': date(2025, 9, 1),
                    'end_date': date(2025, 11, 28),
                    'is_current': True,
                    'fee_deadline': date(2025, 9, 15)
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS('Created Term 3 2025'))
            
            # 3. Create Classes
            class_mapping = self.create_classes(academic_year)
            
            # 4. Import Students
            stats = {
                'students_created': 0,
                'students_updated': 0,
                'parents_created': 0,
                'invoices_created': 0,
            }
            
            for _, row in df.iterrows():
                self.import_student(row, class_mapping, term, stats)
            
            # Print summary
            self.stdout.write(self.style.SUCCESS(f'''
Import Complete!
----------------
Students created: {stats['students_created']}
Students updated: {stats['students_updated']}
Parents created: {stats['parents_created']}
Invoices created: {stats['invoices_created']}
            '''))

    def create_classes(self, academic_year):
        """Create all classes and return mapping."""
        class_config = [
            ('PLAYGROUP', 'pp1', 'Playgroup'),  # Map to PP1 level
            ('PP1', 'pp1', ''),
            ('PP2', 'pp2', ''),
            ('GRADE 1', 'grade_1', ''),
            ('GRADE 2', 'grade_2', ''),
            ('GRADE 3', 'grade_3', ''),
            ('GRADE 4', 'grade_4', ''),
            ('GRADE 5', 'grade_5', ''),
            ('GRADE 6', 'grade_6', ''),
            ('GRADE SEVEN-JSS', 'grade_7', ''),
            ('GRADE EIGHT-JSS', 'grade_8', ''),
            ('GRADE NINE-JSS', 'grade_9', ''),
        ]
        
        mapping = {}
        for excel_name, grade_level, stream in class_config:
            # Determine display name
            if excel_name == 'PLAYGROUP':
                display_name = 'Playgroup'
            elif 'JSS' in excel_name:
                display_name = excel_name.replace('-JSS', ' (JSS)').title()
            else:
                display_name = excel_name.title()
            
            class_obj, created = Class.objects.get_or_create(
                name=display_name,
                academic_year=academic_year,
                defaults={
                    'grade_level': grade_level,
                    'stream': stream,
                    'capacity': 50
                }
            )
            mapping[excel_name] = class_obj
            
            if created:
                self.stdout.write(f'  Created class: {display_name}')
        
        return mapping

    def import_student(self, row, class_mapping, term, stats):
        """Import a single student."""
        admission_no = str(row['Admission_No']).strip()
        full_name = str(row['Name']).strip()
        class_name = str(row['Class']).strip()
        contacts = str(row['Contacts']).strip() if pd.notna(row['Contacts']) else ''
        
        # Parse name
        name_parts = full_name.split()
        if len(name_parts) >= 3:
            first_name = name_parts[0]
            last_name = name_parts[-1]
            middle_name = ' '.join(name_parts[1:-1])
        elif len(name_parts) == 2:
            first_name = name_parts[0]
            last_name = name_parts[1]
            middle_name = ''
        else:
            first_name = full_name
            last_name = ''
            middle_name = ''
        
        # Get class
        class_obj = class_mapping.get(class_name)
        if not class_obj:
            self.stdout.write(self.style.WARNING(f'  Unknown class: {class_name} for {admission_no}'))
            return
        
        # Create or update student
        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                'first_name': first_name.title(),
                'middle_name': middle_name.title(),
                'last_name': last_name.title(),
                'current_class': class_obj,
                'admission_date': date(2025, 1, 6),  # Default admission date
                'date_of_birth': date(2015, 1, 1),  # Placeholder - update later
                'gender': 'M',  # Placeholder - update later
                'status': 'active',
            }
        )
        
        if created:
            stats['students_created'] += 1
        else:
            stats['students_updated'] += 1
        
        # Create parent from contacts
        if contacts and contacts != '254' and contacts != 'nan':
            self.create_parent_from_contacts(student, contacts, stats)
        
        # Create invoice with balances
        prepayment = Decimal(str(row['Prepayment'] or 0))
        balance_bf = Decimal(str(row['Balance_BF'] or 0))
        current_balance = Decimal(str(row['Current_Balance'] or 0))
        total_balance = Decimal(str(row['Total_Balance'] or 0))
        
        invoice, created = Invoice.objects.update_or_create(
            student=student,
            term=term,
            defaults={
                'subtotal': current_balance + balance_bf,
                'total_amount': current_balance + balance_bf,
                'balance_bf': balance_bf,
                'prepayment': prepayment,
                'amount_paid': (current_balance + balance_bf) - total_balance + prepayment,
                'balance': total_balance,
                'status': 'paid' if total_balance <= 0 else 'partially_paid' if prepayment > 0 or balance_bf != total_balance else 'sent',
                'issue_date': date(2025, 9, 1),
                'due_date': date(2025, 9, 15),
            }
        )
        
        if created:
            stats['invoices_created'] += 1

    def create_parent_from_contacts(self, student, contacts, stats):
        """Create parent record from contact string."""
        # Extract phone numbers
        phone_pattern = r'0\d{9}|\d{9}'
        phones = re.findall(phone_pattern, contacts)
        
        if not phones:
            return
        
        # Format primary phone
        primary_phone = phones[0]
        if len(primary_phone) == 9:
            primary_phone = '0' + primary_phone
        primary_phone = '+254' + primary_phone[1:]  # Convert to international format
        
        # Check if parent with this phone exists
        parent = Parent.objects.filter(phone_primary=primary_phone).first()
        
        if not parent:
            # Create new parent
            parent = Parent.objects.create(
                first_name=student.last_name,  # Use student's last name as parent's first name (placeholder)
                last_name='(Parent)',
                phone_primary=primary_phone,
                phone_secondary='+254' + phones[1][1:] if len(phones) > 1 else '',
                relationship='guardian',
            )
            stats['parents_created'] += 1
        
        # Link parent to student if not already linked
        StudentParent.objects.get_or_create(
            student=student,
            parent=parent,
            defaults={
                'relationship': 'guardian',
                'is_primary': True,
                'receives_notifications': True,
            }
        )