from django.core.management.base import BaseCommand

from ai.eval import build_dataset


class Command(BaseCommand):
    help = (
        "Rebuild the fictional retrieval evaluation set (ai/eval/rag_corpus.json and "
        "rag_questions.json). Re-run embed_rag_eval afterwards."
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(build_dataset.write()))
