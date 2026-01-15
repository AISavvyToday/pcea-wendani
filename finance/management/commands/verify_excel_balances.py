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
    help = 'Complete verification of Excel balance data against all active students'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-path',
            default='balances-2col.csv',
            help='Path to CSV file (default: balances-2col.csv)'
        )
        parser.add_argument(
            '--fix-all',
            action='store_true',
            help='Fix all mismatches and create missing invoices (use with caution!)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes'
        )
        parser.add_argument(
            '--export-report',
            help='Export full report to CSV file'
        )
    
    def handle(self, *args, **options):
        csv_path = options['csv_path']
        fix_all = options['fix_all']
        dry_run = options['dry_run']
        export_report = options['export_report']
        
        self.stdout.write("\n" + "="*100)
        self.stdout.write("🔍 COMPLETE EXCEL BALANCE VERIFICATION")
        self.stdout.write("="*100)
        
        # Check if file exists
        if not os.path.exists(csv_path):
            self.stderr.write(f"❌ Error: CSV file not found at {csv_path}")
            return
        
        # Step 1: Load and parse CSV data
        self.stdout.write(f"\n📁 STEP 1: Loading CSV file: {csv_path}")
        excel_data, csv_issues = self.load_csv_data(csv_path)
        self.stdout.write(f"   ✓ Loaded {len(excel_data)} records from CSV")
        
        # Step 2: Get all active students from database
        self.stdout.write(f"\n📊 STEP 2: Querying database for all active students")
        all_active_students = Student.objects.filter(status='active').order_by('admission_number')
        db_student_count = all_active_students.count()
        self.stdout.write(f"   ✓ Found {db_student_count} active students in database")
        
        # Step 3: Get current term
        try:
            current_term = Term.objects.get(is_current=True)
            self.stdout.write(f"   ✓ Current term: {current_term}")
        except Term.DoesNotExist:
            self.stderr.write("❌ Error: No current term found. Please set a current term.")
            return
        except Term.MultipleObjectsReturned:
            self.stderr.write("❌ Error: Multiple current terms found. Please fix.")
            return
        
        # Step 4: Match CSV data with database students
        self.stdout.write(f"\n🔗 STEP 3: Matching CSV admission numbers with database")
        matched_students = []
        unmatched_csv_entries = []
        unmatched_db_students = []
        
        # Build lookup dictionaries
        db_students_by_adm = {}
        for student in all_active_students:
            # Store with and without slashes for flexible lookup
            adm_clean = student.admission_number.replace('/', '').strip()
            db_students_by_adm[student.admission_number] = student
            db_students_by_adm[adm_clean] = student
        
        # Try to match each CSV entry
        for csv_adm, csv_value in excel_data.items():
            student = None
            
            # Try multiple formats for lookup
            lookup_variants = [
                csv_adm,  # Original
                csv_adm.replace('PWA/', 'PWA').replace('/', ''),  # Remove slashes
                csv_adm.replace('PWA', 'PWA/') + '/' if not csv_adm.endswith('/') else csv_adm,  # Add slash
            ]
            
            for variant in lookup_variants:
                if variant in db_students_by_adm:
                    student = db_students_by_adm[variant]
                    break
            
            if student:
                matched_students.append({
                    'csv_admission': csv_adm,
                    'db_admission': student.admission_number,
                    'student': student,
                    'excel_value': csv_value,
                    'match_type': 'exact' if csv_adm in db_students_by_adm else 'format_adjusted'
                })
            else:
                unmatched_csv_entries.append({
                    'admission_number': csv_adm,
                    'excel_value': csv_value,
                    'reason': 'Not found in database or not active'
                })
        
        # Find database students not in CSV
        db_adm_set = {s.admission_number for s in all_active_students}
        csv_adm_set = {entry['db_admission'] for entry in matched_students}
        unmatched_db_adms = db_adm_set - csv_adm_set
        
        for adm in unmatched_db_adms:
            student = db_students_by_adm[adm]
            unmatched_db_students.append({
                'admission_number': adm,
                'student': student,
                'reason': 'Not found in CSV file'
            })
        
        # Report matching results
        self.stdout.write(f"   ✓ Matched CSV entries: {len(matched_students)}")
        self.stdout.write(f"   ✗ Unmatched CSV entries: {len(unmatched_csv_entries)}")
        self.stdout.write(f"   ✗ Database students not in CSV: {len(unmatched_db_students)}")
        
        if unmatched_csv_entries:
            self.stdout.write(f"\n   🔍 Sample unmatched CSV entries:")
            for entry in unmatched_csv_entries[:10]:
                self.stdout.write(f"      - {entry['admission_number']}: {entry['reason']}")
            if len(unmatched_csv_entries) > 10:
                self.stdout.write(f"      ... and {len(unmatched_csv_entries) - 10} more")
        
        # Step 5: Check invoices for matched students
        self.stdout.write(f"\n🧾 STEP 4: Checking invoices for {len(matched_students)} matched students")
        
        results = {
            'total_students_checked': 0,
            'invoices_found': 0,
            'invoices_created': 0,
            'invoices_missing': 0,
            'matches_perfect': 0,
            'matches_format_adjusted': 0,
            'mismatches': 0,
            'balance_matches': 0,
            'prepayment_matches': 0,
            'zero_matches': 0,
            'fixes_applied': 0,
            'details': [],
            'mismatch_details': [],
            'missing_invoice_details': []
        }
        
        for match in matched_students:
            student = match['student']
            csv_adm = match['csv_admission']
            excel_value = match['excel_value']
            
            # Get or create invoice
            invoice = Invoice.objects.filter(
                student=student,
                term=current_term,
                is_active=True
            ).first()
            
            if invoice:
                results['invoices_found'] += 1
                invoice_status = self.check_invoice_match(invoice, excel_value)
                
                if invoice_status['match']:
                    if match['match_type'] == 'exact':
                        results['matches_perfect'] += 1
                    else:
                        results['matches_format_adjusted'] += 1
                    
                    if excel_value > 0:
                        results['balance_matches'] += 1
                    elif excel_value < 0:
                        results['prepayment_matches'] += 1
                    else:
                        results['zero_matches'] += 1
                else:
                    results['mismatches'] += 1
                    results['mismatch_details'].append({
                        'student': student,
                        'invoice': invoice,
                        'excel_value': excel_value,
                        'expected_balance_bf': excel_value if excel_value > 0 else 0,
                        'expected_prepayment': abs(excel_value) if excel_value < 0 else 0,
                        'actual_balance_bf': invoice.balance_bf,
                        'actual_prepayment': invoice.prepayment,
                        'message': invoice_status['message']
                    })
                
                results['details'].append({
                    'student': student,
                    'invoice': invoice,
                    'excel_value': excel_value,
                    'status': 'MATCH' if invoice_status['match'] else 'MISMATCH',
                    'message': invoice_status['message'],
                    'match_type': match['match_type']
                })
                
                # Fix mismatch if requested
                if fix_all and not dry_run and not invoice_status['match']:
                    fixed = self.fix_invoice_mismatch(invoice, excel_value)
                    if fixed:
                        results['fixes_applied'] += 1
            else:
                results['invoices_missing'] += 1
                results['missing_invoice_details'].append({
                    'student': student,
                    'excel_value': excel_value
                })
                
                # Create invoice if requested
                if fix_all and not dry_run:
                    created = self.create_invoice_for_student(student, current_term, excel_value)
                    if created:
                        results['invoices_created'] += 1
                        results['fixes_applied'] += 1
                
                results['details'].append({
                    'student': student,
                    'invoice': None,
                    'excel_value': excel_value,
                    'status': 'NO_INVOICE',
                    'message': f"No invoice found for current term",
                    'match_type': match['match_type']
                })
            
            results['total_students_checked'] += 1
        
        # Step 6: Process unmatched database students
        self.stdout.write(f"\n📝 STEP 5: Processing {len(unmatched_db_students)} database students not in CSV")
        
        for entry in unmatched_db_students:
            student = entry['student']
            
            # Get or create invoice
            invoice = Invoice.objects.filter(
                student=student,
                term=current_term,
                is_active=True
            ).first()
            
            if not invoice and fix_all and not dry_run:
                # Create invoice with zero balance for students not in CSV
                created = self.create_invoice_for_student(student, current_term, Decimal('0.00'))
                if created:
                    results['invoices_created'] += 1
                    results['fixes_applied'] += 1
        
        # Step 7: Display comprehensive results
        self.display_comprehensive_results(results, dry_run, fix_all)
        
        # Step 8: Export report if requested
        if export_report:
            self.export_comprehensive_report(results, export_report, unmatched_csv_entries, unmatched_db_students)
    
    def parse_net_value(self, value_str):
        """
        Parse net_value string to Decimal.
        Handles: "51,500", "(300)", "-", "Ksh 1,000", etc.
        """
        if not value_str or str(value_str).strip() == '-':
            return Decimal('0.00')
        
        cleaned = str(value_str).strip()
        
        # Remove currency symbols
        cleaned = re.sub(r'(?i)\b(ksh|kes|k\.?sh\.?|usd|eur|gbp)\s*', '', cleaned)
        
        # Check for parentheses (negative)
        is_negative = False
        if cleaned.startswith('(') and cleaned.endswith(')'):
            is_negative = True
            cleaned = cleaned[1:-1]
        
        # Remove commas and any other non-numeric except decimal and minus
        cleaned = cleaned.replace(',', '')
        cleaned = re.sub(r'[^\d.-]', '', cleaned)
        
        if not cleaned or cleaned in ['.', '-']:
            return Decimal('0.00')
        
        try:
            value = Decimal(cleaned)
            return -value if is_negative else value
        except:
            return Decimal('0.00')
    
    def load_csv_data(self, csv_path):
        """Load CSV data and return dictionary of {admission_number: net_value}"""
        data = {}
        issues = []
        
        with open(csv_path, 'r', encoding='utf-8-sig') as csvfile:
            # Detect delimiter and header
            sample = csvfile.read(1024)
            csvfile.seek(0)
            
            try:
                has_header = csv.Sniffer().has_header(sample)
                delimiter = csv.Sniffer().sniff(sample).delimiter
            except:
                delimiter = ','
                has_header = True
            
            reader = csv.DictReader(csvfile, delimiter=delimiter)
            
            if not reader.fieldnames:
                issues.append("CSV has no columns/headers")
                return data, issues
            
            # Find admission number and value columns
            admission_col = None
            value_col = None
            
            for col in reader.fieldnames:
                col_lower = col.lower()
                if any(keyword in col_lower for keyword in ['admission', 'adm', 'number', 'no']):
                    admission_col = col
                elif any(keyword in col_lower for keyword in ['net', 'value', 'balance', 'prepayment', 'bf']):
                    value_col = col
            
            if not admission_col:
                admission_col = reader.fieldnames[0]
            if not value_col:
                value_col = reader.fieldnames[-1]
            
            for row_num, row in enumerate(reader, start=1):
                if admission_col not in row:
                    issues.append(f"Row {row_num}: Missing admission column")
                    continue
                
                admission = str(row[admission_col]).strip()
                value_str = str(row[value_col]).strip() if value_col in row else ''
                
                if not admission:
                    issues.append(f"Row {row_num}: Empty admission number")
                    continue
                
                # Clean admission number
                admission = admission.replace('PWA/', 'PWA').replace('/', '').strip()
                
                # Parse value
                value = self.parse_net_value(value_str)
                
                if admission in data:
                    issues.append(f"Row {row_num}: Duplicate admission number {admission}")
                
                data[admission] = value
        
        return data, issues
    
    def check_invoice_match(self, invoice, excel_value):
        """Check if invoice matches Excel value."""
        result = {
            'match': False,
            'message': ''
        }
        
        if excel_value > 0:
            # Should be balance_bf
            if invoice.balance_bf == excel_value and invoice.prepayment == Decimal('0.00'):
                result['match'] = True
                result['message'] = f"✅ Perfect match: Balance B/F = KES {excel_value:,.2f}"
            else:
                result['match'] = False
                result['message'] = f"❌ Mismatch: Excel expects balance_bf KES {excel_value:,.2f}, but invoice has balance_bf KES {invoice.balance_bf:,.2f}, prepayment KES {invoice.prepayment:,.2f}"
        
        elif excel_value < 0:
            # Should be prepayment
            expected_prepayment = abs(excel_value)
            if invoice.prepayment == expected_prepayment and invoice.balance_bf == Decimal('0.00'):
                result['match'] = True
                result['message'] = f"✅ Perfect match: Prepayment = KES {expected_prepayment:,.2f}"
            else:
                result['match'] = False
                result['message'] = f"❌ Mismatch: Excel expects prepayment KES {expected_prepayment:,.2f}, but invoice has prepayment KES {invoice.prepayment:,.2f}, balance_bf KES {invoice.balance_bf:,.2f}"
        
        else:
            # Should be zero
            if invoice.balance_bf == Decimal('0.00') and invoice.prepayment == Decimal('0.00'):
                result['match'] = True
                result['message'] = f"✅ Perfect match: Zero balance (no prepayment or balance_bf)"
            else:
                result['match'] = False
                result['message'] = f"❌ Mismatch: Excel expects zero, but invoice has balance_bf KES {invoice.balance_bf:,.2f}, prepayment KES {invoice.prepayment:,.2f}"
        
        return result
    
    def fix_invoice_mismatch(self, invoice, excel_value):
        """Fix invoice mismatch by updating balance_bf or prepayment."""
        try:
            if excel_value > 0:
                invoice.balance_bf = excel_value
                invoice.prepayment = Decimal('0.00')
            elif excel_value < 0:
                invoice.prepayment = abs(excel_value)
                invoice.balance_bf = Decimal('0.00')
            else:
                invoice.balance_bf = Decimal('0.00')
                invoice.prepayment = Decimal('0.00')
            
            invoice.save()
            self.stdout.write(f"   🔧 Fixed invoice {invoice.invoice_number} for {invoice.student.admission_number}")
            return True
        except Exception as e:
            self.stderr.write(f"   ❌ Error fixing invoice {invoice.id}: {e}")
            return False
    
    def create_invoice_for_student(self, student, term, excel_value):
        """Create a new invoice for a student."""
        try:
            from finance.services import InvoiceService
            
            # Get fee structure for student's class
            fee_structure = None  # You might need to implement this logic
            
            invoice = InvoiceService.create_invoice_for_student(
                student=student,
                term=term,
                fee_structure=fee_structure,
                created_by=None  # System user
            )
            
            # Set balance_bf or prepayment based on Excel value
            if excel_value > 0:
                invoice.balance_bf = excel_value
            elif excel_value < 0:
                invoice.prepayment = abs(excel_value)
            
            invoice.save()
            self.stdout.write(f"   📄 Created invoice {invoice.invoice_number} for {student.admission_number}")
            return True
        except Exception as e:
            self.stderr.write(f"   ❌ Error creating invoice for {student.admission_number}: {e}")
            return False
    
    def display_comprehensive_results(self, results, dry_run, fix_all):
        """Display comprehensive results."""
        self.stdout.write("\n" + "="*100)
        self.stdout.write("📊 COMPREHENSIVE VERIFICATION RESULTS")
        self.stdout.write("="*100)
        
        # Summary Statistics
        self.stdout.write("\n📈 SUMMARY STATISTICS:")
        self.stdout.write(f"   Total students checked: {results['total_students_checked']}")
        self.stdout.write(f"   Invoices found: {results['invoices_found']}")
        self.stdout.write(f"   Invoices missing: {results['invoices_missing']}")
        self.stdout.write(f"   Invoices created: {results['invoices_created']}")
        self.stdout.write("")
        self.stdout.write(f"   Perfect matches (format and value): {results['matches_perfect']}")
        self.stdout.write(f"   Format-adjusted matches: {results['matches_format_adjusted']}")
        self.stdout.write(f"   Mismatches found: {results['mismatches']}")
        self.stdout.write("")
        self.stdout.write(f"   Balance B/F matches: {results['balance_matches']}")
        self.stdout.write(f"   Prepayment matches: {results['prepayment_matches']}")
        self.stdout.write(f"   Zero balance matches: {results['zero_matches']}")
        
        if fix_all:
            self.stdout.write(f"\n🔧 FIXES APPLIED: {results['fixes_applied']}")
            if dry_run:
                self.stdout.write("   ⚠️  DRY RUN: No actual changes were made")
        
        # Mismatch Details
        if results['mismatch_details']:
            self.stdout.write(f"\n❌ DETAILED MISMATCHES ({len(results['mismatch_details'])}):")
            for i, mismatch in enumerate(results['mismatch_details'][:20], 1):
                student = mismatch['student']
                self.stdout.write(f"   {i}. {student.admission_number} - {student.full_name}")
                self.stdout.write(f"      Excel: {mismatch['message'].split(': ')[1]}")
                self.stdout.write(f"      Expected: balance_bf={mismatch['expected_balance_bf']:,.2f}, prepayment={mismatch['expected_prepayment']:,.2f}")
                self.stdout.write(f"      Actual: balance_bf={mismatch['actual_balance_bf']:,.2f}, prepayment={mismatch['actual_prepayment']:,.2f}")
            
            if len(results['mismatch_details']) > 20:
                self.stdout.write(f"   ... and {len(results['mismatch_details']) - 20} more mismatches")
        
        # Missing Invoice Details
        if results['missing_invoice_details']:
            self.stdout.write(f"\n⚠️  MISSING INVOICES ({len(results['missing_invoice_details'])}):")
            for i, missing in enumerate(results['missing_invoice_details'][:10], 1):
                student = missing['student']
                self.stdout.write(f"   {i}. {student.admission_number} - {student.full_name}")
                if missing['excel_value'] != 0:
                    self.stdout.write(f"      Excel value: KES {missing['excel_value']:,.2f}")
            
            if len(results['missing_invoice_details']) > 10:
                self.stdout.write(f"   ... and {len(results['missing_invoice_details']) - 10} more")
        
        # Calculate percentages
        if results['total_students_checked'] > 0:
            match_rate = ((results['matches_perfect'] + results['matches_format_adjusted']) / 
                         results['total_students_checked']) * 100
            self.stdout.write(f"\n📊 OVERALL MATCH RATE: {match_rate:.1f}%")
        
        self.stdout.write("\n" + "="*100)
    
    def export_comprehensive_report(self, results, export_path, unmatched_csv_entries, unmatched_db_students):
        """Export comprehensive report to CSV."""
        import csv
        
        with open(export_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'admission_number',
                'student_name',
                'status',
                'excel_value',
                'invoice_number',
                'invoice_balance_bf',
                'invoice_prepayment',
                'invoice_status',
                'match_status',
                'message',
                'match_type',
                'notes'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            # Write matched students
            for detail in results['details']:
                student = detail['student']
                invoice = detail['invoice']
                
                writer.writerow({
                    'admission_number': student.admission_number,
                    'student_name': student.full_name,
                    'status': detail['status'],
                    'excel_value': detail['excel_value'],
                    'invoice_number': invoice.invoice_number if invoice else 'NONE',
                    'invoice_balance_bf': invoice.balance_bf if invoice else 0,
                    'invoice_prepayment': invoice.prepayment if invoice else 0,
                    'invoice_status': invoice.status if invoice else 'NONE',
                    'match_status': 'MATCH' if detail.get('status') == 'MATCH' else 'MISMATCH',
                    'message': detail['message'],
                    'match_type': detail.get('match_type', 'exact'),
                    'notes': ''
                })
            
            # Write unmatched CSV entries
            for entry in unmatched_csv_entries:
                writer.writerow({
                    'admission_number': entry['admission_number'],
                    'student_name': 'NOT FOUND',
                    'status': 'UNMATCHED_CSV',
                    'excel_value': entry['excel_value'],
                    'invoice_number': 'NONE',
                    'invoice_balance_bf': 0,
                    'invoice_prepayment': 0,
                    'invoice_status': 'NONE',
                    'match_status': 'NOT_FOUND',
                    'message': entry['reason'],
                    'match_type': 'NONE',
                    'notes': 'Student not found in database or not active'
                })
            
            # Write unmatched database students
            for entry in unmatched_db_students:
                student = entry['student']
                writer.writerow({
                    'admission_number': student.admission_number,
                    'student_name': student.full_name,
                    'status': 'UNMATCHED_DB',
                    'excel_value': 0,
                    'invoice_number': 'NONE',
                    'invoice_balance_bf': 0,
                    'invoice_prepayment': 0,
                    'invoice_status': 'NONE',
                    'match_status': 'NOT_IN_CSV',
                    'message': entry['reason'],
                    'match_type': 'NONE',
                    'notes': 'Student not found in CSV file'
                })
        
        self.stdout.write(f"\n💾 Comprehensive report exported to: {export_path}")
        self.stdout.write(f"   Total records: {len(results['details']) + len(unmatched_csv_entries) + len(unmatched_db_students)}")
