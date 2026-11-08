from django.core.management.base import BaseCommand, CommandError

from ai.eval import report, results, search_report
from ai.eval.evaluate import Evaluation


class Command(BaseCommand):
    help = (
        "Print the AI evaluation report as markdown: search scored now, plus every saved run. "
        "scripts/ai-eval.sh writes it to dev-docs/ai-evaluation.md. Needs no model."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--compare", metavar="LABEL", help="Before and after against a saved search run."
        )
        parser.add_argument(
            "--final",
            action="store_true",
            help="Also score the locked test set. Do this once, after all tuning is finished.",
        )

    def handle(self, *args, **options):
        current = search_report.build()
        comparison = None
        try:
            if options["compare"]:
                before = results.load(search_report.KIND, options["compare"])
                comparison = (options["compare"], search_report.compare_data(before, current))
        except (ValueError, FileNotFoundError) as problem:
            raise CommandError(str(problem)) from None
        final = search_report.build(Evaluation("test")) if options["final"] else None
        saved = {kind: results.load_all(kind) for kind, _ in report.SAVED_SECTIONS}
        page = report.render(
            current, results.load_all(search_report.KIND), saved, comparison, final
        )
        self.stdout.write(page, ending="")
