"""HTTP endpoints for the Data Backup File.

    GET  /api/backup/           the user's backup file, as a download
    POST /api/backup/restore/   merge a backup file into the account (multipart field "file")

Neither asks for the password: the file can only be opened by this account, and a restore only
adds what is missing. Errors share the app's {"code", "detail"} body.
"""

from django.conf import settings
from django.db import IntegrityError
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .errors import BackupError
from .fileformat import too_large
from .services import build_backup, file_name, restore_backup


class BackupProblem(APIException):
    """400 with a machine-readable `code` the page can react to."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, code: str, detail: str):
        super().__init__({"code": code, "detail": detail})


class BackupView(APIView):
    """Turns BackupError into the {code, detail} body."""

    throttle_scope = "backup"

    def handle_exception(self, exc):
        if isinstance(exc, BackupError):
            exc = BackupProblem(exc.code, exc.detail)
        return super().handle_exception(exc)


class DownloadView(BackupView):
    def get(self, request):
        content = build_backup(request.user)
        response = HttpResponse(content, content_type="application/octet-stream")
        name = file_name(timezone.localdate())
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response


class RestoreView(BackupView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get("file")
        if file is None:
            raise BackupError("missing_file", "Upload the backup file in the 'file' field.")
        if file.size > settings.BACKUP_MAX_BYTES:
            raise too_large()  # checked before reading it into memory
        try:
            counts = restore_backup(request.user, file.read())
        except IntegrityError:
            # Something else changed the account at the same moment. Nothing was restored.
            return Response(
                {
                    "detail": "Your data changed during the restore. Nothing was restored. Try again."
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(counts)
