# Generated manually to remove base_dir field

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('media', '0002_convert_paths_to_relative'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='mediaitem',
            name='base_dir',
        ),
    ]
