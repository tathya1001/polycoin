"""HTTP endpoints for the AI panel builder.

The browser relays every model call to the user's own Ollama; the server runs the workflow and
never calls a model. The conversation's state travels in a sealed token, so nothing is stored.

    GET  /api/ai/agent/status/   whether it is on, the prompt version and the limits
    POST /api/ai/agent/turn/     a message: {message, token?, dashboard, embed?}
    POST /api/ai/agent/step/     the model's answer: {token, reply | vector | skip}

Both POSTs answer {"status": "needs_model", "token", "progress", "request"} (ask the model, then
send a step) or {"status": "done", "token", "outcome"}. Errors share the app's {"code", "detail"}
body. With AGENT_ENABLED off, turn and step answer 503 agent_disabled.
"""

from django.conf import settings
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .agent import service
from .agent.errors import AgentError
from .agent.prompts import PROMPT_VERSION
from .agent.schema import MAX_REPLY_CHARS
from .rag_views import ModelSerializer, VectorField

MAX_MESSAGE = 300  # characters

STATUS_CODES = {"agent_disabled": status.HTTP_503_SERVICE_UNAVAILABLE}


class AgentProblem(APIException):
    """400 (or 503 for agent_disabled) with a machine-readable `code` the page can react to."""

    def __init__(self, code: str, detail: str):
        self.status_code = STATUS_CODES.get(code, status.HTTP_400_BAD_REQUEST)
        super().__init__({"code": code, "detail": detail})


class TokenField(serializers.CharField):
    """A sealed token: only its size is checked here; unsealing checks the rest."""

    def __init__(self, **kwargs):
        super().__init__(trim_whitespace=False, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if len(value) > settings.AGENT_MAX_TOKEN_BYTES:
            raise AgentError(
                "token_invalid", "This conversation can't be continued. Start a new one."
            )
        return value


class TurnSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=MAX_MESSAGE)  # trimmed; blank is refused
    token = TokenField(required=False, allow_null=True)
    dashboard = serializers.DictField(required=False, allow_null=True)
    embed = ModelSerializer(required=False, allow_null=True)


class StepSerializer(serializers.Serializer):
    token = TokenField()
    # Not trimmed: it is the model's raw reply, parsed as JSON.
    reply = serializers.CharField(
        max_length=MAX_REPLY_CHARS, required=False, allow_blank=True, trim_whitespace=False
    )
    vector = VectorField(required=False)
    skip = serializers.BooleanField(required=False)

    def validate(self, data):
        given = [name for name in ("reply", "vector") if name in data] + (
            ["skip"] if data.get("skip") else []
        )
        if len(given) != 1:
            raise serializers.ValidationError("Send exactly one of reply, vector or skip.")
        return data


class AgentView(APIView):
    """Turns AgentError into the {code, detail} body and applies the kill switch."""

    allowed_when_disabled = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # authentication and throttles come first
        if not settings.AGENT_ENABLED and not self.allowed_when_disabled:
            raise AgentError("agent_disabled", "The AI panel builder is turned off for now.")

    def handle_exception(self, exc):
        if isinstance(exc, AgentError):
            exc = AgentProblem(exc.code, exc.detail)
        return super().handle_exception(exc)

    @staticmethod
    def valid(serializer_class, data) -> dict:
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class StatusView(AgentView):
    """Works when turned off, so the page can explain why the button is missing."""

    throttle_scope = "ai_light"
    allowed_when_disabled = True

    def get(self, request):
        return Response(
            {
                "enabled": settings.AGENT_ENABLED,
                "prompt_version": PROMPT_VERSION,
                "limits": {
                    "message": MAX_MESSAGE,
                    "reply": MAX_REPLY_CHARS,
                    "turns": settings.AGENT_MAX_TURNS,
                    "steps": settings.AGENT_MAX_STEPS,
                },
            }
        )


class TurnView(AgentView):
    throttle_scope = "agent"

    def post(self, request):
        data = self.valid(TurnSerializer, request.data)
        embed = data.get("embed")
        return Response(
            service.turn(
                request.user,
                message=data["message"],
                token=data.get("token"),
                dashboard=data.get("dashboard"),
                embed=dict(embed) if embed else None,
            )
        )


class StepView(AgentView):
    throttle_scope = "agent"

    def post(self, request):
        data = self.valid(StepSerializer, request.data)
        return Response(
            service.step(
                request.user,
                data["token"],
                reply=data.get("reply"),
                vector=data.get("vector"),
                skip=data.get("skip", False),
            )
        )
