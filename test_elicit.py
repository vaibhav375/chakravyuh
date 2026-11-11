from elicit import GENUINE, Call


def clock():
    t = [0.0]

    def now():
        t[0] += 10
        return t[0]
    return now


def test_digital_arrest_call():
    c = Call(now=clock())
    assert "who is calling" in c.hear("hello, hello?")
    assert "which office" in c.hear("Main CBI se bol raha hoon, aapke naam pe parcel aaya hai")
    assert "frightened" in c.hear("aapke against arrest warrant hai, money laundering case")
    assert "stay on the line" in c.hear("kisi ko mat batana, video call pe raho")
    assert c.hear("abhi AnyDesk install karo").startswith("Stall")
    assert "account or UPI" in c.hear("verification ke liye refundable amount pay karna hoga")

    d = c.hear("account number 1234 5678 9012 3 mein bhejo")
    assert "Read back 1234567890123" in d
    assert "IFSC" in c.hear("haan sahi hai")  # account without IFSC -> ask for it first
    assert "Read back SBIN0001234" in c.hear("IFSC S B I N zero zero zero one two three four")
    assert "payment failed" in c.hear("haan, ab jaldi bhejo")
    assert "Read back ramesh@ybl" in c.hear("toh ramesh at the rate ybl pe bhejo")
    assert "payment failed (it says daily limit exceeded)" in c.hear("ho gaya?")

    r = c.report()
    assert r["mode"] == "scam" and r["stage"] == "payment_ask" and r["payment_fails"] == 2
    assert [i["type"] for i in r["identifiers"]] == ["account", "ifsc", "upi"]
    assert list(r["stage_times"]) == ["screen", "hook", "threat", "isolation", "payment_ask"]


def test_dashboard_demo_scripts():
    import dashboard
    for persona, script in dashboard.DEMO.items():
        events = []
        dashboard.publish = events.append
        call = dashboard.run_demo(sleep=lambda s: None, persona=persona)
        assert [i["type"] for i in call.identifiers] == ["account", "ifsc", "upi", "mobile"], persona
        assert call.fails == 2, persona
        replies = [e["text"] for e in events if e.get("speaker") == "persona"][1:]
        assert replies == [r for _, r in script], persona  # guardrail blocks none of the scripted lines


def test_number_split_across_two_turns_is_joined():
    c = Call(now=clock())
    c.hear("Mobile number nine eight seven six five.")  # the real split from a live call
    assert c.identifiers == []
    c.hear("Zero zero zero zero zero.")
    assert c.identifiers == [{"type": "mobile", "value": "9876500000"}]


def test_a_finished_number_is_not_joined_to_the_next_one():
    c = Call(now=clock())
    c.hear("Mobile 9876500000")
    c.hear("Dusra 9845012345")
    assert [i["value"] for i in c.identifiers] == ["9876500000", "9845012345"]


def test_an_unfinished_number_is_dropped_once_other_talk_follows():
    c = Call(now=clock())
    c.hear("Number hai 98765")
    c.hear("jaldi karo beta")
    c.hear("00000 rupees bhejo")
    assert c.identifiers == []


def test_genuine_caller_gets_ai_disclosure():
    c = Call(now=clock())
    c.hear("hello aunty, main Priya bol rahi hoon")
    c.hear("Rohit ghar pe hai kya?")
    assert c.hear("unko bolna shaam ko milte hain") == GENUINE
    assert c.hear("thik hai") == GENUINE


def test_stages_never_go_back():
    c = Call(now=clock())
    c.hear("aapka account block ho jayega, payment karo")
    assert c.stage == "payment_ask"
    c.hear("main RBI officer hoon")
    assert c.stage == "payment_ask"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
