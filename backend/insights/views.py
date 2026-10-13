from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, MethodNotAllowed
from rest_framework.response import Response
from rest_framework.views import APIView

from core.mixins import OwnedQuerysetMixin
from vault.services import UserCipher

from . import services, spec
from .models import MAX_PANELS_PER_DASHBOARD, Dashboard, Panel
from .serializers import (
    DashboardDetailSerializer,
    DashboardSerializer,
    LayoutItemSerializer,
    PanelCreateSerializer,
    PanelSerializer,
    PanelUpdateSerializer,
)

MAX_QUERIES = 30  # one per panel; matches the cap on panels per dashboard
UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


class InsightsProblem(APIException):
    """Same {"code", "detail"} body as ImportProblem and AIProblem."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, error: spec.SpecError):
        super().__init__({"code": error.code, "detail": error.detail})


class InsightsBase(APIView):
    throttle_scope = "insights"

    def handle_exception(self, exc):
        if isinstance(exc, spec.SpecError):
            exc = InsightsProblem(exc)
        return super().handle_exception(exc)


class QueryItemSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=64)
    spec = serializers.DictField()


class QueryRequestSerializer(serializers.Serializer):
    filters = serializers.DictField(required=False, allow_null=True)
    queries = QueryItemSerializer(many=True, allow_empty=False, max_length=MAX_QUERIES)

    def validate_queries(self, queries):
        keys = [query["key"] for query in queries]
        if len(set(keys)) != len(keys):
            raise serializers.ValidationError("Query keys must be unique.")
        return queries


class FieldsView(InsightsBase):
    """The catalogue the editor builds its dropdowns from."""

    def get(self, request):
        return Response(spec.catalogue())


class QueryView(InsightsBase):
    """Every panel's spec in, every panel's result out, with the rows decrypted once."""

    def post(self, request):
        data = QueryRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        results = services.run_queries(
            request.user,
            data.validated_data.get("filters") or {},
            data.validated_data["queries"],
        )
        return Response({"results": results})


class DashboardViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    """The user's dashboards (tabs). A single dashboard also carries its panels."""

    queryset = Dashboard.objects.all()
    throttle_scope = "insights"
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def update(self, request, *args, **kwargs):
        # PUT is only open for the layout action. On a dashboard itself only PATCH is allowed.
        if not kwargs.get("partial"):
            raise MethodNotAllowed(request.method)
        return super().update(request, *args, **kwargs)

    def get_serializer_class(self):
        return DashboardDetailSerializer if self.action == "retrieve" else DashboardSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["cipher"] = UserCipher(self.request.user)  # one DEK query per request
        return context

    def get_queryset(self):
        queryset = super().get_queryset()  # already scoped to request.user
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("panels")  # one query, not one per dashboard
        return queryset

    # Panels belong to a dashboard, so they live under it. get_object() does the ownership
    # check (404 for someone else's dashboard), so none of these actions needs its own.
    @action(detail=True, methods=["post"], url_path="panels")
    def add_panel(self, request, pk=None):
        dashboard = self.get_object()
        context = {**self.get_serializer_context(), "dashboard": dashboard}
        serializer = PanelCreateSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        panel = serializer.save()
        body = PanelSerializer(panel, context=context).data
        return Response(body, status=status.HTTP_201_CREATED)

    # One action for both methods: two actions sharing a URL would leave the second unreachable.
    @action(detail=True, methods=["patch", "delete"], url_path=rf"panels/(?P<panel_id>{UUID_RE})")
    def panel(self, request, pk=None, panel_id=None):
        dashboard = self.get_object()
        panel = get_object_or_404(dashboard.panels, pk=panel_id)
        if request.method == "DELETE":
            panel.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        context = self.get_serializer_context()
        serializer = PanelUpdateSerializer(panel, data=request.data, partial=True, context=context)
        serializer.is_valid(raise_exception=True)
        panel = serializer.save()
        return Response(PanelSerializer(panel, context=context).data)

    @action(detail=True, methods=["put"], url_path="layout")
    def layout(self, request, pk=None):
        """Save where every moved or resized panel now sits, all or nothing."""
        dashboard = self.get_object()
        serializer = LayoutItemSerializer(
            data=request.data, many=True, allow_empty=False, max_length=MAX_PANELS_PER_DASHBOARD
        )
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data

        ids = [item["panel"] for item in items]
        if len(set(ids)) != len(ids):
            return Response(
                {"detail": "Each panel can appear only once."}, status=status.HTTP_400_BAD_REQUEST
            )
        panels = {panel.id: panel for panel in dashboard.panels.filter(id__in=ids)}
        if len(panels) != len(ids):  # an id from another dashboard (or nowhere) was in the list
            return Response(
                {"detail": "Every panel must belong to this dashboard."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for item in items:
            panel = panels[item["panel"]]
            panel.x, panel.y, panel.w, panel.h = item["x"], item["y"], item["w"], item["h"]
        with transaction.atomic():
            Panel.objects.bulk_update(panels.values(), ["x", "y", "w", "h"])
        return Response(status=status.HTTP_204_NO_CONTENT)
