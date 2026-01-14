from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from students.models import Student
from pathlib import Path
import pandas as pd


class Command(BaseCommand):
    help = "Import Term 3 2025 balances and set bal_bf_original or prepayment_original"

    def handle(self, *args, **options):
        BASE_DIR = Path(settings.BASE_DIR)

        excel_path = BASE_DIR / "TERM_3_2025_LIST_AND_BALANCES_NO GRADE_9.xlsx"

        if not excel_path.exists():
            self.stderr.write(self.style.ERROR(f"Excel file not found: {excel_path}"))
            return

        self.stdout.write(self.style.WARNING(f"Reading file: {excel_path}"))

        # Try to read the Excel file with headers first
        try:
            df = pd.read_excel(excel_path)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error reading Excel file: {e}"))
            return

        # Check if this looks like a file without headers (first row is data)
        if df.shape[1] > 0 and isinstance(df.columns[0], (int, float)):
            # File likely has no headers, read it again without headers
            df = pd.read_excel(excel_path, header=None)
            
            # Assign column names based on the pattern we see in the error
            # From the error: ['2025', 'PWA/3176/', 'ELLA LUCILLA WANGUI GITONGA', 'GRADE 6', '30500', '7020908960702629888', '12500', '0', '0.1', '-12500']
            # This looks like: Year, Admission#, Name, Grade, Amount?, ID?, Paid?, ?, ?, Balance?
            column_names = [
                'year', 'admission_number', 'student_name', 'grade', 
                'amount_1', 'id_number', 'amount_2', 'zero_1', 'zero_2', 'balance'
            ]
            
            # If we have fewer columns than names, adjust
            if len(column_names) > df.shape[1]:
                column_names = column_names[:df.shape[1]]
            
            df.columns = column_names
            self.stdout.write(self.style.WARNING("File had no headers. Assigned column names based on pattern."))
        
        # Normalize column names if they exist
        df.columns = df.columns.map(lambda c: str(c).strip() if isinstance(c, str) else str(c))
        
        self.stdout.write(self.style.SUCCESS(f"Columns after processing: {list(df.columns)}"))
        
        # Try to identify the admission number column
        admission_col = None
        
        # First check for exact matches in column names
        for col in df.columns:
            col_lower = str(col).lower()
            if any(keyword in col_lower for keyword in ['adm', 'admission', 'student', 'no', 'number']):
                admission_col = col
                break
        
        # If not found, check the data pattern - column that looks like "PWA/3176/"
        if not admission_col:
            for col in df.columns:
                # Sample the first few non-null values
                sample_values = df[col].dropna().head(5).astype(str)
                # Check if any value looks like an admission number (contains slash and numbers)
                if any('/' in val and any(char.isdigit() for char in val) for val in sample_values):
                    admission_col = col
                    self.stdout.write(self.style.WARNING(f"Detected admission column by pattern: {col}"))
                    break
        
        # Try to identify balance column
        balance_col = None
        
        # First check for exact matches
        for col in df.columns:
            col_lower = str(col).lower()
            if any(keyword in col_lower for keyword in ['balance', 'bal', 'total', 'final']):
                balance_col = col
                break
        
        # If not found, look for column with negative/positive numbers
        if not balance_col:
            for col in df.columns:
                try:
                    # Check if column has numeric values and some are negative
                    numeric_values = pd.to_numeric(df[col].head(10), errors='coerce').dropna()
                    if len(numeric_values) > 0:
                        # If we have both positive and negative values, it's likely the balance
                        has_negative = (numeric_values < 0).any()
                        has_positive = (numeric_values > 0).any()
                        if has_negative or has_positive:
                            balance_col = col
                            self.stdout.write(self.style.WARNING(f"Detected balance column by numeric pattern: {col}"))
                            break
                except:
                    continue
        
        if not admission_col:
            self.stderr.write(
                self.style.ERROR(
                    f"Could not detect admission number column. Found columns: {list(df.columns)}"
                ))
            # Show sample of first row to help debug
            self.stdout.write(f"First row sample: {df.iloc[0].to_dict() if len(df) > 0 else 'No data'}")
            return
        
        if not balance_col:
            self.stderr.write(
                self.style.ERROR(
                    f"Could not detect balance column. Found columns: {list(df.columns)}"
                )
            )
            # Show sample of numeric columns
            numeric_cols = []
            for col in df.columns:
                try:
                    if pd.api.types.is_numeric_dtype(df[col]):
                        numeric_cols.append(col)
                except:
                    continue
            self.stdout.write(f"Numeric columns found: {numeric_cols}")
            return
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Using admission column '{admission_col}' and balance column '{balance_col}'"
            )
        )
        
        updated_bf = 0
        updated_prepayment = 0
        skipped = 0
        not_found = 0
        
        with transaction.atomic():
            for index, row in df.iterrows():
                try:
                    admission_number = str(row[admission_col]).strip()
                    
                    if not admission_number or admission_number.lower() == 'nan' or admission_number == 'None':
                        skipped += 1
                        continue
                    
                    # Clean up admission number
                    admission_number = admission_number.strip()
                    
                    # Get balance value
                    balance_value = row[balance_col]
                    
                    # Handle NaN or non-numeric values
                    if pd.isna(balance_value):
                        skipped += 1
                        continue
                    
                    # Convert to numeric
                    try:
                        total_balance = float(balance_value)
                    except (ValueError, TypeError):
                        # Try to clean the string if it's not numeric
                        if isinstance(balance_value, str):
                            # Remove currency symbols, commas, etc.
                            clean_value = ''.join(ch for ch in balance_value if ch.isdigit() or ch == '.' or ch == '-')
                            try:
                                total_balance = float(clean_value)
                            except:
                                self.stderr.write(self.style.WARNING(f"Could not parse balance value '{balance_value}' for {admission_number}"))
                                skipped += 1
                                continue
                        else:
                            skipped += 1
                            continue
                    
                    if total_balance == 0:
                        skipped += 1
                        continue
                    
                    # Try to find student by admission number
                    students = Student.objects.filter(admission_number__iexact=admission_number)
                    
                    if not students.exists():
                        # Try alternative: remove any extra slashes or spaces
                        clean_adm = admission_number.replace(' ', '').strip('/')
                        students = Student.objects.filter(admission_number__icontains=clean_adm)
                    
                    if not students.exists():
                        not_found += 1
                        self.stderr.write(self.style.WARNING(f"Student not found: {admission_number}"))
                        continue
                    
                    student = students.first()
                    
                    # POSITIVE → Balance B/F
                    if total_balance > 0:
                        student.bal_bf_original = total_balance
                        student.save(update_fields=["bal_bf_original"])
                        updated_bf += 1
                        self.stdout.write(f"Updated {admission_number}: Balance B/F = {total_balance}")
                    
                    # NEGATIVE → Prepayment (store positive)
                    elif total_balance < 0:
                        student.prepayment_original = abs(total_balance)
                        student.save(update_fields=["prepayment_original"])
                        updated_prepayment += 1
                        self.stdout.write(f"Updated {admission_number}: Prepayment = {abs(total_balance)}")
                        
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Error processing row {index}: {e}"))
                    continue
        
        self.stdout.write(self.style.SUCCESS("=== IMPORT SUMMARY ==="))
        self.stdout.write(self.style.SUCCESS(f"Balance BF updated: {updated_bf}"))
        self.stdout.write(self.style.SUCCESS(f"Prepayments updated: {updated_prepayment}"))
        self.stdout.write(self.style.WARNING(f"Skipped (0/empty): {skipped}"))
        self.stdout.write(self.style.WARNING(f"Students not found: {not_found}"))