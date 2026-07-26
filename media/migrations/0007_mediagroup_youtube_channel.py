# Generated for the YouTube channel auto-sync feature.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('media', '0006_mediagroup_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='mediagroup',
            name='youtube_channel_url',
            field=models.URLField(
                blank=True,
                help_text=(
                    'Optional YouTube channel URL (e.g. https://www.youtube.com/@name). '
                    'New uploads are periodically downloaded as audio into this group.'
                ),
                max_length=2048,
            ),
        ),
        migrations.AddField(
            model_name='mediagroup',
            name='youtube_last_synced_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When this group was last checked for new YouTube uploads.',
                null=True,
            ),
        ),
    ]
