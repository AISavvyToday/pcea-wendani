# payroll/services/payroll_calculator.py
"""
Service for calculating payroll: gross salary, deductions, and net pay.
Implements Kenya-specific tax and deduction calculations.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


class PayrollCalculator:
    """Calculate payroll amounts including deductions and allowances."""
    
    # NHIF brackets (as of 2024 - update as needed)
    NHIF_BRACKETS = [
        (0, 5999, 150),
        (6000, 7999, 300),
        (8000, 11999, 400),
        (12000, 14999, 500),
        (15000, 19999, 600),
        (20000, 24999, 750),
        (25000, 29999, 850),
        (30000, 34999, 900),
        (35000, 39999, 950),
        (40000, 44999, 1000),
        (45000, 49999, 1100),
        (50000, 59999, 1200),
        (60000, 69999, 1300),
        (70000, 79999, 1400),
        (80000, 89999, 1500),
        (90000, 99999, 1600),
        (100000, float('inf'), 1700),
    ]
    
    # NSSF rates
    NSSF_RATE = Decimal('0.06')  # 6% of gross salary
    NSSF_MAX_CONTRIBUTION = Decimal('2160.00')  # Maximum employee contribution
    
    # PAYE tax brackets (Kenya 2024)
    PAYE_BRACKETS = [
        (0, 288000, Decimal('0.10')),  # 10% for first 288,000 per year (24,000 per month)
        (288000, 388000, Decimal('0.25')),  # 25% for next 100,000 per year (8,333 per month)
        (388000, float('inf'), Decimal('0.30')),  # 30% for above 388,000 per year
    ]
    PERSONAL_RELIEF = Decimal('2400.00')  # Monthly personal relief
    
    @staticmethod
    def calculate_nhif(gross_salary):
        """Calculate NHIF deduction based on gross salary brackets."""
        gross = float(gross_salary)
        for min_sal, max_sal, amount in PayrollCalculator.NHIF_BRACKETS:
            if min_sal <= gross <= max_sal:
                return Decimal(str(amount))
        return Decimal('1700.00')  # Default maximum
    
    @staticmethod
    def calculate_nssf(gross_salary):
        """Calculate NSSF deduction (6% of gross, capped at 2160)."""
        employee_contribution = min(
            gross_salary * PayrollCalculator.NSSF_RATE,
            PayrollCalculator.NSSF_MAX_CONTRIBUTION
        )
        employer_contribution = min(
            gross_salary * PayrollCalculator.NSSF_RATE,
            PayrollCalculator.NSSF_MAX_CONTRIBUTION
        )
        return Decimal(str(employee_contribution)), Decimal(str(employer_contribution))
    
    @staticmethod
    def calculate_paye(gross_salary):
        """
        Calculate PAYE (tax) based on Kenya tax brackets.
        Annualizes monthly salary for calculation.
        """
        monthly_gross = gross_salary
        annual_gross = monthly_gross * Decimal('12')
        
        tax = Decimal('0.00')
        remaining = annual_gross
        
        for i, (min_annual, max_annual, rate) in enumerate(PayrollCalculator.PAYE_BRACKETS):
            if remaining <= 0:
                break
            
            if annual_gross > min_annual:
                taxable_in_bracket = min(
                    remaining,
                    (max_annual if max_annual != float('inf') else annual_gross) - min_annual
                )
                if taxable_in_bracket > 0:
                    tax += taxable_in_bracket * rate
                    remaining -= taxable_in_bracket
        
        # Convert annual tax to monthly and apply personal relief
        monthly_tax = (tax / Decimal('12')) - PayrollCalculator.PERSONAL_RELIEF
        
        return max(Decimal('0.00'), monthly_tax)  # Tax cannot be negative
    
    @staticmethod
    def calculate_allowance(allowance, basic_salary):
        """Calculate allowance amount (fixed or percentage of basic)."""
        if allowance.is_percentage:
            return (basic_salary * allowance.percentage) / Decimal('100.00')
        return allowance.amount
    
    @staticmethod
    def calculate_deduction(deduction, gross_salary, basic_salary):
        """Calculate deduction amount based on type."""
        if deduction.is_calculated:
            # Handle calculated deductions (NHIF, NSSF, PAYE)
            if deduction.deduction_type == 'nhif':
                return PayrollCalculator.calculate_nhif(gross_salary)
            elif deduction.deduction_type == 'nssf':
                nssf_emp, _ = PayrollCalculator.calculate_nssf(gross_salary)
                return nssf_emp
            elif deduction.deduction_type == 'paye':
                return PayrollCalculator.calculate_paye(gross_salary)
            else:
                return Decimal('0.00')
        elif deduction.is_percentage:
            return (gross_salary * deduction.percentage) / Decimal('100.00')
        else:
            return deduction.amount
    
    @staticmethod
    def calculate_payroll(staff_salary, allowances_list, deductions_list):
        """
        Calculate complete payroll for a staff member.
        
        Args:
            staff_salary: StaffSalary instance
            allowances_list: List of Allowance instances
            deductions_list: List of Deduction instances
        
        Returns:
            Dictionary with calculated amounts
        """
        basic_salary = staff_salary.salary_structure.basic_salary
        
        # Calculate total allowances
        total_allowances = Decimal('0.00')
        allowance_breakdown = {}
        for allowance in allowances_list:
            amount = PayrollCalculator.calculate_allowance(allowance, basic_salary)
            total_allowances += amount
            allowance_breakdown[allowance.id] = amount
        
        # Gross salary = basic + allowances
        gross_salary = basic_salary + total_allowances
        
        # Calculate deductions
        nhif = Decimal('0.00')
        nssf_employee = Decimal('0.00')
        nssf_employer = Decimal('0.00')
        paye = Decimal('0.00')
        other_deductions = Decimal('0.00')
        deduction_breakdown = {}
        
        for deduction in deductions_list:
            if deduction.deduction_type == 'nhif':
                nhif = PayrollCalculator.calculate_nhif(gross_salary)
                deduction_breakdown[deduction.id] = nhif
            elif deduction.deduction_type == 'nssf':
                nssf_emp, nssf_emp_cont = PayrollCalculator.calculate_nssf(gross_salary)
                nssf_employee = nssf_emp
                nssf_employer = nssf_emp_cont
                deduction_breakdown[deduction.id] = nssf_employee
            elif deduction.deduction_type == 'paye':
                paye = PayrollCalculator.calculate_paye(gross_salary)
                deduction_breakdown[deduction.id] = paye
            else:
                amount = PayrollCalculator.calculate_deduction(deduction, gross_salary, basic_salary)
                other_deductions += amount
                deduction_breakdown[deduction.id] = amount
        
        total_deductions = nhif + nssf_employee + paye + other_deductions
        net_salary = gross_salary - total_deductions
        
        return {
            'basic_salary': basic_salary,
            'total_allowances': total_allowances,
            'gross_salary': gross_salary,
            'nhif': nhif,
            'nssf_employee': nssf_employee,
            'nssf_employer': nssf_employer,
            'paye': paye,
            'other_deductions': other_deductions,
            'total_deductions': total_deductions,
            'net_salary': net_salary,
            'allowance_breakdown': allowance_breakdown,
            'deduction_breakdown': deduction_breakdown,
        }

