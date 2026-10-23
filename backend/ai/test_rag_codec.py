import struct

import numpy as np
import pytest

from ai.rag import codec


def unit(dims, seed=0):
    vector = np.random.default_rng(seed).standard_normal(dims)
    return vector / np.linalg.norm(vector)


# --- pack / unpack --------------------------------------------------------------


def test_a_payload_round_trips_the_vector_at_float16_and_the_text_exactly():
    vector = unit(768)
    restored, text = codec.unpack(codec.pack(vector, "Tastybites Cafe UPI tastybites ₹ café"))

    assert text == "Tastybites Cafe UPI tastybites ₹ café"
    assert restored.dtype == np.float16 and restored.shape == (768,)
    assert np.abs(restored.astype(np.float64) - vector).max() < 1e-3  # float16 precision


def test_the_payload_layout_is_version_then_dims_then_float16_then_utf8_text():
    payload = codec.pack([0.5, -0.25, 1.0], "abc")

    assert payload[0] == codec.PAYLOAD_VERSION == 1
    assert struct.unpack_from("<H", payload, 1) == (3,)
    assert payload[3:9] == np.array([0.5, -0.25, 1.0], dtype="<f2").tobytes()
    assert payload[9:] == b"abc"


def test_the_unpacked_vector_is_read_only():
    vector, _ = codec.unpack(codec.pack([0.1, 0.2], "x"))
    with pytest.raises(ValueError):
        vector[0] = 1.0


def test_empty_text_is_allowed():
    assert codec.unpack(codec.pack([0.1], ""))[1] == ""


@pytest.mark.parametrize(
    "vector",
    [
        [],
        [[0.1, 0.2], [0.3, 0.4]],  # not one vector
        [0.1, float("nan")],
        [0.1, float("inf")],
        [0.1, 1e6],  # too large for float16: it would become inf
        [0.1, None],
        ["a", 0.2],
        "not a vector",
    ],
)
def test_pack_rejects_anything_but_a_flat_list_of_finite_numbers(vector):
    with pytest.raises(ValueError):
        codec.pack(vector, "text")


def test_pack_allows_exactly_the_maximum_dimensions_and_no_more(settings):
    settings.RAG_MAX_DIMS = 8
    assert codec.unpack(codec.pack(unit(8), "x"))[0].shape == (8,)
    with pytest.raises(ValueError, match="more than 8"):
        codec.pack(unit(9), "x")


def test_the_maximum_dimensions_never_exceed_the_database_constraint(settings):
    settings.RAG_MAX_DIMS = 100_000
    assert codec.max_dims() == 4096


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"", "too short"),
        (b"\x01\x02", "too short"),
        (b"\x02" + codec.pack([0.1], "x")[1:], "version 2"),
        (codec.pack([0.1, 0.2], "")[:-1], "truncated"),
    ],
)
def test_unpack_rejects_a_damaged_or_unknown_payload(payload, message):
    with pytest.raises(ValueError, match=message):
        codec.unpack(payload)


def test_unpack_rejects_text_that_is_not_utf8():
    with pytest.raises(ValueError):
        codec.unpack(codec.pack([0.1], "") + b"\xff\xfe")


# --- unpack_many ----------------------------------------------------------------


def test_unpack_many_keeps_the_order_of_vectors_and_texts():
    vectors = [unit(16, seed) for seed in range(5)]
    payloads = [codec.pack(vector, f"row {n}") for n, vector in enumerate(vectors)]

    matrix, texts = codec.unpack_many(payloads, 16)

    assert matrix.shape == (5, 16) and matrix.dtype == np.float16
    assert texts == [f"row {n}" for n in range(5)]
    for n, vector in enumerate(vectors):
        assert np.array_equal(matrix[n], codec.unpack(payloads[n])[0])
        assert np.abs(matrix[n].astype(np.float64) - vector).max() < 1e-3


def test_unpack_many_of_nothing_is_an_empty_matrix():
    matrix, texts = codec.unpack_many([], 768)
    assert matrix.shape == (0, 768) and texts == []


@pytest.mark.parametrize(
    "bad",
    [
        codec.pack([0.1] * 8, "other size"),
        b"\x02" + codec.pack([0.1] * 4, "x")[1:],  # another version
        codec.pack([0.1] * 4, "")[:-1],  # truncated
    ],
)
def test_unpack_many_rejects_a_payload_of_another_size_version_or_length(bad):
    good = codec.pack([0.1] * 4, "ok")
    with pytest.raises(ValueError):
        codec.unpack_many([good, bad], 4)
