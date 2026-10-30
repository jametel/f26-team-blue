import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0010_request_venue_constraint')]
    operations = [
        migrations.CreateModel(
            name='SongFeatures',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('genre', models.CharField(max_length=100, null=True, blank=True)),
                ('bpm', models.IntegerField(null=True, blank=True, validators=[django.core.validators.MinValueValidator(1)])),
                ('mood', models.CharField(max_length=100, null=True, blank=True)),
                ('energy', models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1)])),
                ('is_explicit', models.BooleanField(null=True, blank=True)),
                ('source', models.CharField(max_length=100)),
                ('confidence', models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1)])),
                ('refreshed_at', models.DateTimeField(null=True, blank=True)),
                ('song', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='features', to='core.song')),
            ],
        ),
    ]
