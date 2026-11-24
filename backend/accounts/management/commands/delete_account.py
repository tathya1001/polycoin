"""Delete one account and everything it has, for an owner who can no longer sign in.

Someone who has lost both their password and their recovery key can't use Settings > Delete my
account, and nobody can open their data. The Privacy Policy lets them ask for deletion by email;
this command carries that request out. Before running it, check that the request is really the
owner's: reply to the account's email address and wait for a confirmation from it.

Production has no admin site, so run it from a local container against the production database
(the direct, not pooled, connection string):

    docker compose run --rm -e DATABASE_URL="<connection string>" backend \
        python manage.py delete_account person@example.com

It deletes rows only, so it needs no encryption keys, and it prints counts, never content.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import ProtectedError

from accounts.models import User
from accounts.services import delete_account
from transactions.models import Transaction


class Command(BaseCommand):
    help = "Delete one account and all its data, for an owner who can no longer sign in."

    def add_arguments(self, parser):
        parser.add_argument("email", help="The email address of the account to delete.")
        parser.add_argument(
            "--no-input",
            "--noinput",
            action="store_false",
            dest="interactive",
            help="Delete without asking for the email address to be typed again.",
        )

    def handle(self, *args, email, interactive, **options):
        # The same lookup as sign-in: the domain normalised, then a case-insensitive match.
        address = User.objects.normalize_email(email.strip())
        user = User.objects.filter(email__iexact=address).first()
        if user is None:
            raise CommandError("No account has that email address. Nothing was deleted.")

        transactions = Transaction.objects.filter(user=user).count()
        self.stdout.write(
            f"Account {user.email}, created {user.date_joined:%d %b %Y}, "
            f"with {transactions} transactions."
        )
        self.stdout.write("Its encryption key is deleted too. This cannot be undone.")

        if interactive:
            typed = input("Type the email address again to delete it: ")
            if typed.strip().lower() != user.email.lower():
                raise CommandError("The email address did not match. Nothing was deleted.")

        try:
            delete_account(user)
        except ProtectedError as exc:
            # A transaction was added during the delete. It runs in one transaction: all or nothing.
            raise CommandError(
                "The account changed while it was being deleted. Nothing was deleted. Run it again."
            ) from exc
        self.stdout.write(self.style.SUCCESS("Deleted the account and all its data."))
