from JavPI.cloud.reporter import _sanitize_value


def test_sanitize_truncates_and_caps():
    payload = {
        "long": "x" * 2000,
        "items": list(range(100)),
        "nested": {"a": {"b": {"c": {"d": "too-deep"}}}},
    }
    out = _sanitize_value(payload)

    assert isinstance(out["long"], str)
    assert out["long"].endswith("...<truncated>")
    assert len(out["items"]) <= 31
    assert out["nested"]["a"]["b"] == "<truncated-depth>"


def test_sanitize_bytes_and_scalars():
    out = _sanitize_value({"blob": b"abc", "n": 1, "ok": True, "none": None})
    assert out["blob"].startswith("<bytes:")
    assert out["n"] == 1
    assert out["ok"] is True
    assert out["none"] is None

