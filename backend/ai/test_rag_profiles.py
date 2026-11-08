import pytest

from ai.rag.profiles import (
    PROFILES,
    TEXT_VERSION,
    UNTUNED,
    base_name,
    profile_for,
    text_version_for,
)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("nomic-embed-text:latest", "nomic-embed-text"),
        ("nomic-embed-text", "nomic-embed-text"),
        ("  NOMIC-EMBED-TEXT:V1.5 ", "nomic-embed-text"),
        ("localhost:5000/nomic-embed-text", "localhost:5000/nomic-embed-text"),  # registry port
        ("localhost:5000/nomic-embed-text:latest", "localhost:5000/nomic-embed-text"),
        ("someone/nomic-embed-text:latest", "someone/nomic-embed-text"),
        (":latest", ":latest"),
    ],
)
def test_base_name_strips_only_a_trailing_tag(name, expected):
    assert base_name(name) == expected


def test_nomic_gets_its_task_prefixes_whatever_its_tag():
    for name in ("nomic-embed-text", "nomic-embed-text:latest", "nomic-embed-text:v1.5"):
        profile = profile_for(name)
        assert profile.doc_prefix == "search_document: "
        assert profile.query_prefix == "search_query: "


@pytest.mark.parametrize("name", ["mxbai-embed-large:latest", "someone/nomic-embed-text", ""])
def test_a_model_without_a_profile_is_untuned_with_no_prefixes(name):
    profile = profile_for(name)
    assert profile is UNTUNED
    assert (profile.doc_prefix, profile.query_prefix, profile.tuned) == ("", "", False)


def test_a_profile_counts_as_tuned_only_once_it_has_a_threshold():
    assert all(
        profile.tuned == (profile.min_similarity is not None) for profile in PROFILES.values()
    )
    assert not UNTUNED.tuned


def test_profile_keys_are_base_names():
    assert all(base_name(key) == key for key in PROFILES)


@pytest.mark.parametrize(
    "name, doc_prefix, query_prefix, threshold",
    [
        ("embeddinggemma:latest", "title: none | text: ", "task: search result | query: ", 0.355),
        ("bge-m3:latest", "", "", 0.525),
    ],
)
def test_the_benchmarked_models_are_tuned(name, doc_prefix, query_prefix, threshold):
    profile = profile_for(name)
    assert (profile.doc_prefix, profile.query_prefix) == (doc_prefix, query_prefix)
    assert profile.tuned and profile.min_similarity == threshold


def test_text_version_rises_with_a_profiles_revision_only():
    assert text_version_for("nomic-embed-text:latest") == TEXT_VERSION
    assert text_version_for("bge-m3:latest") == TEXT_VERSION  # no prefix: old documents stay
    assert text_version_for("unknown-model") == TEXT_VERSION
    # embeddinggemma gained a prefix with its profile, so documents embedded without it are stale.
    assert text_version_for("embeddinggemma:latest") == TEXT_VERSION + 1000


def test_text_versions_fit_the_stored_column():
    assert all(TEXT_VERSION + 1000 * p.revision <= 32767 for p in PROFILES.values())
