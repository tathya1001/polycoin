import sys

from django.core.management.base import BaseCommand, CommandError

from ai.eval import judge


class Command(BaseCommand):
    help = (
        "Print the labelling sheet (markdown) for a saved answers run: a sample of answers, each "
        "with exactly what the model was given, for a person to score. Calls no model."
    )

    def add_arguments(self, parser):
        parser.add_argument("--run", required=True, metavar="LABEL", help="A saved answers run.")
        parser.add_argument("--count", type=int, default=50)
        parser.add_argument("--unrelated", type=int, default=8, help="No-answer items among them.")
        parser.add_argument(
            "--held-out",
            action="store_true",
            help="A held-out sheet (items H01, H02, ...) that leaves out every answer already in "
            "the sheet given on standard input.",
        )

    def handle(self, *args, **options):
        try:
            items = judge.items_from_run(options["run"])
        except FileNotFoundError as problem:
            raise CommandError(str(problem)) from None
        exclude = set(judge.read_labels(sys.stdin.read())) if options["held_out"] else set()
        sheet = judge.render_sheet(
            options["run"],
            items,
            options["count"],
            options["unrelated"],
            exclude=exclude,
            prefix=judge.HELD_OUT if options["held_out"] else judge.TUNING,
        )
        self.stdout.write(sheet, ending="")
