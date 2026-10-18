from django.apps import AppConfig


class VaultConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'vault'

    def ready(self):
        # Runs once per process (gunicorn worker, manage.py command). A bad key then stops the
        # deploy at its health check, while the previous version keeps serving.
        from .services import check_keys

        check_keys()
