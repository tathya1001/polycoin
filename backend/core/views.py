from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return Response({"status": "ok", "database": "ok"}, status=200)
    except Exception:
        return Response({"status": "error", "database": "error"}, status=503)
