from stdnum import verhoeff

from dpdp_lens.recognizers import column_hint, find_pii, mask


def make_aadhaar(prefix="23412341234"):
    return prefix + verhoeff.calc_check_digit(prefix)


VALID = make_aadhaar()
INVALID = VALID[:-1] + str((int(VALID[-1]) + 1) % 10)


def types(text, column=None):
    return [m[0] for m in find_pii(text, column)]


# Aadhaar
def test_aadhaar_valid_with_context():
    (t, s, e, masked), = find_pii(f"aadhaar: {VALID}")
    assert t == "aadhaar" and masked == "XXXX XXXX " + VALID[-4:]


def test_aadhaar_spaced_with_column_hint():
    spaced = f"{VALID[:4]} {VALID[4:8]} {VALID[8:]}"
    assert types(spaced, "aadhaar") == ["aadhaar"]


def test_aadhaar_bad_checksum_not_flagged():
    assert types(f"aadhaar: {INVALID}") == []
    assert types(INVALID, "aadhaar") == []


def test_bare_valid_12_digit_number_not_flagged():
    assert types(VALID) == []
    assert types(f"reference {VALID} thanks") == []


def test_12_digit_order_id_not_flagged():
    assert types(VALID, "order_id") == []
    assert types(f"order id {VALID}") == []
    assert types("order_id=987654321098") == []


# PAN
def test_pan_positive_and_masked():
    (t, _, _, masked), = find_pii("pan ABCPD1234E")
    assert t == "pan" and masked == "XXXXX1234E"


def test_pan_negative():
    assert types("ABCXD1234E") == []  # 4th letter not a valid holder type
    assert types("ABCPD0000E") == []  # 0000 not allowed
    assert types("abcpd1234e") == []


# Phone
def test_phone_with_context():
    (t, _, _, masked), = find_pii("phone: 9876543210")
    assert t == "phone" and masked == "98XXXXXX10"


def test_phone_with_column_hint_and_prefix():
    assert [m[3] for m in find_pii("+91-9876543210", "mobile")] == ["98XXXXXX10"]
    assert types("09876543210", "phone") == ["phone"]


def test_phone_without_context_not_flagged():
    assert types("9876543210") == []
    assert types("1234567890", "phone") == []  # must start 6 to 9


# Email and DOB
def test_email_masked():
    (t, _, _, masked), = find_pii("mail aarav.sharma@example.test now")
    assert t == "email" and masked == "a***@example.test"


def test_dob_needs_context_and_shows_year_only():
    assert types("2008-05-17") == []
    (t, _, _, masked), = find_pii("2008-05-17", "dob")
    assert t == "dob" and masked == "2008-XX-XX"


# Helpers
def test_column_hint():
    assert column_hint("parent_pan") == "pan"
    assert column_hint("Aadhaar_No") == "aadhaar"
    assert column_hint("uid") == "aadhaar"
    assert column_hint("company") is None  # 'pan' inside a word is not a hint
    assert column_hint("password_hash") is None
    assert column_hint(None) is None


def test_mask_helper():
    assert mask("aadhaar", VALID) == "XXXX XXXX " + VALID[-4:]
