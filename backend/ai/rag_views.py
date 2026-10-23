"""HTTP endpoints for "Ask your transactions".

The browser embeds with the user's own Ollama and sends vectors here; the server indexes,
searches and builds the prompt, and never calls a model.

    GET    /api/ai/rag/status/?model=&digest=          how much is indexed, and the model profile
    GET    /api/ai/rag/pending/?model=&digest=&limit=  the next rows to embed
    POST   /api/ai/rag/vectors/                        store one embedded batch
    POST   /api/ai/rag/ask/                            search, then the prompt for the browser
    DELETE /api/ai/rag/index/                          "Clear index"

Errors share the app's {"code", "detail"} body (like ImportProblem and InsightsProblem). With
RAG_ENABLED off, every endpoint but status and clear answers 503 rag_disabled.
"""

import math

from django.conf import settings
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .rag import index, service
from .rag.errors import RagError

MAX_QUESTION = 300  # characters

STATUS_CODES = {"rag_disabled": status.HTTP_503_SERVICE_UNAVAILABLE}


class RagProblem(APIException):
    """400 (or 503 for rag_disabled) with a machine-readable `code` the page can react to."""

    def __init__(self, code: str, detail: str):
        self.status_code = STATUS_CODES.get(code, status.HTTP_400_BAD_REQUEST)
        super().__init__({"code": code, "detail": detail})


class VectorField(serializers.Field):
    """A list of finite numbers, checked in one loop.

    A ListField of FloatFields runs a field object per number; a full index batch is 100 x 768
    numbers, which would cost seconds of Render's 0.1 CPU. The strict JSON parser already refuses
    NaN and Infinity; booleans are refused here, since JSON true would otherwise count as 1.
    """

    default_error_messages = {
        "invalid": "Must be a list of numbers.",
        "size": "Must have between 1 and {max} numbers.",
        "finite": "Must contain only finite numbers.",
    }

    def to_internal_value(self, data):
        if not isinstance(data, list):
            self.fail("invalid")
        if not 1 <= len(data) <= settings.RAG_MAX_DIMS:
            self.fail("size", max=settings.RAG_MAX_DIMS)
        for value in data:
            if type(value) not in (int, float):  # not isinstance: bool is an int subclass
                self.fail("invalid")
            if not math.isfinite(value):
                self.fail("finite")
        return [float(value) for value in data]

    def to_representation(self, value):
        return value


class ModelSerializer(serializers.Serializer):
    """Which embedding model the index belongs to: the Ollama name and its digest."""

    model = serializers.CharField(max_length=100)
    digest = serializers.CharField(max_length=80)


class PendingSerializer(ModelSerializer):
    limit = serializers.IntegerField(min_value=1, required=False)

    def validate_limit(self, value):
        return min(value, settings.RAG_INDEX_BATCH)


class VectorItemSerializer(serializers.Serializer):
    transaction = serializers.UUIDField()
    version = serializers.CharField(max_length=40)
    vector = VectorField()


class VectorsSerializer(ModelSerializer):
    items = serializers.ListField(child=VectorItemSerializer(), min_length=1)

    def validate_items(self, items):
        if len(items) > settings.RAG_INDEX_BATCH:
            raise serializers.ValidationError(f"At most {settings.RAG_INDEX_BATCH} items.")
        return items


class AskSerializer(ModelSerializer):
    question = serializers.CharField(max_length=MAX_QUESTION)  # trimmed; blank is refused
    vector = VectorField()
    filters = serializers.DictField(required=False, allow_null=True)
    use_question_period = serializers.BooleanField(default=True)


class RagView(APIView):
    """Turns RagError into the {code, detail} body and applies the kill switch."""

    allowed_when_disabled = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # authentication and throttles come first
        if not settings.RAG_ENABLED and not self.allowed_when_disabled:
            raise RagError("rag_disabled", "Ask your transactions is turned off for now.")

    def handle_exception(self, exc):
        if isinstance(exc, RagError):
            exc = RagProblem(exc.code, exc.detail)
        return super().handle_exception(exc)

    @staticmethod
    def valid(serializer_class, data) -> dict:
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class StatusView(RagView):
    """Coverage and the model profile. Works when turned off, so the page can explain why."""

    throttle_scope = "ai_light"
    allowed_when_disabled = True

    def get(self, request):
        data = self.valid(ModelSerializer, request.query_params)
        return Response(index.status(request.user, data["model"], data["digest"]))


class PendingView(RagView):
    """The next rows to embed, with their text. Holds decrypted text: never cache or log it."""

    throttle_scope = "rag_index"

    def get(self, request):
        data = self.valid(PendingSerializer, request.query_params)
        limit = data.get("limit", settings.RAG_INDEX_BATCH)
        return Response(index.pending(request.user, data["model"], data["digest"], limit))


class VectorsView(RagView):
    """Stores one embedded batch from `pending`."""

    throttle_scope = "rag_index"

    def post(self, request):
        data = self.valid(VectorsSerializer, request.data)
        items = [{**item, "transaction": str(item["transaction"])} for item in data["items"]]
        return Response(index.store_vectors(request.user, data["model"], data["digest"], items))


class AskView(RagView):
    """Searches and returns the prompt; the browser sends it to the user's own Ollama."""

    throttle_scope = "rag_ask"

    def post(self, request):
        data = self.valid(AskSerializer, request.data)
        return Response(
            service.ask(
                request.user,
                question=data["question"],
                vector=data["vector"],
                model=data["model"],
                digest=data["digest"],
                filters=data.get("filters"),
                use_question_period=data["use_question_period"],
            )
        )


class IndexView(RagView):
    """ "Clear index": deletes the user's whole index. Always allowed, even when turned off,
    because deleting your own data must never depend on a feature switch."""

    throttle_scope = "destructive"
    allowed_when_disabled = True

    def delete(self, request):
        index.clear(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
