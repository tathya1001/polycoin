from django.core.management.base import BaseCommand, CommandError

from ai.eval import results, search_report


class Command(BaseCommand):
    help = (
        "Score the production search settings on the evaluation set: every metric with confidence "
        "intervals, cross-validated scores, each search side alone and scores per question type. "
        "Needs no model: it uses the committed vectors."
    )

    def add_arguments(self, parser):
        parser.add_argument("--record", metavar="LABEL", help="Save the run, like 'baseline'.")
        parser.add_argument("--compare", metavar="LABEL", help="Compare with a saved run.")
        parser.add_argument("--overwrite", action="store_true", help="Replace a saved run.")

    def handle(self, *args, **options):
        run = search_report.build()
        self.stdout.write(search_report.format_run(run))
        try:
            if options["compare"]:
                before = results.load(search_report.KIND, options["compare"])
                self.stdout.write(f"\nCompared with '{options['compare']}' "
                                  f"(commit {before['meta']['commit']}, {before['meta']['date']}):")  # fmt: skip
                self.stdout.write(search_report.compare(before, run))
            if options["record"]:
                path = results.save(
                    search_report.KIND, options["record"], run, overwrite=options["overwrite"]
                )
                self.stdout.write(self.style.SUCCESS(f"\nSaved {path.name}"))
        except (ValueError, FileExistsError, FileNotFoundError) as problem:
            raise CommandError(str(problem)) from None
