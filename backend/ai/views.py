from django.conf import settings
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .client import AIError, OllamaClient

# AIError.code -> HTTP status. Ollama being down or misbehaving is not the caller's fault;
# anything not listed here (unknown model, no embedder installed, ...) is fixable by them.
STATUS_BY_CODE = {
    "ollama_unreachable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "embedding_failed": status.HTTP_502_BAD_GATEWAY,
    "dimension_mismatch": status.HTTP_502_BAD_GATEWAY,
}


class AIProblem(APIException):
    """Same {"code", "detail"} body as ImportProblem, so the UI can react to the code."""

    def __init__(self, error: AIError):
        super().__init__({"code": error.code, "detail": error.detail})
        self.status_code = STATUS_BY_CODE.get(error.code, status.HTTP_400_BAD_REQUEST)


def get_client() -> OllamaClient:
    """The one place the client is built (tests replace it with a fake). It takes no
    arguments on purpose: the Ollama address comes from settings, never from a request."""
    return OllamaClient()

class AIBase(APIView):
    def handle_exception(self, exc):
        # DRF's hook for turning exceptions into responses: AIError becomes AIProblem.
        if isinstance(exc, AIError):
            exc = AIProblem(exc)
        return super().handle_exception(exc)

class PreviewRequestSerializer(serializers.Serializer):
    model = serializers.CharField(max_length=200)


class DecisionSerializer(serializers.Serializer):
    transaction = serializers.UUIDField()
    category = serializers.UUIDField()


class ApplyRequestSerializer(serializers.Serializer):
    decisions = DecisionSerializer(many=True, allow_empty=False, max_length=settings.AI_MAX_RUN)

class ModelsView(AIBase):
    """Embedding models installed in the user's own Ollama."""

    throttle_scope = "ai_light"

    def get(self, request):
        return Response({"models": get_client().list_models()})


class PreviewView(AIBase):
    """Dry run: proposals and scores for the user's uncategorised rows. Writes nothing."""

    throttle_scope = "ai"  # the only endpoint that embeds, so it has the tight budget

    def post(self, request):
        data = PreviewRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        client = get_client()
        services.validate_model(client, data.validated_data["model"])
        return Response(services.build_proposals(request.user, data.validated_data["model"], client))


class ApplyView(AIBase):
    """Commits the decisions the user saw. Makes no Ollama call."""

    throttle_scope = "ai_light"

    def post(self, request):
        data = ApplyRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(services.apply_decisions(request.user, data.validated_data["decisions"]))
