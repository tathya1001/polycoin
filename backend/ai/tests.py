import uuid

import numpy as np
import pytest

from ai.scoring import (
    build_prototype,
    cosine_similarities,
    decide,
    normalize,
    prepare_text,
)


# --- prepare_text -------------------------------------------------------------


def test_prepare_text_strips_references_ifsc_noise_and_emails():
    text = prepare_text("TASTYBITES", "UPI/DR/412345678901/TASTYBITES/TSTB0000001/tastybites@tstb")
    assert text == "TASTYBITES"


def test_prepare_text_keeps_meaningful_words_and_drops_duplicates():
    assert prepare_text("Bigshop", "POS 123456 BIGSHOP PAY INDIA") == "Bigshop PAY INDIA"


def test_prepare_text_keeps_the_merchant_part_of_a_upi_handle():
    text = prepare_text("PAYWAVE", "UPI/DR/412345678901/PAYWAVE/dinedash@paywave")
    assert text == "PAYWAVE dinedash"


def test_prepare_text_drops_numeric_and_reference_like_handles():
    assert prepare_text("X", "9876543210@testpay") == "X"
    assert prepare_text("X", "paywaveqr281005050101@paywave") == "X"


def test_prepare_text_dedupes_a_handle_that_repeats_the_name():
    assert prepare_text("TASTYBITES", "tastybites@tstb") == "TASTYBITES"


def test_prepare_text_drops_the_banks_to_by_transfer_prefix_but_not_the_word_elsewhere():
    assert prepare_text("BRIGHTWORKS", "BY TRANSFER-NEFT*TSTC0000018*BRIGHTWORKS PAYROLL") == "BRIGHTWORKS PAYROLL"
    assert prepare_text("X", "TO TRANSFER-UPI/DR/412345678901/RENT") == "X RENT"
    # Only the leading bank prefix goes: the user describing a transfer keeps that word.
    assert prepare_text("Money", "sent to friend", notes="transfer to mom") == "Money transfer to mom sent friend"


def test_prepare_text_includes_notes_between_the_name_and_the_narration():
    text = prepare_text("PAYWAVE", "UPI/DR/412345678901/ONLINE", notes="dinner with Rahul")
    assert text == "PAYWAVE dinner with Rahul ONLINE"


def test_prepare_text_cleans_notes_like_the_rest_and_dedupes():
    text = prepare_text("TASTYBITES", "tastybites@tstb", notes="tastybites 9876543210 order")
    assert text == "TASTYBITES order"


def test_prepare_text_keeps_notes_when_the_narration_would_be_cut_off():
    long_narration = " ".join(f"word{n}x" for n in range(200))  # far longer than the cap
    text = prepare_text("X", long_narration, notes="vet visit")
    assert "vet visit" in text and len(text) <= 300


def test_prepare_text_notes_are_optional():
    assert prepare_text("TASTYBITES", "a") == prepare_text("TASTYBITES", "a", notes="")


def test_prepare_text_falls_back_to_name_when_everything_is_noise():
    assert prepare_text("UPI", "DR 412345678901") == "UPI"


# --- normalize / cosine_similarities -----------------------------------------


def test_normalize_gives_unit_length_to_a_vector_and_to_every_row():
    assert np.linalg.norm(normalize([3.0, 4.0])) == pytest.approx(1.0)
    rows = normalize([[3.0, 4.0], [0.0, 5.0]])
    assert np.linalg.norm(rows, axis=1) == pytest.approx([1.0, 1.0])


def test_normalize_leaves_a_zero_vector_alone():
    assert normalize([0.0, 0.0]).tolist() == [0.0, 0.0]


def test_cosine_identical_orthogonal_and_scale_invariant():
    scores = cosine_similarities([1.0, 0.0], [[1.0, 0.0], [0.0, 1.0], [5.0, 0.0]])
    assert scores == pytest.approx([1.0, 0.0, 1.0])


def test_cosine_rejects_mismatched_dimensions():
    with pytest.raises(ValueError):
        cosine_similarities([1.0, 0.0], [[1.0, 0.0, 0.0]])


# --- build_prototype ----------------------------------------------------------

LABEL = [1.0, 0.0]
EXAMPLE = [0.0, 1.0]


def test_prototype_with_no_examples_is_just_the_label():
    assert build_prototype(LABEL, [], 10, 0.7).tolist() == [1.0, 0.0]


@pytest.mark.parametrize(
    "count, weight",
    [(5, 0.35), (10, 0.7), (50, 0.7)],  # half-way, full, and capped
)
def test_prototype_blend_weight_grows_then_caps(count, weight):
    proto = build_prototype(LABEL, [EXAMPLE] * count, full_at=10, max_weight=0.7)
    assert proto == pytest.approx(normalize([1 - weight, weight]))


# --- decide -------------------------------------------------------------------

PROTOS = {1: normalize([1.0, 0.0]), 2: normalize([0.0, 1.0])}


def test_decide_proposes_a_clear_winner():
    result = decide([1.0, 0.1], PROTOS, min_score=0.5, min_margin=0.05)
    assert (result.category_id, result.runner_up_id, result.decision) == (1, 2, "propose")


def test_decide_rejects_a_low_score_on_its_own():
    opposite = {1: normalize([1.0, -1.0]), 2: normalize([-1.0, 1.0])}
    result = decide([1.0, 1.0], opposite, min_score=0.5, min_margin=0.0)
    assert result.decision == "below_threshold"


def test_decide_rejects_a_narrow_margin_on_its_own():
    result = decide([1.0, 1.0], PROTOS, min_score=0.5, min_margin=0.05)
    assert result.decision == "too_close"


def test_decide_with_one_candidate_skips_the_margin_check():
    result = decide([1.0, 0.0], {1: PROTOS[1]}, min_score=0.5, min_margin=0.9)
    assert (result.runner_up_id, result.runner_up_score, result.decision) == (
        None,
        None,
        "propose",
    )


def test_decide_with_no_candidates():
    assert decide([1.0, 0.0], {}, 0.5, 0.05).decision == "no_candidates"


def test_decide_breaks_ties_by_mapping_order():
    result = decide([1.0, 1.0], {7: PROTOS[1], 3: PROTOS[2]}, min_score=0.1, min_margin=0.0)
    assert result.category_id == 7


def test_decide_returns_the_callers_ids_untouched():
    """Category ids are UUIDs in this project: they must come back as the same objects,
    not be coerced (int(uuid) once turned them into meaningless 128-bit integers)."""
    first, second = uuid.uuid4(), uuid.uuid4()
    result = decide([1.0, 0.1], {first: PROTOS[1], second: PROTOS[2]}, 0.5, 0.05)
    assert result.category_id == first
    assert result.runner_up_id == second
    assert type(result.score) is float
