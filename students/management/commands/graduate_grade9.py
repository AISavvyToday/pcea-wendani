# students/management/commands/graduate_grade9.py

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from academics.models import Class
from students.models import Student
from core.models import GradeLevel


class Command(BaseCommand):
    help = "Update all students in Grade 9 classes to 'graduated' status"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without updating the database"
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Find all Grade 9 classes
        grade9_classes = Class.objects.filter(grade_level=GradeLevel.GRADE_9)
        class_ids = list(grade9_classes.values_list("id", flat=True))

        if not class_ids:
            self.stdout.write(
                self.style.WARNING("No Grade 9 classes found in the database.")
            )
            return

        self.stdout.write(
            self.style.NOTICE(
                f"Found {len(class_ids)} Grade 9 class(es): {', '.join(str(c.name) for c in grade9_classes)}"
            )
        )

        # Find all students in Grade 9 classes
        students = Student.objects.filter(current_class_id__in=class_ids)
        student_count = students.count()

        if student_count == 0:
            self.stdout.write(
                self.style.WARNING("No students found in Grade 9 classes.")
            )
            return

        # Show current status breakdown
        status_breakdown = students.values("status").annotate(
            count=Count("id")
        )
        self.stdout.write(
            self.style.NOTICE(
                f"\nFound {student_count} student(s) in Grade 9 classes:"
            )
        )
        for item in status_breakdown:
            self.stdout.write(f"  - {item['status']}: {item['count']}")

        # Count how many would actually be updated (excluding already graduated)
        would_update_count = students.exclude(status="graduated").count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\n=== DRY RUN MODE ==="
                )
            )
            self.stdout.write(
                f"Would update {would_update_count} student(s) to 'graduated' status."
            )
            if student_count > would_update_count:
                self.stdout.write(
                    f"  ({student_count - would_update_count} student(s) are already graduated)"
                )
            self.stdout.write("Run without --dry-run to apply changes.")
            return

        # Update students
        now = timezone.now()
        students_to_update = []

        with transaction.atomic():
            for student in students:
                # Only update if not already graduated
                if student.status != "graduated":
                    student.status = "graduated"
                    student.status_date = now
                    # Append to status_reason if it exists, otherwise set it
                    if student.status_reason:
                        student.status_reason = (
                            f"{student.status_reason}\n---\nGraduated from Grade 9"
                        )
                    else:
                        student.status_reason = "Graduated from Grade 9"
                    students_to_update.append(student)

            # Use bulk_update for efficiency
            if students_to_update:
                Student.objects.bulk_update(
                    students_to_update,
                    ["status", "status_date", "status_reason"],
                    batch_size=100,
                )
                updated_count = len(students_to_update)
            else:
                updated_count = 0

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Successfully updated {updated_count} student(s) to 'graduated' status."
            )
        )
        if student_count > updated_count:
            self.stdout.write(
                self.style.NOTICE(
                    f"  ({student_count - updated_count} student(s) were already graduated)"
                )
            )

