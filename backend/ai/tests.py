from ai.scoring import prepare_text

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

