import os

from django.core.management.base import BaseCommand, CommandError

from ai.eval import candidates, dataset, embed


class Command(BaseCommand):
    help = (
        "Embed the retrieval evaluation sets with a local Ollama (dev machine only). Without "
        "--cache, writes the committed vector files (commit the result); with --cache, writes "
        "the benchmark's git-ignored cache, using the model's own task prefixes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--model", default="embeddinggemma:latest")
        parser.add_argument(
            "--url",
            default=os.environ.get("OLLAMA_URL", embed.DEFAULT_URL),
            help="Ollama's address (default: OLLAMA_URL, else the Docker host).",
        )
        parser.add_argument(
            "--split", choices=(*dataset.SPLITS, "all"), default="all", help="Which set to embed."
        )
        parser.add_argument(
            "--cache", action="store_true", help="Write to the benchmark cache, for comparing."
        )

    def handle(self, *args, **options):
        model = options["model"]
        splits = dataset.SPLITS if options["split"] == "all" else (options["split"],)
        try:
            prefixes = candidates.prefixes_for(model) if options["cache"] else None
        except ValueError as problem:
            raise CommandError(str(problem)) from None
        for split in splits:
            path = candidates.cache_path(model, split) if options["cache"] else None
            summary = embed.write_vectors(options["url"], model, split, prefixes, path)
            self.stdout.write(self.style.SUCCESS(summary))
