import csv
import os
import re
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db.models import Q
from students.models import Student
from academics.models import Term
from finance.models import Invoice
from core.models import InvoiceStatus

class Command(BaseCommand):
    help = 'Verify Excel balance data against database invoices for active students'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-path',
            default='balances-2col.csv',
            help='Path to CSV file (default: balances-2col.csv)'
        )
        parser.add_argument(
            '--summary-only',
            action='store_true',
            help='Only show summary, not individual records'
        )
        parser.add_argument(
            '--export-mismatches',
            help='Export mismatches to CSV file'
        )
        parser.add_argument(
            '--fix-mismatches',
            action='store_true',
            help='Fix mismatches by updating database (use with caution!)'
        )
    
    def handle(self, *args, **options):
        csv_path = options['csv_path']
        summary_only = options['summary_only']
        export_path = options['export_mismatches']
        fix_mismatches = options['fix_mismatches']
        
        self.stdout.write(f"📊 Starting Excel balance verification...")
        self.stdout.write(f"📁 Reading CSV file: {csv_path}")
        
        # Check if file exists
        if not os.path.exists(csv_path):
            self.stderr.write(f"❌ Error: CSV file not found at {csv_path}")
            return
        
        # Load Excel/CSV data
        excel_data = self.load_csv_data(csv_path)
        self.stdout.write(f"📈 Loaded {len(excel_data)} records from CSV")
        
        # Get current term
        try:
            current_term = Term.objects.get(is_current=True)
            self.stdout.write(f"📚 Current term: {current_term}")
        except Term.DoesNotExist:
            self.stderr.write("❌ Error: No current term found. Please set a current term.")
            return
        except Term.MultipleObjectsReturned:
            self.stderr.write("❌ Error: Multiple current terms found. Please fix.")
            return
        
        # Initialize counters
        results = {
            'total_excel_records': len(excel_data),
            'active_students_found': 0,
            'active_students_not_found': 0,
            'invoices_found': 0,
            'invoices_not_found': 0,
            'matches': 0,
            'mismatches': 0,
            'balance_matches': 0,
            'prepayment_matches': 0,
            'zero_matches': 0,
            'fixes_applied': 0,
            'details': []
        }
        
        # Process each student
        for admission_number, excel_value in excel_data.items():
            result = self.check_student_balance(
                admission_number, 
                excel_value, 
                current_term
            )
            
            results['details'].append(result)
            
            if result['student_found']:
                results['active_students_found'] += 1
                if result['invoice_found']:
                    results['invoices_found'] += 1
                    if result['match']:
                        results['matches'] += 1
                        if excel_value > 0:
                            results['balance_matches'] += 1
                        elif excel_value < 0:
                            results['prepayment_matches'] += 1
                        else:
                            results['zero_matches'] += 1
                    else:
                        results['mismatches'] += 1
                        
                        # Fix mismatches if requested
                        if fix_mismatches and result['invoice']:
                            fix_result = self.fix_mismatch(result['invoice'], excel_value)
                            if fix_result:
                                results['fixes_applied'] += 1
                                self.stdout.write(f"✅ FIXED: {admission_number}")
                else:
                    results['invoices_not_found'] += 1
            else:
                results['active_students_not_found'] += 1
        
        # Display results
        self.display_summary(results)
        
        if not summary_only:
            self.display_detailed_results(results)
        
        if export_path:
            self.export_mismatches(results, export_path)
        
        if fix_mismatches:
            self.stdout.write(f"\n🔧 Applied {results['fixes_applied']} fixes to database")
    
    def parse_net_value(self, value_str):
        """
        Parse net_value string to Decimal.
        Handles:
        - "51,500" → 51500 (positive)
        - "(300)" → -300 (negative)
        - "-" or empty → 0
        - "Ksh 1,000" → 1000 (strips Ksh)
        """
        if not value_str or value_str.strip() == '-':
            return Decimal('0.00')
        
        # Remove any currency symbols and spaces
        cleaned = str(value_str).strip()
        
        # Remove "Ksh", "Ksh.", "KES", etc.
        cleaned = re.sub(r'(?i)\b(ksh|kes|k\.?sh\.?)\s*', '', cleaned)
        
        # Remove parentheses for negative numbers
        is_negative = False
        if cleaned.startswith('(') and cleaned.endswith(')'):
            is_negative = True
            cleaned = cleaned[1:-1]  # Remove parentheses
        
        # Remove commas
        cleaned = cleaned.replace(',', '')
        
        # Remove any other non-numeric characters except decimal point and minus
        cleaned = re.sub(r'[^\d.-]', '', cleaned)
        
        # Handle empty after cleaning
        if not cleaned or cleaned == '.' or cleaned == '-':
            return Decimal('0.00')
        
        try:
            value = Decimal(cleaned)
            if is_negative:
                value = -value
            return value
        except:
            self.stdout.write(f"⚠️  Warning: Could not parse value '{value_str}' → '{cleaned}'")
            return Decimal('0.00')
    
    def load_csv_data(self, csv_path):
        """Load CSV data into dictionary {admission_number: net_value}"""
        data = {}
        
        with open(csv_path, 'r', encoding='utf-8-sig') as csvfile:
            # Try to detect delimiter
            sample = csvfile.read(1024)
            csvfile.seek(0)
            
            has_header = csv.Sniffer().has_header(sample)
            delimiter = csv.Sniffer().sniff(sample).delimiter
            
            self.stdout.write(f"📖 CSV delimiter: '{delimiter}', Has header: {has_header}")
            
            reader = csv.DictReader(csvfile, delimiter=delimiter)
            
            # Handle different possible column names
            fieldnames = reader.fieldnames
            
            if not fieldnames:
                self.stderr.write("❌ Error: CSV has no columns")
                return data
            
            # Try to find admission number column
            admission_col = None
            value_col = None
            
            for col in fieldnames:
                col_lower = col.lower()
                if 'admission' in col_lower or 'adm' in col_lower:
                    admission_col = col
                elif 'net' in col_lower or 'value' in col_lower or 'balance' in col_lower or 'prepayment' in col_lower:
                    value_col = col
            
            if not admission_col:
                admission_col = fieldnames[0]
            if not value_col:
                value_col = fieldnames[-1]
            
            self.stdout.write(f"📊 Using columns: '{admission_col}' and '{value_col}'")
            
            for row_num, row in enumerate(reader, start=1):
                if admission_col not in row or value_col not in row:
                    self.stderr.write(f"⚠️  Warning: Row {row_num} missing columns")
                    continue
                
                admission_number = str(row[admission_col]).strip()
                value_str = str(row[value_col]).strip()
                
                # Skip empty rows
                if not admission_number:
                    continue
                
                # Clean admission number - handle PWA/xxxx/ format
                if admission_number.startswith('PWA/'):
                    # Remove slashes: PWA/2747/ → PWA2747
                    admission_number = admission_number.replace('PWA/', 'PWA').rstrip('/')
                elif admission_number.startswith('PWA'):
                    admission_number = admission_number.strip()
                
                # Parse the value
                value = self.parse_net_value(value_str)
                
                if admission_number in data:
                    self.stderr.write(f"⚠️  Warning: Duplicate admission number: {admission_number}")
                
                data[admission_number] = value
        
        return data
    
    def check_student_balance(self, admission_number, excel_value, current_term):
        """Check if student's Excel value matches their invoice."""
        result = {
            'admission_number': admission_number,
            'excel_value': excel_value,
            'excel_type': 'Balance B/F (+ve)' if excel_value > 0 else 
                         'Prepayment (-ve)' if excel_value < 0 else 'Zero',
            'student_found': False,
            'invoice_found': False,
            'match': False,
            'details': '',
            'student_status': '',
            'invoice_id': None,
            'invoice': None,
            'invoice_balance_bf': Decimal('0.00'),
            'invoice_prepayment': Decimal('0.00'),
            'invoice_total': Decimal('0.00'),
            'invoice_status': '',
        }
        
        try:
            # Find student - try exact match first
            student = Student.objects.get(
                admission_number=admission_number,
                status='active'
            )
            result['student_found'] = True
            result['student_status'] = student.status
            
            # Find invoice for current term
            invoice = Invoice.objects.filter(
                student=student,
                term=current_term,
                is_active=True
            ).first()
            
            if invoice:
                result['invoice_found'] = True
                result['invoice_id'] = invoice.id
                result['invoice'] = invoice
                result['invoice_balance_bf'] = invoice.balance_bf
                result['invoice_prepayment'] = invoice.prepayment
                result['invoice_total'] = invoice.total_amount
                result['invoice_status'] = invoice.status
                
                # Check for match based on Excel value
                if excel_value > 0:
                    # Should be balance_bf
                    if (invoice.balance_bf == excel_value and 
                        invoice.prepayment == Decimal('0.00')):
                        result['match'] = True
                        result['details'] = f"✅ MATCH: Balance B/F = KES {excel_value:,.2f}"
                    else:
                        result['match'] = False
                        if invoice.prepayment > 0:
                            result['details'] = f"❌ MISMATCH: Expected balance_bf KES {excel_value:,.2f}, found prepayment KES {invoice.prepayment:,.2f} and balance_bf KES {invoice.balance_bf:,.2f}"
                        else:
                            result['details'] = f"❌ MISMATCH: Expected balance_bf KES {excel_value:,.2f}, found balance_bf KES {invoice.balance_bf:,.2f}"
                
                elif excel_value < 0:
                    # Should be prepayment (positive value in DB)
                    expected_prepayment = abs(excel_value)
                    if (invoice.prepayment == expected_prepayment and 
                        invoice.balance_bf == Decimal('0.00')):
                        result['match'] = True
                        result['details'] = f"✅ MATCH: Prepayment = KES {expected_prepayment:,.2f}"
                    else:
                        result['match'] = False
                        if invoice.balance_bf > 0:
                            result['details'] = f"❌ MISMATCH: Expected prepayment KES {expected_prepayment:,.2f}, found balance_bf KES {invoice.balance_bf:,.2f} and prepayment KES {invoice.prepayment:,.2f}"
                        else:
                            result['details'] = f"❌ MISMATCH: Expected prepayment KES {expected_prepayment:,.2f}, found prepayment KES {invoice.prepayment:,.2f}"
                
                else:
                    # Should be zero for both
                    if (invoice.balance_bf == Decimal('0.00') and 
                        invoice.prepayment == Decimal('0.00')):
                        result['match'] = True
                        result['details'] = f"✅ MATCH: Zero balance (no prepayment or balance_bf)"
                    else:
                        result['match'] = False
                        result['details'] = f"❌ MISMATCH: Expected zero, found balance_bf KES {invoice.balance_bf:,.2f} and prepayment KES {invoice.prepayment:,.2f}"
            
            else:
                result['invoice_found'] = False
                result['details'] = f"⚠️  WARNING: No invoice found for current term"
        
        except Student.DoesNotExist:
            # Try alternative formats
            try:
                # Try without trailing slash
                clean_adm = admission_number.rstrip('/')
                student = Student.objects.get(
                    admission_number=clean_adm,
                    status='active'
                )
                result['student_found'] = True
                result['student_status'] = student.status
                result['details'] = f"⚠️  Found with cleaned admission number: {clean_adm}"
                
                # Try to find invoice
                invoice = Invoice.objects.filter(
                    student=student,
                    term=current_term,
                    is_active=True
                ).first()
                
                if invoice:
                    result['invoice_found'] = True
                    result['invoice_id'] = invoice.id
                    result['invoice'] = invoice
                    result['invoice_balance_bf'] = invoice.balance_bf
                    result['invoice_prepayment'] = invoice.prepayment
                    result['invoice_status'] = invoice.status
                    
                    # Check match (same logic as above)
                    if excel_value > 0:
                        if (invoice.balance_bf == excel_value and 
                            invoice.prepayment == Decimal('0.00')):
                            result['match'] = True
                            result['details'] = f"✅ MATCH: Balance B/F = KES {excel_value:,.2f}"
                        else:
                            result['match'] = False
                            result['details'] = f"❌ MISMATCH: Expected balance_bf KES {excel_value:,.2f}, found balance_bf KES {invoice.balance_bf:,.2f}, prepayment KES {invoice.prepayment:,.2f}"
                    elif excel_value < 0:
                        expected_prepayment = abs(excel_value)
                        if (invoice.prepayment == expected_prepayment and 
                            invoice.balance_bf == Decimal('0.00')):
                            result['match'] = True
                            result['details'] = f"✅ MATCH: Prepayment = KES {expected_prepayment:,.2f}"
                        else:
                            result['match'] = False
                            result['details'] = f"❌ MISMATCH: Expected prepayment KES {expected_prepayment:,.2f}, found prepayment KES {invoice.prepayment:,.2f}, balance_bf KES {invoice.balance_bf:,.2f}"
                    else:
                        if (invoice.balance_bf == Decimal('0.00') and 
                            invoice.prepayment == Decimal('0.00')):
                            result['match'] = True
                            result['details'] = f"✅ MATCH: Zero balance"
                        else:
                            result['match'] = False
                            result['details'] = f"❌ MISMATCH: Expected zero, found balance_bf KES {invoice.balance_bf:,.2f}, prepayment KES {invoice.prepayment:,.2f}"
                else:
                    result['invoice_found'] = False
                    result['details'] = f"⚠️  Found student but no invoice for current term"
                    
            except Student.DoesNotExist:
                result['student_found'] = False
                result['details'] = f"❌ ERROR: Student not found or not active (tried: {admission_number})"
            except Student.MultipleObjectsReturned:
                result['student_found'] = False
                result['details'] = f"❌ ERROR: Multiple students with admission number {admission_number}"
        
        return result
    
    def fix_mismatch(self, invoice, excel_value):
        """Fix a mismatch by updating the invoice."""
        try:
            if excel_value > 0:
                invoice.balance_bf = excel_value
                invoice.prepayment = Decimal('0.00')
                invoice.save(update_fields=['balance_bf', 'prepayment'])
                return True
            elif excel_value < 0:
                invoice.prepayment = abs(excel_value)
                invoice.balance_bf = Decimal('0.00')
                invoice.save(update_fields=['balance_bf', 'prepayment'])
                return True
            else:
                invoice.balance_bf = Decimal('0.00')
                invoice.prepayment = Decimal('0.00')
                invoice.save(update_fields=['balance_bf', 'prepayment'])
                return True
        except Exception as e:
            self.stderr.write(f"❌ Error fixing invoice {invoice.id}: {e}")
            return False
    
    def display_summary(self, results):
        """Display summary of verification results."""
        self.stdout.write("\n" + "="*80)
        self.stdout.write("📊 VERIFICATION SUMMARY")
        self.stdout.write("="*80)
        
        self.stdout.write(f"📈 Total records in Excel: {results['total_excel_records']}")
        self.stdout.write(f"👤 Active students found: {results['active_students_found']}")
        self.stdout.write(f"❌ Active students not found: {results['active_students_not_found']}")
        self.stdout.write("")
        self.stdout.write(f"🧾 Invoices found for current term: {results['invoices_found']}")
        self.stdout.write(f"⚠️  Invoices not found: {results['invoices_not_found']}")
        self.stdout.write("")
        self.stdout.write(f"✅ MATCHES: {results['matches']}")
        self.stdout.write(f"  ├─ Balance B/F matches: {results['balance_matches']}")
        self.stdout.write(f"  ├─ Prepayment matches: {results['prepayment_matches']}")
        self.stdout.write(f"  └─ Zero matches: {results['zero_matches']}")
        self.stdout.write(f"❌ MISMATCHES: {results['mismatches']}")
        
        if results['invoices_found'] > 0:
            match_rate = (results['matches'] / results['invoices_found']) * 100
            self.stdout.write(f"📈 Match rate: {match_rate:.1f}%")
        
        self.stdout.write("="*80 + "\n")
    
    def display_detailed_results(self, results):
        """Display detailed results for each student."""
        self.stdout.write("\n" + "="*80)
        self.stdout.write("📋 DETAILED RESULTS")
        self.stdout.write("="*80)
        
        # Sort by: mismatches first, then by admission number
        details = sorted(results['details'], key=lambda x: (not x['match'], x['admission_number']))
        
        for detail in details:
            if not detail['student_found']:
                self.stdout.write(f"{detail['admission_number']}: {detail['details']}")
            elif not detail['invoice_found']:
                self.stdout.write(f"{detail['admission_number']}: {detail['details']}")
            else:
                # Show all details for invoices
                status_symbol = "✅" if detail['match'] else "❌"
                self.stdout.write(f"{status_symbol} {detail['admission_number']}: {detail['details']}")
                if not detail['match']:
                    self.stdout.write(f"    Excel: {detail['excel_type']} = KES {abs(detail['excel_value']):,.2f}")
                    self.stdout.write(f"    Invoice #{detail['invoice_id']}: balance_bf=KES {detail['invoice_balance_bf']:,.2f}, prepayment=KES {detail['invoice_prepayment']:,.2f}")
        
        self.stdout.write("="*80 + "\n")
    
    def export_mismatches(self, results, export_path):
        """Export mismatches to CSV file."""
        mismatches = [d for d in results['details'] if d['invoice_found'] and not d['match']]
        
        if not mismatches:
            self.stdout.write(f"✅ No mismatches to export")
            return
        
        with open(export_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'admission_number',
                'excel_value',
                'excel_type',
                'student_status',
                'invoice_id',
                'invoice_balance_bf',
                'invoice_prepayment',
                'invoice_status',
                'verification_status',
                'details'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for mismatch in mismatches:
                writer.writerow({
                    'admission_number': mismatch['admission_number'],
                    'excel_value': mismatch['excel_value'],
                    'excel_type': mismatch['excel_type'],
                    'student_status': mismatch['student_status'],
                    'invoice_id': mismatch['invoice_id'],
                    'invoice_balance_bf': mismatch['invoice_balance_bf'],
                    'invoice_prepayment': mismatch['invoice_prepayment'],
                    'invoice_status': mismatch['invoice_status'],
                    'verification_status': 'MISMATCH',
                    'details': mismatch['details'].replace('❌ MISMATCH: ', '')
                })
        
        self.stdout.write(f"💾 Exported {len(mismatches)} mismatches to {export_path}")