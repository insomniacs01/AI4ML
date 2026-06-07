from backend.app.services.governance_payload_values import coerce_non_negative_int, optional_payload_str


def test_optional_payload_str_returns_text_only_for_truthy_values() -> None:
    assert optional_payload_str("value") == "value"
    assert optional_payload_str(123) == "123"
    assert optional_payload_str("") is None
    assert optional_payload_str(None) is None


def test_coerce_non_negative_int_rejects_invalid_and_negative_values() -> None:
    assert coerce_non_negative_int("12") == 12
    assert coerce_non_negative_int("-5") == 0
    assert coerce_non_negative_int("bad") == 0
