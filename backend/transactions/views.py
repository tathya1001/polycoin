import json
import uuid
from collections import Counter
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from categories.services import get_default_category
from core.mixins import OwnedQuerysetMixin
from datasources.services import first_source, get_source, sources_for
from vault.services import UserCipher

from .importer import (
    ImportFileError,
    PasswordRequired,
    WrongPassword,
    detect_header,
    parse_rows,
)
from .links import (
    DEFAULT_CANDIDATE_DAYS,
    MAX_CANDIDATE_DAYS,
    SUGGESTION_RANGE_DAYS,
    LinkError,
    TooManyRows,
    link_candidates,
    link_many,
    link_transactions,
    suggest_transfers,
)
from .models import Transaction, TransferLink
from .readers import read_statement
from .search import matching_ids, parse_search
from .serializers import (
    BulkCategorySerializer,
    BulkDeleteSerializer,
    BulkLinkSerializer,
    BulkSourceSerializer,
    LinkSerializer,
    TransactionSerializer,
)
from .services import create_transaction, fingerprint_of, move_transactions, where_held

# Requests reach Django through the Vercel proxy, which refuses bodies over 4.5 MB. Keep equal to
# MAX_UPLOAD_BYTES on the import page.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
PREVIEW_SAMPLE_ROWS = 10
PREVIEW_MAX_ERRORS = 50


class TransactionPagination(PageNumberPagination):
    page_size = 50


