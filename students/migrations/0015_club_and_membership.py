from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('students', '0014_parent_organization_student_organization'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Club',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('is_active', models.BooleanField(default=True)),
                ('name', models.CharField(max_length=100)),
                ('code', models.CharField(blank=True, max_length=30)),
                ('description', models.TextField(blank=True)),
                ('patron_name', models.CharField(blank=True, max_length=100)),
                ('organization', models.ForeignKey(blank=True, help_text='Organization this club belongs to', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='clubs', to='core.organization')),
            ],
            options={
                'db_table': 'clubs',
                'ordering': ['name'],
                'unique_together': {('organization', 'name')},
            },
        ),
        migrations.CreateModel(
            name='ClubMembership',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('is_active', models.BooleanField(default=True)),
                ('joined_on', models.DateField(default=django.utils.timezone.now)),
                ('club', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='students.club')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='club_memberships', to='students.student')),
            ],
            options={
                'db_table': 'club_memberships',
                'ordering': ['club__name', 'student__admission_number'],
                'unique_together': {('club', 'student')},
            },
        ),
        migrations.AddField(
            model_name='club',
            name='students',
            field=models.ManyToManyField(related_name='clubs', through='students.ClubMembership', to='students.student'),
        ),
    ]
