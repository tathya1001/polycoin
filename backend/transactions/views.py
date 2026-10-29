import json
import uuid

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
from vault.services import UserCipher

from .importer import (
    ImportFileError,
    PasswordRequired,
    WrongPassword,
    detect_header,
    parse_rows,
)
from .models import Transaction
from .readers import read_statement
from .serializers import BulkCategorySerializer, TransactionSerializer
from .services import create_transaction

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
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
    """No create: transactions only arrive through the statement import."""

    queryset = Transaction.objects.select_related("category")
    serializer_class = TransactionSerializer
    pagination_class = TransactionPagination
    # No PUT. POST only reaches the bulk-category action: there is no create.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

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

        if "category" in params:
            try:
                qs = qs.filter(category_id=uuid.UUID(params["category"]))
            except ValueError:
                raise ValidationError({"category": "Not a valid id."})

        return qs  # Meta.ordering already gives -date

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


# --- statement import ---------------------------------------------------------

class ImportProblem(APIException):
    """400 with a machine-readable `code`, so the UI can react (e.g. ask for a password)."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, code: str, detail: str):
        super().__init__({"code": code, "detail": detail})


class ImportBase(APIView):
    """Both import endpoints are stateless: the file (and password) arrive with every
    call and are never stored. Only the commit step writes to the database."""

    parser_classes = [MultiPartParser]
    throttle_scope = "import"

    def load(self, request):
        """Validate the upload and parse it.
        Returns (rows, header_index, detected_mapping, parsed, errors)."""
        file = request.FILES.get("file")
        if file is None:
            raise ImportProblem("missing_file", "Upload a file in the 'file' field.")
        if file.size > MAX_UPLOAD_BYTES:
            raise ImportProblem("file_too_large", "The file is larger than 5 MB.")

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
            }
        )


class ImportView(ImportBase):
    def post(self, request):
        *_, parsed, errors = self.load(request)

        cipher = UserCipher(request.user)  # one DEK load for the whole import
        category = get_default_category(request.user)  # "Others"
        imported = duplicates = 0

        with transaction.atomic():
            for item in parsed:
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
                        )
                    imported += 1
                except IntegrityError:  # fingerprint already stored: re-imported row
                    duplicates += 1

        return Response({"imported": imported, "duplicates": duplicates, "errors": errors})
