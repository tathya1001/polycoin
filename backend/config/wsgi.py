"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()

# Django loads the URLconf, and with it every view, on the first request. Loading it here moves
# that cost to boot, so no user waits for it; the RAG views pull in langchain-core, numpy and
# rank-bm25, which take about 6 s at Render's 0.1 CPU. gunicorn runs this once in the master
# (start.sh uses --preload) and forks the workers from it. Only gunicorn imports this file, so
# management commands and tests start as fast as before.
from django.db import connections  # noqa: E402
from django.urls import get_resolver  # noqa: E402

get_resolver().url_patterns
# A connection opened before the fork would be shared by every worker. Nothing above opens one
# today; closing them keeps it that way if an import ever does.
connections.close_all()
