from django.db import migrations


def restore_request_identity(apps, schema_editor):
    connection = schema_editor.connection
    Request = apps.get_model('core', 'SongRequest')
    if 'core_request_identity_backup' in connection.introspection.table_names():
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT request_id, requested_by_id, session_key '
                'FROM core_request_identity_backup'
            )
            rows = cursor.fetchall()
        for request_id, user_id, session_key in rows:
            Request.objects.filter(pk=request_id).update(
                requested_by_id=user_id, session_key=session_key or ''
            )
        schema_editor.execute('DROP TABLE core_request_identity_backup')

    for old, new in (
        ('Pending', 'PENDING'), ('Approved', 'APPROVED'),
        ('Rejected', 'REJECTED'), ('Played', 'PLAYED'),
    ):
        Request.objects.filter(status=old).update(status=new)


class Migration(migrations.Migration):
    dependencies = [('core', '0006_repair_request_workflow')]
    operations = [migrations.RunPython(restore_request_identity, migrations.RunPython.noop)]
