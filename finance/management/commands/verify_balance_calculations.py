import csv
from decimal import Decimal, ROUND_HALF_UP
from django.core.management.base import BaseCommand
from django.db.models import Sum, Q
from students.models import Student
from academics.models import Term
from finance.models import Invoice, InvoiceItem, FeeStructure, FeeItem
from core.models import InvoiceStatus, GradeLevel


class Command(BaseCommand):
    help = 'Verify and fix all balance calculations and fee structure matches'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=True,
            help='Show what would be fixed without making changes (default: True)'
        )
        parser.add_argument(
            '--fix-invoice-balances',
            action='store_true',
            help='Fix invoice.balance mismatches'
        )
        parser.add_argument(
            '--fix-student-balances',
            action='store_true',
            help='Fix student.outstanding_balance mismatches'
        )
        parser.add_argument(
            '--fix-total-amounts',
            action='store_true',
            help='Fix invoice.total_amount from invoice items'
        )
        parser.add_argument(
            '--export-report',
            help='Export verification report to CSV file'
        )
        parser.add_argument(
            '--skip-fee-structure-check',
            action='store_true',
            help='Skip fee structure matching verification'
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        fix_invoice_balances = options['fix_invoice_balances']
        fix_student_balances = options['fix_student_balances']
        fix_total_amounts = options['fix_total_amounts']
        export_report = options['export_report']
        skip_fee_structure = options['skip_fee_structure_check']
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write("💰 COMPREHENSIVE BALANCE VERIFICATION")
        self.stdout.write("="*80)
        
        # Get current term
        try:
            current_term = Term.objects.get(is_current=True)
            self.stdout.write(f"\n📅 Current term: {current_term}")
        except Term.DoesNotExist:
            self.stderr.write("❌ Error: No current term found")
            return
        
        # Get all active students with current term invoices
        students = Student.objects.filter(
            status='active',
            invoices__term=current_term,
            invoices__is_active=True
        ).distinct().prefetch_related('invoices', 'invoices__items', 'invoices__fee_structure')
        
        student_count = students.count()
        self.stdout.write(f"👤 Active students with invoices: {student_count}")
        
        results = {
            'total_students': student_count,
            'invoice_balance_mismatches': [],
            'student_balance_mismatches': [],
            'total_amount_mismatches': [],
            'fee_structure_mismatches': [],
            'transport_issues': [],
            'fixes_applied': 0,
            'summary': {
                'total_debt': Decimal('0.00'),
                'total_prepayment': Decimal('0.00'),
                'total_paid': Decimal('0.00'),
                'total_balance': Decimal('0.00')
            }
        }
        
        # Process each student
        for student in students:
            # Get current term invoice
            invoice = student.invoices.filter(
                term=current_term,
                is_active=True
            ).first()
            
            if not invoice:
                self.stderr.write(f"⚠️  No invoice found for {student.admission_number}")
                continue
            
            # Update summary statistics
            results['summary']['total_debt'] += invoice.balance_bf
            results['summary']['total_prepayment'] += invoice.prepayment
            results['summary']['total_paid'] += invoice.amount_paid
            results['summary']['total_balance'] += invoice.balance
            
            # ===== PHASE 1: Verify Invoice Balance =====
            self.verify_invoice_balance(student, invoice, results, dry_run, fix_invoice_balances)
            
            # ===== PHASE 2: Verify Student Outstanding Balance =====
            self.verify_student_balance(student, invoice, results, dry_run, fix_student_balances)
            
            # ===== PHASE 3: Verify Total Amount vs Invoice Items =====
            self.verify_total_amount(student, invoice, results, dry_run, fix_total_amounts)
            
            # ===== PHASE 4: Verify Fee Structure Match =====
            if not skip_fee_structure:
                self.verify_fee_structure_match(student, invoice, current_term, results, dry_run)
            
            # ===== PHASE 5: Verify Transport Fees (if applicable) =====
            if student.uses_school_transport:
                self.verify_transport_fee(student, invoice, current_term, results, dry_run)
        
        # Display results
        self.display_results(results, dry_run, skip_fee_structure)
        
        # Export report if requested
        if export_report:
            self.export_report(results, export_report)
    
    def verify_invoice_balance(self, student, invoice, results, dry_run, fix_invoice_balances):
        """Verify invoice.balance calculation using correct formula."""
        # CORRECT FORMULA (matches Invoice._recalculate_balance):
        #   balance = total_amount + balance_bf + prepayment - amount_paid
        #
        # NOTES:
        # - total_amount is already net of discount_amount, so discount MUST NOT
        #   be subtracted again here.
        # - prepayment is stored as negative when there is credit, so adding it
        #   reduces the balance.
        expected_balance = (
            invoice.total_amount
            + invoice.balance_bf
            + invoice.prepayment
            - invoice.amount_paid
        )
        
        # Round to 2 decimal places for comparison
        expected_balance = expected_balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        actual_balance = invoice.balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        if expected_balance != actual_balance:
            mismatch = {
                'student': student,
                'invoice': invoice,
                'expected_balance': expected_balance,
                'actual_balance': actual_balance,
                'difference': expected_balance - actual_balance,
                'total_amount': invoice.total_amount,
                'balance_bf': invoice.balance_bf,
                'prepayment': invoice.prepayment,
                'amount_paid': invoice.amount_paid,
                'discount_amount': invoice.discount_amount,
                'formula': (
                    f'({invoice.total_amount} + {invoice.balance_bf} + '
                    f'{invoice.prepayment}) - {invoice.amount_paid} = {expected_balance}'
                )
            }
            results['invoice_balance_mismatches'].append(mismatch)
            
            # Fix if requested
            if fix_invoice_balances and not dry_run:
                try:
                    invoice.balance = expected_balance
                    invoice.save(update_fields=['balance'])
                    mismatch['fixed'] = True
                    results['fixes_applied'] += 1
                except Exception as e:
                    mismatch['error'] = str(e)
    
    def verify_student_balance(self, student, invoice, results, dry_run, fix_student_balances):
        """Verify student.outstanding_balance matches invoice.balance."""
        # Since each student has only one invoice for current term
        # outstanding_balance should equal invoice.balance for unpaid invoices
        
        expected_outstanding = invoice.balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        actual_outstanding = student.outstanding_balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # For paid invoices, both should be 0
        if invoice.status == InvoiceStatus.PAID:
            expected_outstanding = Decimal('0.00')
        
        if expected_outstanding != actual_outstanding:
            mismatch = {
                'student': student,
                'invoice': invoice,
                'expected_outstanding': expected_outstanding,
                'actual_outstanding': actual_outstanding,
                'difference': expected_outstanding - actual_outstanding,
                'invoice_status': invoice.status,
                'invoice_balance': invoice.balance
            }
            results['student_balance_mismatches'].append(mismatch)
            
            # Fix if requested
            if fix_student_balances and not dry_run:
                try:
                    student.outstanding_balance = expected_outstanding
                    student.save(update_fields=['outstanding_balance'])
                    mismatch['fixed'] = True
                    results['fixes_applied'] += 1
                except Exception as e:
                    mismatch['error'] = str(e)
    
    def verify_total_amount(self, student, invoice, results, dry_run, fix_total_amounts):
        """Verify invoice.total_amount matches sum of invoice items."""
        # Sum all invoice item net_amounts
        items_total = invoice.items.aggregate(
            total=Sum('net_amount')
        )['total'] or Decimal('0.00')
        
        items_total = items_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        invoice_total = invoice.total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        if items_total != invoice_total:
            mismatch = {
                'student': student,
                'invoice': invoice,
                'expected_total': items_total,
                'actual_total': invoice_total,
                'difference': items_total - invoice_total,
                'item_count': invoice.items.count(),
                'invoice_items': list(invoice.items.values('description', 'amount', 'discount_applied', 'net_amount'))
            }
            results['total_amount_mismatches'].append(mismatch)
            
            # Fix if requested
            if fix_total_amounts and not dry_run:
                try:
                    # Update invoice total amount
                    invoice.total_amount = items_total

                    # Recalculate balance with new total amount using the same
                    # formula as Invoice._recalculate_balance
                    new_balance = (
                        items_total
                        + invoice.balance_bf
                        + invoice.prepayment
                        - invoice.amount_paid
                    )
                    invoice.balance = new_balance

                    invoice.save(update_fields=['total_amount', 'balance'])
                    mismatch['fixed'] = True
                    results['fixes_applied'] += 1
                    
                    # Also update student outstanding balance
                    student.outstanding_balance = invoice.balance
                    student.save(update_fields=['outstanding_balance'])
                    
                except Exception as e:
                    mismatch['error'] = str(e)
    
    def verify_fee_structure_match(self, student, invoice, current_term, results, dry_run):
        """Verify invoice matches correct fee structure for student's grade."""
        
        # Get student's current class and grade level
        if not student.current_class:
            issue = {
                'student': student,
                'issue': 'No current class assigned',
                'grade_level': 'Unknown',
                'expected_fee_structure': 'Cannot determine'
            }
            results['fee_structure_mismatches'].append(issue)
            return
        
        grade_level = student.current_class.grade_level
        
        # Find expected fee structure for this grade and term
        expected_fee_structures = FeeStructure.objects.filter(
            academic_year=current_term.academic_year,
            term=current_term.term,
            grade_levels__contains=[grade_level],  # JSON array contains grade level
            is_active=True
        )
        
        if not expected_fee_structures.exists():
            issue = {
                'student': student,
                'invoice': invoice,
                'grade_level': grade_level,
                'issue': f'No fee structure found for {grade_level} in {current_term}',
                'expected_fee_structure': 'None'
            }
            results['fee_structure_mismatches'].append(issue)
            return
        
        # Get the fee structure linked to invoice (if any)
        invoice_fee_structure = invoice.fee_structure
        
        if not invoice_fee_structure:
            issue = {
                'student': student,
                'invoice': invoice,
                'grade_level': grade_level,
                'issue': 'Invoice has no fee structure linked',
                'expected_fee_structures': [fs.name for fs in expected_fee_structures]
            }
            results['fee_structure_mismatches'].append(issue)
            return
        
        # Check if linked fee structure is valid for student's grade
        if invoice_fee_structure not in expected_fee_structures:
            issue = {
                'student': student,
                'invoice': invoice,
                'grade_level': grade_level,
                'issue': f'Invoice uses fee structure "{invoice_fee_structure.name}" which is not valid for {grade_level}',
                'actual_fee_structure': invoice_fee_structure.name,
                'expected_fee_structures': [fs.name for fs in expected_fee_structures]
            }
            results['fee_structure_mismatches'].append(issue)
        
        # Compare invoice items with fee structure items
        fee_structure_items = invoice_fee_structure.items.all()
        invoice_items = invoice.items.all()
        
        # Check for missing required items
        required_items = fee_structure_items.filter(is_optional=False)
        for req_item in required_items:
            matching_invoice_item = invoice_items.filter(
                description__icontains=req_item.description,
                category=req_item.category
            ).first()
            
            if not matching_invoice_item:
                issue = {
                    'student': student,
                    'invoice': invoice,
                    'grade_level': grade_level,
                    'issue': f'Missing required fee item: {req_item.description} ({req_item.category})',
                    'expected_amount': req_item.amount,
                    'fee_structure': invoice_fee_structure.name
                }
                results['fee_structure_mismatches'].append(issue)
            elif matching_invoice_item.amount != req_item.amount:
                issue = {
                    'student': student,
                    'invoice': invoice,
                    'grade_level': grade_level,
                    'issue': f'Amount mismatch for {req_item.description}',
                    'expected_amount': req_item.amount,
                    'actual_amount': matching_invoice_item.amount,
                    'difference': req_item.amount - matching_invoice_item.amount,
                    'fee_structure': invoice_fee_structure.name
                }
                results['fee_structure_mismatches'].append(issue)
    
    def verify_transport_fee(self, student, invoice, current_term, results, dry_run):
        """Verify transport fee is correctly billed."""
        transport_items = invoice.items.filter(category='transport')
        
        if not transport_items.exists():
            issue = {
                'student': student,
                'invoice': invoice,
                'issue': 'No transport fee item found for transport user',
                'route': student.transport_route.name if student.transport_route else 'None'
            }
            results['transport_issues'].append(issue)
            return
        
        # Check each transport item
        for item in transport_items:
            # Get expected transport fee
            try:
                from transport.models import TransportFee
                transport_fee = TransportFee.objects.get(
                    route=student.transport_route,
                    academic_year=current_term.academic_year,
                    term=current_term.term
                )
                
                # Get trip type from item metadata
                trip_type = item.transport_trip_type or 'full'
                expected_amount = transport_fee.get_amount_for_trip(trip_type)
                
                if item.net_amount != expected_amount:
                    issue = {
                        'student': student,
                        'invoice': invoice,
                        'item': item.description,
                        'expected_amount': expected_amount,
                        'actual_amount': item.net_amount,
                        'trip_type': trip_type,
                        'route': student.transport_route.name,
                        'difference': expected_amount - item.net_amount
                    }
                    results['transport_issues'].append(issue)
                    
            except Exception as e:
                issue = {
                    'student': student,
                    'invoice': invoice,
                    'issue': f'Transport fee verification error: {str(e)}',
                    'route': student.transport_route.name if student.transport_route else 'None'
                }
                results['transport_issues'].append(issue)
    
    def display_results(self, results, dry_run, skip_fee_structure):
        """Display verification results."""
        self.stdout.write("\n" + "="*80)
        self.stdout.write("📊 COMPREHENSIVE VERIFICATION RESULTS")
        self.stdout.write("="*80)
        
        # Summary Statistics
        self.stdout.write(f"\n📈 FINANCIAL SUMMARY:")
        self.stdout.write(f"   Total students: {results['total_students']}")
        self.stdout.write(f"   Total debt (balance_bf): KES {results['summary']['total_debt']:,.2f}")
        self.stdout.write(f"   Total prepayment (credit): KES {results['summary']['total_prepayment']:,.2f}")
        self.stdout.write(f"   Total amount paid: KES {results['summary']['total_paid']:,.2f}")
        self.stdout.write(f"   Total outstanding balance: KES {results['summary']['total_balance']:,.2f}")
        
        # Invoice Balance Mismatches
        self.stdout.write(f"\n📄 INVOICE BALANCE CALCULATION:")
        self.stdout.write(f"   Mismatches: {len(results['invoice_balance_mismatches'])}")
        
        if results['invoice_balance_mismatches']:
            self.stdout.write(f"\n   🔍 Sample mismatches:")
            for i, mismatch in enumerate(results['invoice_balance_mismatches'][:3], 1):
                student = mismatch['student']
                self.stdout.write(f"   {i}. {student.admission_number} - {student.full_name}")
                self.stdout.write(f"      Formula: {mismatch['formula']}")
                self.stdout.write(f"      Expected: KES {mismatch['expected_balance']:,.2f}")
                self.stdout.write(f"      Actual: KES {mismatch['actual_balance']:,.2f}")
                self.stdout.write(f"      Difference: KES {mismatch['difference']:,.2f}")
                if mismatch.get('fixed'):
                    self.stdout.write(f"      ✅ FIXED")
        
        # Student Balance Mismatches
        self.stdout.write(f"\n👤 STUDENT OUTSTANDING BALANCE:")
        self.stdout.write(f"   Mismatches: {len(results['student_balance_mismatches'])}")
        
        if results['student_balance_mismatches']:
            self.stdout.write(f"\n   🔍 Sample mismatches:")
            for i, mismatch in enumerate(results['student_balance_mismatches'][:3], 1):
                student = mismatch['student']
                self.stdout.write(f"   {i}. {student.admission_number} - {student.full_name}")
                self.stdout.write(f"      Expected: KES {mismatch['expected_outstanding']:,.2f}")
                self.stdout.write(f"      Actual: KES {mismatch['actual_outstanding']:,.2f}")
                self.stdout.write(f"      Invoice Status: {mismatch['invoice_status']}")
                if mismatch.get('fixed'):
                    self.stdout.write(f"      ✅ FIXED")
        
        # Total Amount Mismatches
        self.stdout.write(f"\n💰 INVOICE TOTAL AMOUNT:")
        self.stdout.write(f"   Mismatches: {len(results['total_amount_mismatches'])}")
        
        if results['total_amount_mismatches']:
            self.stdout.write(f"\n   🔍 Sample mismatches:")
            for i, mismatch in enumerate(results['total_amount_mismatches'][:3], 1):
                student = mismatch['student']
                self.stdout.write(f"   {i}. {student.admission_number} - {student.full_name}")
                self.stdout.write(f"      Expected (sum of items): KES {mismatch['expected_total']:,.2f}")
                self.stdout.write(f"      Actual (total_amount): KES {mismatch['actual_total']:,.2f}")
                self.stdout.write(f"      Items: {mismatch['item_count']}")
                if mismatch.get('fixed'):
                    self.stdout.write(f"      ✅ FIXED")
        
        # Fee Structure Mismatches
        if not skip_fee_structure:
            self.stdout.write(f"\n🏫 FEE STRUCTURE MATCH:")
            self.stdout.write(f"   Issues: {len(results['fee_structure_mismatches'])}")
            
            if results['fee_structure_mismatches']:
                self.stdout.write(f"\n   🔍 Sample issues:")
                for i, issue in enumerate(results['fee_structure_mismatches'][:3], 1):
                    self.stdout.write(f"   {i}. {issue['student'].admission_number}: {issue['issue']}")
                    if 'expected_amount' in issue:
                        self.stdout.write(f"      Expected: KES {issue['expected_amount']:,.2f}")
                        self.stdout.write(f"      Actual: KES {issue.get('actual_amount', 0):,.2f}")
        
        # Transport Issues
        if results['transport_issues']:
            self.stdout.write(f"\n🚌 TRANSPORT FEE CHECK:")
            self.stdout.write(f"   Issues: {len(results['transport_issues'])}")
            for i, issue in enumerate(results['transport_issues'][:2], 1):
                self.stdout.write(f"   {i}. {issue['student'].admission_number}: {issue['issue']}")
        
        # Overall Status
        total_issues = (
            len(results['invoice_balance_mismatches']) +
            len(results['student_balance_mismatches']) +
            len(results['total_amount_mismatches']) +
            len(results.get('fee_structure_mismatches', [])) +
            len(results['transport_issues'])
        )
        
        if total_issues == 0:
            self.stdout.write("\n✅ SUCCESS: All verifications passed!")
        else:
            error_rate = (total_issues / results['total_students']) * 100
            self.stdout.write(f"\n⚠️  FOUND {total_issues} ISSUES ({error_rate:.1f}% of students)")
        
        if dry_run:
            self.stdout.write(f"\n🔍 DRY RUN: No changes were made. Use fix flags to apply changes.")
        
        if results.get('fixes_applied', 0) > 0:
            self.stdout.write(f"\n🔧 APPLIED {results['fixes_applied']} FIXES")
        
        self.stdout.write("\n" + "="*80)
    
    def export_report(self, results, export_path):
        """Export detailed report to CSV."""
        with open(export_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow([
                'Category',
                'Admission Number',
                'Student Name',
                'Invoice Number',
                'Issue',
                'Expected Value',
                'Actual Value',
                'Difference',
                'Details',
                'Fixed',
                'Error'
            ])
            
            # Write invoice balance mismatches
            for mismatch in results['invoice_balance_mismatches']:
                writer.writerow([
                    'Invoice Balance',
                    mismatch['student'].admission_number,
                    mismatch['student'].full_name,
                    mismatch['invoice'].invoice_number,
                    'Balance calculation mismatch',
                    mismatch['expected_balance'],
                    mismatch['actual_balance'],
                    mismatch['difference'],
                    mismatch.get('formula', ''),
                    mismatch.get('fixed', False),
                    mismatch.get('error', '')
                ])
            
            # Write student balance mismatches
            for mismatch in results['student_balance_mismatches']:
                writer.writerow([
                    'Student Balance',
                    mismatch['student'].admission_number,
                    mismatch['student'].full_name,
                    mismatch['invoice'].invoice_number,
                    'Outstanding balance mismatch',
                    mismatch['expected_outstanding'],
                    mismatch['actual_outstanding'],
                    mismatch['difference'],
                    f"Invoice Status: {mismatch['invoice_status']}",
                    mismatch.get('fixed', False),
                    mismatch.get('error', '')
                ])
            
            # Write total amount mismatches
            for mismatch in results['total_amount_mismatches']:
                writer.writerow([
                    'Total Amount',
                    mismatch['student'].admission_number,
                    mismatch['student'].full_name,
                    mismatch['invoice'].invoice_number,
                    'Total amount mismatch',
                    mismatch['expected_total'],
                    mismatch['actual_total'],
                    mismatch['difference'],
                    f"Items: {mismatch['item_count']}",
                    mismatch.get('fixed', False),
                    mismatch.get('error', '')
                ])
            
            # Write fee structure mismatches
            for issue in results.get('fee_structure_mismatches', []):
                writer.writerow([
                    'Fee Structure',
                    issue['student'].admission_number,
                    issue['student'].full_name,
                    issue.get('invoice', Invoice()).invoice_number if 'invoice' in issue else 'N/A',
                    issue.get('issue', ''),
                    issue.get('expected_amount', ''),
                    issue.get('actual_amount', ''),
                    issue.get('difference', ''),
                    f"Grade: {issue.get('grade_level', '')}",
                    False,  # No auto-fix for fee structure
                    ''
                ])
            
            # Write transport issues
            for issue in results.get('transport_issues', []):
                writer.writerow([
                    'Transport Fee',
                    issue['student'].admission_number,
                    issue['student'].full_name,
                    issue.get('invoice', Invoice()).invoice_number if 'invoice' in issue else 'N/A',
                    issue.get('issue', ''),
                    issue.get('expected_amount', ''),
                    issue.get('actual_amount', ''),
                    issue.get('difference', ''),
                    f"Route: {issue.get('route', '')}",
                    False,  # No auto-fix for transport
                    ''
                ])
        
        self.stdout.write(f"\n💾 Report exported to: {export_path}")
        self.stdout.write(f"   Total issues logged: {len(results['invoice_balance_mismatches']) + len(results['student_balance_mismatches']) + len(results['total_amount_mismatches']) + len(results.get('fee_structure_mismatches', [])) + len(results.get('transport_issues', []))}")