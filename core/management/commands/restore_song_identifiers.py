import csv
from importlib import import_module

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


class Command(BaseCommand):
    help = 'Restore song identifiers from a verified CSV mapping after migration 0019.'

    def add_arguments(self, parser):
        parser.add_argument('mapping_file', help='CSV with old_id and musicbrainz_id columns')
        parser.add_argument('--apply', action='store_true', help='Apply the verified mapping')

    def handle(self, *args, **options):
        try:
            with open(options['mapping_file'], encoding='utf-8-sig', newline='') as file:
                reader = csv.DictReader(file)
                if not reader.fieldnames or not {'old_id', 'musicbrainz_id'} <= set(reader.fieldnames):
                    raise ValueError('CSV must include old_id and musicbrainz_id columns.')
                rows = list(reader)
            mapping = {}
            for row in rows:
                old, new = row['old_id'], row['musicbrainz_id']
                if not old or old != old.strip() or old in mapping:
                    raise ValueError('Every old_id must be present, unique, and have no surrounding spaces.')
                mapping[old] = new
            if not mapping:
                raise ValueError('The mapping is empty.')
            migration = import_module('core.migrations.0019_remove_song_musicbrainz_id_song_bpm_song_genre_and_more')
            with transaction.atomic():
                migration.rekey_songs(apps, connection, mapping)
                if not options['apply']:
                    transaction.set_rollback(True)
            action = 'Restored' if options['apply'] else 'Validated without saving'
            self.stdout.write(f'{action} {len(mapping)} song identifiers.')
        except (OSError, csv.Error, ValueError) as error:
            raise CommandError(str(error)) from error
