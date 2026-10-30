from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0014_song_decision')]
    operations = [
        migrations.AddField(model_name='queue', name='position', field=models.PositiveIntegerField(null=True)),
        migrations.AddField(model_name='queue', name='priority', field=models.SmallIntegerField(default=0)),
        migrations.AlterField(
            model_name='songrequest', name='status',
            field=models.CharField(max_length=20, default='PENDING', choices=[
                ('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'),
                ('PLAYED', 'Played'), ('REMOVED', 'Removed'),
            ]),
        ),
    ]
