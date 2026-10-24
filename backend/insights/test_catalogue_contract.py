"""The frontend's copy of the catalogue (its Vitest tests use it) must match the real one.

The editor's rules come from catalogue(), so a stale copy would let the frontend tests pass
against rules the backend no longer has. The copy sits in the frontend tree, which CI checks out
along with this one; a container that mounts only the backend skips this test.

To refresh the copy after changing the catalogue, from the repository root:

    docker compose exec -T backend python -c "import django,json,os;\
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');django.setup();\
from insights.spec import catalogue;print(json.dumps(catalogue(),indent=1))" \
> frontend/lib/__fixtures__/catalogue.json
"""

import json
from pathlib import Path

import pytest

from insights.spec import catalogue

COPY = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "__fixtures__" / "catalogue.json"


@pytest.mark.skipif(not COPY.exists(), reason="the frontend tree isn't available here")
def test_the_frontend_copy_of_the_catalogue_is_current():
    assert json.loads(COPY.read_text(encoding="utf-8")) == catalogue()