class TransactionViewSet(
    OwnedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """No create: transactions only arrive through the statement import.

    A delete is a real delete (the row, its fingerprint and its Ask document go). So importing
    the same statement again brings a deleted transaction back, as a new row in "Others"."""

    queryset = Transaction.objects.select_related(
        "category", "debit_link__credit", "credit_link__debit"
    )
    serializer_class = TransactionSerializer
    pagination_class = TransactionPagination
    # No PUT. POST only reaches the bulk actions: there is no create.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    throttle_scope = None  # only `candidates` and a search of encrypted columns have one

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["cipher"] = UserCipher(self.request.user)  # one DEK query per request
        return context

    def get_queryset(self):
        qs = super().get_queryset()  # already scoped to request.user
        params = self.request.query_params

        for param, lookup in (("from", "date__gte"), ("to", "date__lte")):
            if param in params:
                parsed = parse_date(params[param])
                if parsed is None:
                    raise ValidationError({param: "Use YYYY-MM-DD."})
                qs = qs.filter(**{lookup: parsed})

        if "type" in params:
            if params["type"] not in Transaction.Type.values:
                raise ValidationError({"type": "Must be 'credit' or 'debit'."})
            qs = qs.filter(txn_type=params["type"])

        for param, lookup in (("category", "category_id__in"), ("data_source", "data_source_id__in")):
            if param in params:  # one id, or several separated by commas
                try:
                    ids = [uuid.UUID(part) for part in params[param].split(",")]
                except ValueError:
                    raise ValidationError({param: "Not a valid id."})
                qs = qs.filter(**{lookup: ids})

        # Newest first. Date alone leaves same-day rows in no fixed order, so a row could repeat
        # or go missing between one page and the next.
        return qs.order_by("-date", "-created_at", "id")

    def get_throttles(self):
        if self.action == "list" and parse_search(self.request.query_params):
            self.throttle_scope = "transaction_search"
        return super().get_throttles()

    def list(self, request, *args, **kwargs):
        search = parse_search(request.query_params)
        if search is None:
            return super().list(request, *args, **kwargs)
        queryset = self.filter_queryset(self.get_queryset())
        cipher = self.get_serializer_context()["cipher"]
        try:
            ids = matching_ids(queryset, cipher, search)
        except TooManyRows:
            return _too_many_rows()
        page = self.paginate_queryset(ids)
        rows = {row.pk: row for row in queryset.filter(pk__in=page)}
        serializer = self.get_serializer([rows[pk] for pk in page], many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=["post"], url_path="bulk-source")
    def bulk_source(self, request):
        """Move many transactions to another data source. As with bulk-category, ids that aren't
        the caller's come back as "missing". "skipped" counts rows the target already holds."""
        serializer = BulkSourceSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        ids = set(serializer.validated_data["transactions"])

        mine = Transaction.objects.filter(user=request.user, id__in=ids)
        found = set(mine.values_list("id", flat=True))
        moved, skipped = move_transactions(
            request.user, mine, serializer.validated_data["data_source"]
        )
        return Response(
            {"moved": moved, "skipped": skipped, "missing": sorted(str(i) for i in ids - found)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="link-candidates", throttle_scope="links")
    def candidates(self, request, pk=None):
        """The transactions this one could be linked to as a transfer."""
        raw_days = request.query_params.get("days", str(DEFAULT_CANDIDATE_DAYS))
        if not raw_days.isdigit() or not 1 <= int(raw_days) <= MAX_CANDIDATE_DAYS:
            raise ValidationError({"days": f"Use 1 to {MAX_CANDIDATE_DAYS}."})
        cipher = self.get_serializer_context()["cipher"]
        try:
            found = link_candidates(request.user, cipher, self.get_object(), int(raw_days))
        except TooManyRows:
            return _too_many_rows()
        return Response(found)

    @action(detail=False, methods=["post"], url_path="bulk-category")
    def bulk_category(self, request):
        """Put many transactions into one category in a single request and one SQL UPDATE.

        Ids that aren't the caller's (or don't exist) are reported back as "missing", never
        updated, and never distinguished from each other, so nothing leaks about other users.
        """
        serializer = BulkCategorySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        ids = set(serializer.validated_data["transactions"])
        category = serializer.validated_data["category"]

        mine = Transaction.objects.filter(user=request.user, id__in=ids)
        found = set(mine.values_list("id", flat=True))
        # .update() skips auto_now, so set updated_at by hand.
        updated = mine.update(category=category, updated_at=timezone.now())
        return Response(
            {"updated": updated, "missing": sorted(str(i) for i in ids - found)},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """Delete many transactions in one request. As with bulk-category, ids that aren't the
        caller's (or don't exist) come back as "missing" and are never touched."""
        serializer = BulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = set(serializer.validated_data["transactions"])

        mine = Transaction.objects.filter(user=request.user, id__in=ids)
        found = set(mine.values_list("id", flat=True))
        _, per_model = mine.delete()  # the count includes cascaded rows; report transactions only
        return Response(
            {
                "deleted": per_model.get(Transaction._meta.label, 0),
                "missing": sorted(str(i) for i in ids - found),
            },
            status=status.HTTP_200_OK,
        )


# --- statement import ---------------------------------------------------------

def _too_many_rows() -> Response:
    detail = "Too many transactions in the period. Pick a shorter date range."
    return Response({"code": "too_many_rows", "detail": detail}, status=status.HTTP_400_BAD_REQUEST)


def _fingerprint(cipher, item: dict) -> bytes:
    return fingerprint_of(
        cipher,
        date=item["date"],
        txn_type=item["txn_type"],
        amount=item["amount"],
        balance=item["balance"],
        description=item["description"],
    )


class ImportProblem(APIException):
    """400 with a machine-readable `code`, so the UI can react (e.g. ask for a password)."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, code: str, detail: str):
        super().__init__({"code": code, "detail": detail})


ELSEWHERE_CHOICES = ("skip", "move", "add")  # for rows another data source already holds


class ImportBase(APIView):
    """Both import endpoints are stateless: the file (and password) arrive with every
    call and are never stored. Only the commit step writes to the database."""

    parser_classes = [MultiPartParser]
    throttle_scope = "import"

    def target_source(self, request):
        """The data source the file goes into. With none named: the user's first one."""
        raw = request.data.get("data_source")
        if not raw:
            return first_source(request.user)
        source = get_source(request.user, raw)
        if source is None:
            raise ImportProblem("invalid_source", "That data source doesn't exist.")
        return source

    def load(self, request):
        """Validate the upload and parse it.
        Returns (rows, header_index, detected_mapping, parsed, errors)."""
        file = request.FILES.get("file")
        if file is None:
            raise ImportProblem("missing_file", "Upload a file in the 'file' field.")
        if file.size > MAX_UPLOAD_BYTES:
            raise ImportProblem("file_too_large", "The file is larger than 4 MB.")

        try:
            rows = read_statement(file, file.name, request.data.get("password") or None)
        except PasswordRequired:
            raise ImportProblem("password_required", "This file is password-protected.")
        except WrongPassword:
            raise ImportProblem("wrong_password", "That password is incorrect.")
        except ImportFileError as exc:
            raise ImportProblem("invalid_file", str(exc))

        header_index, detected = detect_header(rows)
        if header_index is None:
            raise ImportProblem("no_header", "Couldn't find the header row of the statement.")

        mapping = detected
        if request.data.get("mapping"):
            try:
                mapping = json.loads(request.data["mapping"])
            except json.JSONDecodeError:
                raise ImportProblem("invalid_mapping", "mapping must be valid JSON.")
            if not isinstance(mapping, dict):
                raise ImportProblem("invalid_mapping", "mapping must be a JSON object.")

        try:
            parsed, errors = parse_rows(rows, header_index, mapping)
        except ImportFileError as exc:
            raise ImportProblem("invalid_mapping", str(exc))
        return rows, header_index, detected, parsed, errors


class ImportPreviewView(ImportBase):
    """Nothing is written. Shows how the columns were detected plus a sample.
    Its own, looser rate limit: the page asks again after every column-mapping change."""

    throttle_scope = "import_preview"

    def post(self, request):
        rows, header_index, detected, parsed, errors = self.load(request)
        source = self.target_source(request)
        cipher = UserCipher(request.user)
        fingerprints = {_fingerprint(cipher, item) for item in parsed}
        held = where_held(request.user, fingerprints)
        here = sum(source.pk in sources for sources in held.values())
        elsewhere = Counter(
            other
            for sources in held.values()
            if source.pk not in sources
            for other in sources
        )
        names = {s.pk: s.name for s in sources_for(request.user, cipher)}
        return Response(
            {
                "headers": ["" if c is None else str(c) for c in rows[header_index]],
                "detected_mapping": detected,
                "sample": [
                    {
                        "row": item["row"],
                        "date": item["date"].isoformat(),
                        "txn_type": item["txn_type"],
                        "amount": str(item["amount"]),  # strings: the UI never sees floats
                        "balance": None if item["balance"] is None else str(item["balance"]),
                        "name": item["name"],
                        "description": item["description"],
                    }
                    for item in parsed[:PREVIEW_SAMPLE_ROWS]
                ],
                "row_count": len(parsed),
                "error_count": len(errors),
                "errors": errors[:PREVIEW_MAX_ERRORS],
                "duplicates": here,
                "elsewhere": [
                    {"data_source": str(pk), "name": names[pk], "count": count}
                    for pk, count in elsewhere.most_common()
                ],
            }
        )


class ImportView(ImportBase):
    def post(self, request):
        *_, parsed, errors = self.load(request)
        source = self.target_source(request)
        elsewhere = request.data.get("elsewhere") or "skip"
        if elsewhere not in ELSEWHERE_CHOICES:
            raise ImportProblem("invalid_choice", "elsewhere must be skip, move or add.")

        cipher = UserCipher(request.user)  # one DEK load for the whole import
        category = get_default_category(request.user)  # "Others"
        imported = duplicates = skipped = moved = 0
        fingerprints = [_fingerprint(cipher, item) for item in parsed]
        held = where_held(request.user, set(fingerprints))
        to_move = set()

        with transaction.atomic():
            for item, fingerprint in zip(parsed, fingerprints, strict=True):
                holders = held.get(fingerprint, ())
                if source.pk in holders:
                    duplicates += 1
                    continue
                if holders and elsewhere != "add":
                    if elsewhere == "move":
                        to_move.add(fingerprint)
                    else:
                        skipped += 1
                    continue
                try:
                    # Savepoint per row: on Postgres an IntegrityError would otherwise
                    # poison the outer transaction and abort every later insert.
                    with transaction.atomic():
                        create_transaction(
                            cipher,
                            request.user,
                            date=item["date"],
                            txn_type=item["txn_type"],
                            name=item["name"],
                            description=item["description"],
                            amount=item["amount"],
                            balance=item["balance"],
                            category=category,
                            data_source=source,
                        )
                    imported += 1
                except IntegrityError:  # the same row twice in one file
                    duplicates += 1
            if to_move:
                rows = Transaction.objects.filter(user=request.user, fingerprint__in=to_move)
                moved, _ = move_transactions(request.user, rows, source)

        return Response(
            {
                "imported": imported,
                "duplicates": duplicates,
                "moved": moved,
                "skipped": skipped,
                "errors": errors,
            }
        )


class LinkView(APIView):
    """POST /api/transactions/links/: the user says these two rows are one transfer."""

    throttle_scope = "links"

    def post(self, request):
        serializer = LinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            link = link_transactions(
                request.user, UserCipher(request.user), values["first"], values["second"]
            )
        except LinkError as error:
            return Response(
                {"code": error.code, "detail": error.detail}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {"id": str(link.pk), "debit": str(link.debit_id), "credit": str(link.credit_id)},
            status=status.HTTP_201_CREATED,
        )


class BulkLinkView(APIView):
    """POST /api/transactions/links/bulk/: approve many suggested transfers at once."""

    throttle_scope = "links"

    def post(self, request):
        serializer = BulkLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            link_many(
                request.user, UserCipher(request.user), serializer.validated_data["pairs"]
            )
        )


class LinkDetailView(APIView):
    """DELETE /api/transactions/links/{id}/: the two rows count on their own again."""

    throttle_scope = "links"

    def delete(self, request, pk):
        deleted, _ = TransferLink.objects.filter(user=request.user, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)


class TransferSuggestionsView(APIView):
    """GET /api/transactions/transfer-suggestions/: likely transfers for the user to approve."""

    throttle_scope = "links"

    def get(self, request):
        today = timezone.localdate()
        start, end = today - timedelta(days=SUGGESTION_RANGE_DAYS), today
        for param, name in (("from", "start"), ("to", "end")):
            if param in request.query_params:
                parsed = parse_date(request.query_params[param])
                if parsed is None:
                    raise ValidationError({param: "Use YYYY-MM-DD."})
                start, end = (parsed, end) if name == "start" else (start, parsed)
        if start > end or (end - start).days > SUGGESTION_RANGE_DAYS:
            raise ValidationError({"from": f"Use a range of {SUGGESTION_RANGE_DAYS} days or less."})
        try:
            return Response(suggest_transfers(request.user, UserCipher(request.user), start, end))
        except TooManyRows:
            return _too_many_rows()
