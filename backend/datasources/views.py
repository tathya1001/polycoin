from datetime import date

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.mixins import OwnedQuerysetMixin
from insights.services import (
    opening_balances,
    panels_using_source,
    rename_source_in_panels,
    source_labels,
)
from transactions.index import ids, keep, rows_of, source_spans
from transactions.models import TransferLink
from transactions.services import remove_source
from vault.services import UserCipher

from .models import DataSource
from .serializers import RemoveSourceSerializer, ReorderSerializer, WriteSourceSerializer
from .services import (
    SourceError,
    create_source,
    get_source,
    rename_source,
    reorder_sources,
    sources_for,
)


def _problem(error: SourceError) -> Response:
    status_code = status.HTTP_409_CONFLICT if error.code == "name_taken" else 400
    return Response({"code": error.code, "detail": error.detail}, status=status_code)


def _as_json(source, facts: dict | None = None, balance=None) -> dict:
    facts = facts or {}
    first, last = facts.get("first"), facts.get("last")
    return {
        "id": str(source.pk),
        "name": source.name,
        "color": source.color,
        "position": source.position,
        "transactions": facts.get("count", 0),
        "first_date": first.isoformat() if first else None,
        "last_date": last.isoformat() if last else None,
        "balance": None if balance is None else f"{balance:.2f}",
    }


class DataSourceViewSet(OwnedQuerysetMixin, viewsets.GenericViewSet):
    """The list is a plain array, like categories: a user has at most a few dozen."""

    queryset = DataSource.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]
    throttle_scope = None  # only `remove` has one

    def list(self, request):
        cipher = UserCipher(request.user)
        sources = sources_for(request.user, cipher)
        # Each source's row count and first and last date, from the decrypted cores.
        facts = source_spans(rows_of(request.user))
        labels = source_labels(request.user, cipher)
        balances = opening_balances(request.user, cipher, date.max, labels)
        return Response(
            [
                _as_json(s, facts.get(s.pk), balances.get(labels[s.pk].key))
                for s in sources
            ]
        )

    def create(self, request):
        serializer = WriteSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            source = create_source(
                request.user, UserCipher(request.user), values.get("name"), values.get("color")
            )
        except SourceError as error:
            return _problem(error)
        return Response(_as_json(source), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        source = self.get_object()
        serializer = WriteSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        cipher = UserCipher(request.user)
        names = {s.pk: s.name for s in sources_for(request.user, cipher)}
        source.name = names[source.pk]
        try:
            with transaction.atomic():
                if "name" in values:
                    old, source.name = source.name, rename_source(source, cipher, values["name"])
                    rename_source_in_panels(request.user, cipher, old, source.name)
                if "color" in values:
                    source.color = values["color"]
                    DataSource.objects.filter(pk=source.pk).update(color=source.color)
        except SourceError as error:
            return _problem(error)
        return Response(_as_json(source))

    @action(detail=True, methods=["get"])
    def usage(self, request, pk=None):
        """What deleting this source would touch, for the confirmation."""
        source = self.get_object()
        cipher = UserCipher(request.user)
        name = next(s.name for s in sources_for(request.user, cipher) if s.pk == source.pk)
        held = set(ids(keep(rows_of(request.user), sources=[source.pk])))
        links = TransferLink.objects.filter(user=request.user).values_list("first_id", "second_id")
        return Response(
            {
                "transactions": len(held),
                "links": sum(1 for first, second in links if first in held or second in held),
                "panels": panels_using_source(request.user, cipher, str(source.pk), name),
            }
        )

    @action(detail=True, methods=["post"], throttle_scope="destructive")
    def remove(self, request, pk=None):
        source = self.get_object()
        serializer = RemoveSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_id = serializer.validated_data.get("move_to")
        target = None
        if target_id is not None:
            target = get_source(request.user, target_id)
            if target is None or target.pk == source.pk:
                return Response(
                    {"code": "invalid_target", "detail": "Choose another data source."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            return Response(remove_source(request.user, source, target))
        except SourceError as error:
            return _problem(error)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reorder_sources(request.user, serializer.validated_data["order"])
        except SourceError as error:
            return _problem(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
