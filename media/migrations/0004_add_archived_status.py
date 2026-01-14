# Generated manually for archive feature

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('media', '0003_remove_base_dir'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mediaitem',
            name='status',
            field=models.CharField(
                choices=[
                    ('PREFETCHING', 'Prefetching'),
                    ('DOWNLOADING', 'Downloading'),
                    ('PROCESSING', 'Processing'),
                    ('READY', 'Ready'),
                    ('ERROR', 'Error'),
                    ('ARCHIVED', 'Archived'),
                ],
                db_index=True,
                default='PREFETCHING',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='mediaitem',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
