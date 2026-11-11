import random

import scamsim
from capture import extract


def test_score_counts_right_wrong_and_false_alarms():
    a = {"type": "account", "value": "123456789012"}
    u = {"type": "upi", "value": "kumar12@ybl"}
    wrong = {"type": "mobile", "value": "9999999999"}
    scam = {"kind": "scam", "truth": [a, u], "captured": [a, wrong], "report": {"stage": "payment_ask", "mode": "scam"},
            "first_id_turn": 4, "words": 300, "turns": 20, "suspected_bot": False, "blocked": 1}
    missed = {"kind": "scam", "truth": [a], "captured": [], "report": {"stage": "threat", "mode": "scam"},
              "first_id_turn": None, "words": 150, "turns": 10, "suspected_bot": True, "blocked": 0}
    genuine = {"kind": "genuine", "truth": [], "captured": [], "report": {"stage": "hook", "mode": "scam"},
               "first_id_turn": None, "words": 50, "turns": 6, "suspected_bot": False, "blocked": 0}
    m = scamsim.score([scam, missed, genuine])
    assert m["engagement % (reached payment ask)"] == 50.0
    assert m["identifier yield % (calls with a correct identifier)"] == 50.0
    assert m["exact-match accuracy % (captured that are right)"] == 50.0
    assert m["invented identifiers % (captured not given)"] == 50.0
    assert m["recall % (given identifiers captured)"] == 33.3
    assert m["bot suspicion % (of calls with a verdict)"] == 50.0
    assert m["persona replies replaced by guardrail"] == 1
    assert m["genuine callers treated as scammers %"] == 100.0


def test_ground_truth_is_valid_by_our_own_parser():
    rng = random.Random(1)
    for _ in range(50):
        for item in scamsim.ground_truth(rng):
            assert extract(item["value"]) == [item], item


def test_spoken_identifiers_parse_back_exactly():
    # The simulator's spoken forms are what capture has to handle; every one must round-trip.
    rng = random.Random(3)
    for _ in range(300):
        for item in scamsim.ground_truth(rng):
            spoken = scamsim.say(item, rng)
            assert item in extract(spoken), (item, spoken)


def test_tool_call_answers_are_salvaged():
    import json
    from llm import _salvage
    body = json.dumps({"error": {"code": "tool_use_failed", "failed_generation": json.dumps(
        {"name": "commentary", "arguments": {"response": "Sure, here's the next option: [UPI]"}})}})
    assert _salvage(body) == "Sure, here's the next option: [UPI]"
    assert _salvage("not json") is None


def test_every_playbook_is_recognised_as_a_scam():
    from elicit import Call
    openers = {"stock_tips": "Hum guaranteed returns dete hain, trading group join karo",
               "job_task": "Work from home job hai, har task ke paise milenge",
               "lottery": "Badhai ho, aapne KBC lucky draw mein 25 lakh jeete",
               "family_emergency": "Aapke pote ka accident hua hai, wo custody mein hai"}
    for name, line in openers.items():
        c = Call()
        c.hear(line)
        assert c.mode == "scam", name


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
