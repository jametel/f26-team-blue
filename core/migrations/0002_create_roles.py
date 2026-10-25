from django.db import migrations


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ["Customer", "Staff", "Owner"]:
        Group.objects.update_or_create(name=name)


def delete_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=["Customer", "Staff", "Owner"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_groups, delete_groups),
    ]
