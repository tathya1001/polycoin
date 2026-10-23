import os

from django.core.management.base import BaseCommand

from ai.eval import embed


class Command(BaseCommand):
    help = (
        "Embed the retrieval evaluation set with a local Ollama and write "
        "ai/eval/rag_vectors.json (dev machine only; commit the result)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--model", default="nomic-embed-text:latest")
        parser.add_argument(
            "--url",
            default=os.environ.get("OLLAMA_URL", embed.DEFAULT_URL),
            help="Ollama's address (default: OLLAMA_URL, else the Docker host).",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(embed.write_vectors(options["url"], options["model"])))
