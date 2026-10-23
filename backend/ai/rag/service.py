"""One ask, end to end on the server: search, then the answer context, then one log line.

The view only parses the request; everything an ask does lives here, so it is testable without
HTTP and reusable by other callers, such as an agent tool.
"""

import logging
from datetime import date

from django.utils import timezone

from .answer import build_answer
from .profiles import PROMPT_VERSION, profile_for
from .retriever import EncryptedHybridRetriever

logger = logging.getLogger(__name__)


def ask(
    user,
    *,
    question: str,
    vector: list[float],
    model: str,
    digest: str,
    filters: dict | None = None,
    use_question_period: bool = True,
    today: date | None = None,
) -> dict:
    """The ask response: {prompt_version, profile, period, coverage, summary, sources,
    messages | None, options}. Raises RagError for a request the services refuse.

    Logs one line per ask with counts and milliseconds only: never the question, the
    sources or anything else the user wrote.
    """
    today = today or timezone.localdate()
    found = EncryptedHybridRetriever(
        user=user,
        model=model,
        digest=digest,
        query_vector=vector,
        filters=filters,
        use_question_period=use_question_period,
        today=today,
    )
    result = found.search(question)
    response = build_answer(user, question, result, today)
    response["profile"] = profile_for(model).as_dict()

    stats = result.stats
    logger.info(
        "rag ask: prompt=%s documents=%d keyword=%d vector=%d matches=%d sources=%d "
        "period=%s ms=%s",
        PROMPT_VERSION,
        stats["documents"],
        stats["keyword"],
        stats["vector"],
        stats["matches"],
        len(response["sources"]),
        result.period["source"],
        " ".join(f"{stage}:{ms:.0f}" for stage, ms in stats["ms"].items()),
    )
    return response
