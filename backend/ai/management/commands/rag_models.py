from django.core.management.base import BaseCommand, CommandError

from ai.eval import benchmark, candidates, results
from ai.eval.dataset import load_vectors, vectors


class Command(BaseCommand):
    help = (
        "Compare embedding models on the dev set. Embed each one first with "
        "`embed_rag_eval --cache --model <tag>`. With --cosine, time the server's exact cosine "
        "over RAG_MAX_DOCS rows for each model's size instead; run that in a container limited "
        "like the server:\n"
        "  docker run --rm --cpus 0.1 --memory 512m --memory-swap 512m "
        "--network moneyangle_default --env-file .env -v <repo>/backend:/app moneyangle-backend "
        "python manage.py rag_models --cosine --record <label>"
    )

    def add_arguments(self, parser):
        parser.add_argument("--record", metavar="LABEL", help="Save the run, like 'v1'.")
        parser.add_argument("--overwrite", action="store_true", help="Replace a saved run.")
        parser.add_argument(
            "--cosine", action="store_true", help="Time the server's cosine for each model's size."
        )

    def handle(self, *args, **options):
        models = candidates.cached_models()
        if not models:
            raise CommandError("No cached models. Run: embed_rag_eval --cache --model <tag>")
        try:
            if options["cosine"]:
                kind, run = benchmark.COSINE_KIND, self._cosine(models)
            else:
                kind = benchmark.KIND
                run = benchmark.build(models, reference=vectors("dev")["model"])
                self.stdout.write(benchmark.format_models(run))
            if options["record"]:
                path = results.save(kind, options["record"], run, overwrite=options["overwrite"])
                self.stdout.write(self.style.SUCCESS(f"\nSaved {path.name}"))
        except (ValueError, FileExistsError) as problem:
            raise CommandError(str(problem)) from None

    def _cosine(self, models: list[str]) -> dict:
        sizes = sorted({load_vectors(candidates.cache_path(m, "dev"))["dims"] for m in models})
        limit = benchmark.cpu_limit()
        timings = {str(dims): round(benchmark.cosine_ms(dims), 1) for dims in sizes}
        where = f"{limit} CPU" if limit else "no CPU limit"
        for dims, ms in timings.items():
            self.stdout.write(f"{dims} dims: {ms} ms for one exact cosine pass ({where})")
        return {
            "meta": results.metadata(cpu_limit=limit),
            "milliseconds": timings,
            "headline": {f"{dims} dims ms": ms for dims, ms in timings.items()} | {"CPU": limit},
        }
