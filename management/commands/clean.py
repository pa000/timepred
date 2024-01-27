from django.core.management.base import BaseCommand
from timepred.processing.clean import remove_incorrect_data


class Command(BaseCommand):
    def handle(self, *args, **options):
        remove_incorrect_data()
