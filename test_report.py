from datetime import datetime

from report import IST, build_report, suspects


def test_accounts_pair_with_the_ifsc_given_after_them():
    ids = [{"type": "account", "value": "111122223333"}, {"type": "ifsc", "value": "SBIN0001234"},
           {"type": "upi", "value": "x@ybl"}, {"type": "account", "value": "999988887777"},
           {"type": "mobile", "value": "9876500000"}, {"type": "ifsc", "value": "HDFC0000001"},
           {"type": "ifsc", "value": "UTIB0000002"}]
    s = suspects(ids)
    assert s["bank_accounts"] == [{"account": "111122223333", "ifsc": "SBIN0001234"},
                                  {"account": "999988887777", "ifsc": "HDFC0000001"},
                                  {"account": None, "ifsc": "UTIB0000002"}]
    assert s["upi_ids"] == ["x@ybl"] and s["mobiles"] == ["9876500000"]


def test_report_shape():
    summary = {"mode": "scam", "stage": "payment_ask", "stage_times": {"screen": 0.0, "hook": 3.1},
               "identifiers": [{"type": "upi", "value": "x@ybl"}], "payment_fails": 1, "duration": 95.2}
    r = build_report(summary, [("persona", "हाँ?"), ("caller", "CBI se bol raha hoon")], "Dadi", datetime(2026, 11, 11, 17, 30, 5, tzinfo=IST).timestamp(),
                     classify_with=lambda t: {"scam_type": "digital_arrest", "impersonated_agency": "CBI", "summary": "x"})
    assert r["report_id"] == "20261111-173005"
    assert r["incident"]["started"] == "2026-11-11T17:30:05+05:30"
    assert r["suspect_identifiers"]["upi_ids"] == ["x@ybl"]
    assert r["transcript"][1] == {"speaker": "caller", "text": "CBI se bol raha hoon"}
    assert r["scam"]["impersonated_agency"] == "CBI"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
