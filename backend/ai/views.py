from django.conf import settings
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services

# The server never talks to Ollama: the browser embeds a prepared run with the user's own
# Ollama and scores it itself (frontend/lib/ollama.ts, lib/scoring.ts), then applies here.


class DecisionSerializer(serializers.Serializer):
    transaction = serializers.UUIDField()
    category = serializers.UUIDField()


class ApplyRequestSerializer(serializers.Serializer):
    decisions = DecisionSerializer(many=True, allow_empty=False, max_length=settings.AI_MAX_RUN)


class PrepareView(APIView):
    """The texts, candidates and thresholds for a run in the browser. Writes nothing."""

    throttle_scope = "ai"  # decrypts the most rows of any AI endpoint, so the tight budget

    def get(self, request):
        return Response(services.prepare_run(request.user))


class ApplyView(APIView):
    """Commits the decisions the user saw."""

    throttle_scope = "ai_light"

    def post(self, request):
        data = ApplyRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(services.apply_decisions(request.user, data.validated_data["decisions"]))
