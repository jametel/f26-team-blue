import django.db.models.deletion
import django.core.validators
from django.conf import settings
from django.db import migrations, models
from django.utils.text import slugify


def assign_venue_slugs(apps, schema_editor):
    Venue = apps.get_model('core', 'Venue')
    for venue in Venue.objects.all():
        prefix = slugify(venue.name)[:80] or 'venue'
        venue.slug = f'{prefix}-{venue.pk}'
        venue.save(update_fields=['slug'])


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0007_restore_request_identity'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='venue', name='slug',
            field=models.CharField(max_length=100, null=True, blank=True),
        ),
        migrations.RunPython(assign_venue_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='venue', name='slug',
            field=models.SlugField(max_length=100, unique=True, blank=True),
        ),
        migrations.AddField(
            model_name='venue', name='owner',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='owned_venues', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='venue', name='staff',
            field=models.ManyToManyField(blank=True, related_name='staff_venues', to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name='VenueConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('min_bpm', models.PositiveIntegerField(null=True, blank=True, validators=[django.core.validators.MinValueValidator(1)])),
                ('max_bpm', models.PositiveIntegerField(null=True, blank=True, validators=[django.core.validators.MinValueValidator(1)])),
                ('allow_explicit', models.BooleanField(default=False)),
                ('unknown_policy', models.CharField(max_length=10, default='REVIEW', choices=[('REVIEW', 'Staff review'), ('ACCEPT', 'Accept'), ('REJECT', 'Reject')])),
                ('venue', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='config', to='core.venue')),
            ],
            options={
                'constraints': [
                    models.CheckConstraint(condition=models.Q(min_bpm__isnull=True) | models.Q(min_bpm__gte=1), name='venue_min_bpm_positive'),
                    models.CheckConstraint(condition=models.Q(max_bpm__isnull=True) | models.Q(max_bpm__gte=1), name='venue_max_bpm_positive'),
                    models.CheckConstraint(condition=models.Q(min_bpm__isnull=True) | models.Q(max_bpm__isnull=True) | models.Q(min_bpm__lte=models.F('max_bpm')), name='venue_bpm_range_valid'),
                ],
            },
        ),
    ]
