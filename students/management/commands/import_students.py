# students/management/commands/import_students.py

import re
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import List, Optional, Tuple

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from academics.models import AcademicYear, Term, Class
from students.models import Student, Parent, StudentParent
from core.models import TermChoices

STREAM_EAST = "East"  # change if your Class.stream choices require something else


def normalize_class_key(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    value = value.upper()
    # Remove extra year numbers like "2025" since they're already in academic year
    value = re.sub(r'\s+202[0-9]$', '', value)
    value = re.sub(r'\s+\(202[0-9]\)$', '', value)
    return value.strip()


def to_decimal(value) -> Decimal:
    """
    Safe conversion from pandas values (NaN, floats, strings) to Decimal.
    """
    if value is None:
        return Decimal("0.00")

    try:
        # pandas NaN handling
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


def normalize_ke_phone(digits_only: str) -> Optional[str]:
    """
    Convert to +254XXXXXXXXX format.
    Accepts:
      - 2547XXXXXXXX / 2541XXXXXXXX
      - 07XXXXXXXX / 01XXXXXXXX
      - 7XXXXXXXX / 1XXXXXXXX (9 digits)
    """
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


def extract_phones(contacts: str) -> List[str]:
    """
    Extract Kenyan phone numbers from messy contact strings.
    """
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
            p = normalize_ke_phone(m)
            if p and p not in seen:
                phones.append(p)
                seen.add(p)

    digits = re.sub(r"\D", "", text)
    for m in re.findall(r"254\d{9}", digits):
        p = normalize_ke_phone(m)
        if p and p not in seen:
            phones.append(p)
            seen.add(p)

    for m in re.findall(r"0\d{9}", digits):
        p = normalize_ke_phone(m)
        if p and p not in seen:
            phones.append(p)
            seen.add(p)

    return phones


class Command(BaseCommand):
    help = "Import students with credit balances from Excel file"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to Excel file")
        parser.add_argument("--dry-run", action="store_true", help="Parse and validate but roll back DB changes")
        parser.add_argument("--limit", type=int, default=0, help="Only import first N rows (0 = all)")

    def handle(self, *args, **options):
        file_path = options["file_path"]
        dry_run = options["dry_run"]
        limit = options["limit"] or 0

        self.stdout.write(self.style.NOTICE(f"Reading {file_path}..."))

        # Read Excel: your sheet has a top line then header row (Year, #, Name...)
        df = pd.read_excel(file_path, sheet_name=0)
        
        # Print debug info
        print("Columns found:", df.columns.tolist())
        print("First few rows:")
        print(df.head())
        
        # Clean column names - remove whitespace
        df.columns = [str(c).strip() for c in df.columns]
        
        # Check for different possible column names
        column_mapping = {
            "Year": "Year",
            "#": "Admission_No",
            "Name": "Name",
            "Class": "Class",
            "Contacts": "Contacts",
            "Total Balance": "Total_Balance",
            "Total Balance": "Total_Balance",
            "Balance B/F": "Balance_BF",
            "Current Balance": "Current_Balance",
            "Prepayment": "Prepayment"
        }
        
        # Rename columns based on what we find
        for excel_col, our_col in column_mapping.items():
            if excel_col in df.columns and our_col not in df.columns:
                df = df.rename(columns={excel_col: our_col})
        
        # Check if we have the needed columns
        required = [
            "Admission_No",
            "Name",
            "Class",
        ]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing expected columns in Excel: {missing}. Found: {list(df.columns)}")

        # Clean the data
        df = df.dropna(subset=["Admission_No"]).copy()
        df["Admission_No"] = df["Admission_No"].astype(str).str.strip()
        df["Name"] = df["Name"].astype(str).str.strip()
        df["Class"] = df["Class"].astype(str).str.strip()
        
        # For debugging, print unique class values
        unique_classes = df["Class"].unique()
        print(f"Found {len(unique_classes)} unique class values in Excel:")
        for cls in sorted(unique_classes):
            print(f"  '{cls}'")

        if limit > 0:
            df = df.head(limit)

        stats = {
            "students_created": 0,
            "students_updated": 0,
            "parents_created": 0,
            "rows_skipped": 0,
            "errors": 0,
        }

        with transaction.atomic():
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

            class_mapping = self.create_classes(academic_year)

            for _, row in df.iterrows():
                try:
                    self.import_row(row, class_mapping, term, stats)
                except Exception as e:
                    stats["errors"] += 1
                    adm = str(row.get("Admission_No", "")).strip()
                    self.stdout.write(self.style.ERROR(f"[{adm}] Import failed: {e}"))

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"""
Import Complete! {'(DRY RUN - rolled back)' if dry_run else ''}
----------------
Students created: {stats['students_created']}
Students updated: {stats['students_updated']}
Parents created: {stats['parents_created']}
Rows skipped: {stats['rows_skipped']}
Errors: {stats['errors']}
"""
            )
        )

    def create_classes(self, academic_year):
        """
        Create all classes and return mapping keyed by normalized Excel class names.
        """
        # Map Excel class patterns to database class names
        class_config = [
            # GRADE classes
            ("GRADE 9", "Grade 9 2025", "grade_9", STREAM_EAST),
            ("GRADE 8", "Grade 8 2025", "grade_8", STREAM_EAST),
            ("GRADE 7", "Grade 7 2025", "grade_7", STREAM_EAST),
            ("GRADE 6", "Grade 6 2025", "grade_6", STREAM_EAST),
            ("GRADE 5", "Grade 5 2025", "grade_5", STREAM_EAST),
            ("GRADE 4", "Grade 4 2025", "grade_4", STREAM_EAST),
            ("GRADE 3", "Grade 3 2025", "grade_3", STREAM_EAST),
            ("GRADE 2", "Grade 2 2025", "grade_2", STREAM_EAST),
            ("GRADE 1", "Grade 1 2025", "grade_1", STREAM_EAST),
            
            # Pre-primary classes
            ("PP2", "PP2 2025", "pp2", STREAM_EAST),
            ("PP1", "PP1 2025", "pp1", STREAM_EAST),
            
            # PlayGroup variations
            ("PLAYGROUP", "PlayGroup 2025", "playgroup", STREAM_EAST),
            ("PLAY GROUP", "PlayGroup 2025", "playgroup", STREAM_EAST),
            
            # Handle variations with year appended
            ("GRADE 9 2025", "Grade 9 2025", "grade_9", STREAM_EAST),
            ("GRADE 8 2025", "Grade 8 2025", "grade_8", STREAM_EAST),
            ("GRADE 7 2025", "Grade 7 2025", "grade_7", STREAM_EAST),
            ("GRADE 6 2025", "Grade 6 2025", "grade_6", STREAM_EAST),
            ("GRADE 5 2025", "Grade 5 2025", "grade_5", STREAM_EAST),
            ("GRADE 4 2025", "Grade 4 2025", "grade_4", STREAM_EAST),
            ("GRADE 3 2025", "Grade 3 2025", "grade_3", STREAM_EAST),
            ("GRADE 2 2025", "Grade 2 2025", "grade_2", STREAM_EAST),
            ("GRADE 1 2025", "Grade 1 2025", "grade_1", STREAM_EAST),
            ("PP2 2025", "PP2 2025", "pp2", STREAM_EAST),
            ("PP1 2025", "PP1 2025", "pp1", STREAM_EAST),
        ]

        mapping = {}
        for excel_pattern, db_class_name, grade_level, stream in class_config:
            key = normalize_class_key(excel_pattern)
            
            # Try to find existing class first
            class_obj = Class.objects.filter(
                name=db_class_name,
                academic_year=academic_year
            ).first()
            
            if not class_obj:
                # Create new class if doesn't exist
                class_obj, created = Class.objects.get_or_create(
                    name=db_class_name,
                    academic_year=academic_year,
                    defaults={
                        "grade_level": grade_level,
                        "stream": stream,
                    },
                )
                
                # Enforce stream if field exists
                try:
                    if getattr(class_obj, "stream", None) != stream:
                        class_obj.stream = stream
                        class_obj.save(update_fields=["stream"])
                except Exception:
                    pass
            
            mapping[key] = class_obj
        
        # Debug: print mapping
        print("Class mapping created:")
        for key, cls in mapping.items():
            print(f"  '{key}' -> '{cls.name}' (grade_level: {cls.grade_level})")

        return mapping

    def import_row(self, row, class_mapping, term, stats):
        admission_no = str(row["Admission_No"]).strip()
        if not admission_no:
            stats["rows_skipped"] += 1
            return

        full_name = str(row["Name"]).strip()
        class_name = str(row["Class"]).strip()
        contacts = str(row["Contacts"]).strip() if "Contacts" in row and pd.notna(row["Contacts"]) else ""

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

        # Class mapping (robust)
        class_key = normalize_class_key(class_name)
        class_obj = class_mapping.get(class_key)
        
        if not class_obj:
            # Try to find class directly in database
            class_obj = Class.objects.filter(
                name__icontains=class_key,
                academic_year__year=2025
            ).first()
            
            if not class_obj:
                stats["rows_skipped"] += 1
                self.stdout.write(self.style.WARNING(f"Unknown class '{class_name}' (normalized: '{class_key}') for {admission_no}"))
                return

        # Calculate balance from Excel columns if available
        credit_balance = Decimal('0.00')
        
        # Try different column names for balance
        balance_columns = ["Total_Balance", "Current_Balance", "Balance_BF", "Prepayment"]
        for col in balance_columns:
            if col in row and pd.notna(row[col]):
                try:
                    # Handle formula values (they might be strings)
                    val = str(row[col])
                    if val.startswith('='):
                        # Simple formula evaluation: =G2+H2-F2
                        # Extract cell references and look up values
                        # This is a simplified version - in production you'd want a proper formula parser
                        pass
                    else:
                        credit_balance = to_decimal(row[col])
                        break
                except Exception as e:
                    pass
        
        # Set frozen original values based on Excel balance
        balance_bf_original = credit_balance if credit_balance > 0 else Decimal('0.00')
        prepayment_original = abs(credit_balance) if credit_balance < 0 else Decimal('0.00')

        # Student upsert with credit_balance and frozen fields
        student, created = Student.objects.update_or_create(
            admission_number=admission_no,
            defaults={
                "first_name": first_name.title(),
                "middle_name": middle_name.title(),
                "last_name": last_name.title(),
                "current_class": class_obj,
                "credit_balance": credit_balance,
                "balance_bf_original": balance_bf_original,
                "prepayment_original": prepayment_original,
                "admission_date": date(2025, 1, 6),
                "date_of_birth": date(2015, 1, 1),  # placeholder - adjust based on grade
                "gender": self.guess_gender(full_name),  # improved gender guessing
                "status": "active",
            },
        )
        
        if created:
            stats["students_created"] += 1
            self.stdout.write(self.style.SUCCESS(f"Created: {admission_no} - {full_name} -> {class_obj.name}"))
        else:
            stats["students_updated"] += 1
            self.stdout.write(self.style.NOTICE(f"Updated: {admission_no} - {full_name} -> {class_obj.name}"))

        # Parent extraction/link
        if contacts and contacts.strip().lower() not in {"254", "nan"}:
            self.create_parent_from_contacts(student, contacts, stats)

    def guess_gender(self, full_name: str) -> str:
        """Simple gender guessing based on name patterns"""
        name_lower = full_name.lower()
        
        # Common female names in your data
        female_indicators = [
            'wanjiru', 'wanjiku', 'nyambura', 'njeri', 'njoki', 'wangui', 
            'nyawira', 'muthoni', 'nyokabi', 'kerubo', 'cheptoo', 'jane',
            'mary', 'susan', 'grace', 'faith', 'hope', 'joy', 'prudence',
            'regina', 'dorcas', 'lydia', 'abigael', 'tracy', 'ann', 'aidah',
            'barbara', 'teresa', 'sylvia', 'stacy', 'sharon', 'stephanie',
            'meyers', 'beatrice', 'nancy', 'winfred', 'delcee', 'joypeninna',
            'ashley', 'sofia', 'olivia', 'amillia', 'keysha', 'leticia',
            'jasmin', 'precious', 'ana', 'imann', 'lainiey', 'esther', 'anaya',
            'monica', 'terryann', 'michelle', 'sloan', 'lesley', 'edna', 'sarah',
            'natalie', 'ruby', 'tiffany', 'tifanny', 'triza', 'tasha', 'gebrielle',
            'elsie', 'claire', 'cindy', 'shanice', 'blessing', 'hawi', 'joysasha',
            'lindsey', 'rosette', 'alexis', 'hilda', 'christine', 'taneesha',
            'tiffany', 'julie', 'emani', 'lisa', 'stephanie', 'esther', 'blessing',
            'maya', 'shanicenjeri', 'victoria', 'alisha', 'talia', 'yasmine',
            'gianna', 'sabian', 'angel', 'kimberly', 'millicent', 'britney',
            'angel', 'nillan', 'lynne', 'praise', 'scarlet', 'jewel', 'becky',
            'vanessa', 'susan', 'aurelia', 'nicole', 'amy', 'adrielle', 'sharon',
            'gianna', 'ellen', 'trizah', 'lisa', 'andrea', 'addah', 'angelicah',
            'tiana', 'leila', 'lavinia', 'meghan', 'eliana', 'alyssa', 'ariana',
            'laura', 'tayana', 'mollyann', 'natalia', 'nadia', 'alma', 'nancy',
            'maylin', 'elsie', 'mariah', 'riannah', 'essy', 'stephanie', 'mayanah',
            'elsie', 'tiana', 'marsha', 'june', 'naila', 'linda', 'precious',
            'madelyn', 'tamia', 'tinsely', 'tashely', 'tanisha', 'joy', 'zaneta',
            'joan', 'alexia', 'natania', 'tiffany', 'annrowena', 'shannel',
            'wemah', 'naomi', 'rayna', 'tiffany', 'carmi', 'misky', 'precious',
            'eliana', 'lynne', 'grace', 'angel', 'gladys', 'princess', 'nicole',
            'susan', 'victoria', 'tasha', 'veronica', 'victoria', 'andrea',
            'shantel', 'tamara', 'brightvictoria', 'tasha', 'joan', 'abigael',
            'gladys', 'aaliah', 'natalie', 'samantha', 'lesley', 'alexis',
            'gianna', 'ayesha', 'promise', 'ella', 'tiffany', 'siobhan',
            'audreyann', 'maureen', 'chloe', 'shekinah', 'luciabella', 'mya',
            'briella', 'lavin', 'keisha', 'paula', 'liana', 'jewel', 'brieshah',
            'leilani', 'abigael', 'jancy', 'brianna', 'nessie', 'joy', 'wanjiru',
            'ivy', 'joy', 'pinky', 'claudia', 'mariana', 'elianna', 'neriah',
            'brenda', 'phyllis', 'mariana', 'claudia', 'pinky', 'gabriella',
            'elianna', 'neriah', 'brenda', 'phyllis', 'mariana', 'claudia',
            'pinky', 'gabriella', 'elianna', 'neriah', 'brenda', 'phyllis',
            'mariana', 'claudia', 'pinky', 'gabriella'
        ]
        
        # Common male names in your data  
        male_indicators = [
            'raymond', 'nicholas', 'franklin', 'mike', 'fredrick', 'jayden',
            'ethan', 'samuel', 'sunday', 'nelson', 'bilquees', 'graeme',
            'maxwell', 'imbusi', 'ian', 'emmanuel', 'elvis', 'enrique', 'lewis',
            'damian', 'wilson', 'jesse', 'bereket', 'ezra', 'jesse', 'peter',
            'jermaine', 'troy', 'gift', 'trevor', 'tyler', 'christiano', 'neron',
            'ian', 'kefer', 'abel', 'ryan', 'mor', 'trevier', 'jesse', 'peter',
            'dylan', 'larvin', 'dwayne', 'melvin', 'liam', 'ethan', 'azriel',
            'misheel', 'washington', 'lain', 'carlton', 'leon', 'peter', 'haniel',
            'terryann', 'michelle', 'sloan', 'lesley', 'sammy', 'israel',
            'johannes', 'emmanuel', 'chris', 'damian', 'nathan', 'simon', 'julian',
            'jayden', 'francis', 'fabian', 'austine', 'branice', 'nobel', 'jeremy',
            'jabez', 'maxwell', 'collins', 'austine', 'brandon', 'tyron', 'fidel',
            'andrew', 'henok', 'briannah', 'tijaan', 'michael', 'maurice', 'kai',
            'leon', 'caleb', 'adrian', 'evlogia', 'liam', 'gian', 'nathan',
            'liam', 'peace', 'adela', 'nourcen', 'gabriel', 'deilon', 'theon',
            'liam', 'carl', 'sabian', 'ryan', 'ethan', 'shawn', 'ethan', 'liam',
            'caleb', 'liam', 'lemuel', 'jayden', 'skyler', 'branton', 'jason',
            'israel', 'george', 'bill', 'davis', 'myles', 'lenny', 'jayden',
            'liam', 'emmanuel', 'mishael', 'abel', 'bradon', 'andrea', 'addah',
            'angelicah', 'delvin', 'jabali', 'tiana', 'trevour', 'john', 'williams',
            'prince', 'leila', 'noah', 'elijah', 'ian', 'kaiden', 'ryan', 'baraka',
            'bayly', 'jude', 'jayden', 'destiny', 'adrian', 'jonnievans', 'ethan',
            'haxley', 'clara', 'vinny', 'moses', 'abigael', 'lieighton', 'sherlyn',
            'lavinia', 'james', 'meghan', 'eliana', 'alyssa', 'ariana', 'klaire',
            'laura', 'jesse', 'liam', 'tayana', 'mollyann', 'kyle', 'maximillan',
            'natalia', 'nadia', 'noel', 'alma', 'nancy', 'maylin', 'elsie',
            'jayden', 'jayden', 'riannah', 'mariah', 'essy', 'nicholas', 'stephanie',
            'branson', 'prince', 'ethan', 'mayanah', 'elsie', 'tiana', 'adrian',
            'victor', 'marsha', 'june', 'haniel', 'naila', 'ethan', 'joeljeremy',
            'muhoro', 'precious', 'keith', 'darrel', 'madelyn', 'tamia', 'tinsely',
            'brainard', 'tashely', 'nathan', 'tanisha', 'alpha', 'ethan', 'evans',
            'joy', 'lennox', 'zaneta', 'erick', 'maxwell', 'joan', 'alexia',
            'adrian', 'fidell', 'jesse', 'natania', 'paul', 'tiffany', 'annrowena',
            'ronjustine', 'collins', 'allen', 'shannel', 'deyshawn', 'paul',
            'samuel', 'bereket', 'nevid', 'sebastian', 'alvin', 'wemah', 'hamisi',
            'naomi', 'rayna', 'maxwell', 'tiffany', 'innocent', 'carmi', 'alvin',
            'misky', 'joe', 'precious', 'eliana', 'darrmien', 'lynne', 'grace',
            'angel', 'jayden', 'gladys', 'george', 'princess', 'giovanni', 'nicole',
            'nathan', 'ryan', 'susan', 'ithiel', 'hakeem', 'victoria', 'steve',
            'tasha', 'nethan', 'brian', 'inaarah', 'warren', 'rachel', 'nolan',
            'nicole', 'veronica', 'victoria', 'max', 'green', 'andrea', 'elly',
            'eve', 'shanaya', 'adrian', 'arthur', 'victor', 'ryan', 'joshua',
            'juliet', 'francis', 'shantel', 'gerald', 'tamara', 'jayden',
            'brightvictoria', 'tasha', 'joan', 'vincent', 'hadynpaul', 'jaden',
            'abigael', 'ryan', 'stephanie', 'tamima', 'israel', 'natalia',
            'emmanuel', 'denzel', 'lavine', 'charles', 'larisa', 'myllan', 'asher',
            'jayson', 'terry', 'jackline', 'peterson', 'aaliyah', 'andrew', 'diana',
            'tegan', 'thalma', 'lucy', 'achan', 'angear', 'gael', 'reagan',
            'abigael', 'gladys', 'declan', 'granvilile', 'aaliah', 'vinshel',
            'olivia', 'justine', 'victor', 'natalie', 'prince', 'dylan', 'christian',
            'samantha', 'lewis', 'dalton', 'lesley', 'louis', 'alexis', 'gianna',
            'samuel', 'allan', 'nolan', 'ephrath', 'ayesha', 'naval', 'promise',
            'ella', 'ethan', 'ryan', 'tiffany', 'harville', 'siobhan', 'nabil',
            'ethan', 'elyana', 'victor', 'edi', 'elaine', 'victor', 'daniel',
            'norman', 'audreyann', 'ayden', 'maureen', 'oscar', 'jaylen', 'chloe',
            'biko', 'prince', 'grayson', 'shekinah', 'eli', 'tyler', 'kyle', 'moses',
            'luciabella', 'leslie', 'mya', 'trevor', 'zethan', 'briella', 'lavin',
            'jaysen', 'peterxavier', 'keisha', 'adrian', 'reagan', 'paula', 'liana',
            'shawn', 'benaiah', 'aswani', 'jewel', 'brieshah', 'shawn', 'leilani',
            'abigael', 'jancy', 'bryson', 'brianna', 'abner', 'shannel', 'nessie',
            'ryan', 'ryan', 'ivy', 'joy', 'wanjiru', 'abel', 'james', 'shaquille',
            'sharveen', 'brian', 'roy', 'royalle', 'teresia', 'raymond', 'samuel',
            'jayana', 'rachel', 'shantelle', 'glen', 'migael', 'dylan', 'whitney',
            'sammalik', 'ruth', 'blessing', 'naomi', 'ruth', 'ayana', 'leticia',
            'ivan', 'malika', 'precious', 'prudence', 'lizzy', 'brian', 'brianna',
            'nathan', 'ella', 'lian', 'laurel', 'warren', 'trevor', 'kaysan',
            'andy', 'roy', 'leon', 'hadassah', 'ariana', 'ellyanna', 'jade',
            'nigel', 'zelipha', 'kelsey', 'george', 'hadriel', 'angel', 'gianna',
            'neriah', 'aiden', 'shanice', 'gian', 'brenda', 'maxwell', 'isabel',
            'phyllis', 'tim', 'fortune', 'mariana', 'leonne', 'claudia', 'pinky',
            'gabriel', 'fabian'
        ]
        
        for indicator in female_indicators:
            if indicator in name_lower:
                return 'F'
        
        for indicator in male_indicators:
            if indicator in name_lower:
                return 'M'
        
        # Default to Male if uncertain
        return 'M'

    def create_parent_from_contacts(self, student, contacts, stats):
        phones = extract_phones(contacts)
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