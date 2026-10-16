from django.conf import settings
from django.db import connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def ping(request):
    """Liveness only. It never touches the database, so keep-alive pings and Render's health
    checks don't keep Neon's compute awake and burn its monthly free hours."""
    return Response({"status": "ok", "commit": settings.GIT_COMMIT})


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return Response({"status": "ok", "database": "ok"}, status=200)
    except Exception:
        return Response({"status": "error", "database": "error"}, status=503)
