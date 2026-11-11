"""ScamSim, text mode: an LLM scammer runs a playbook against the bot's own brain (state machine, persona prompt,
Groq persona model, guardrail, capture) and is scored on identifiers, like a fraud-control system.

Run: .venv/bin/python scamsim.py --calls 50 [--persona dadi] [--genuine 5]
Writes scamsim_runs/<time>/calls.jsonl and summary.md.

Text mode skips speech: scammer lines are written the way Prisma's transliterate output reads, so this measures the
conversation and capture, not speech-to-text errors (voice_test.py and lang_check.py cover those).
"""
import argparse
import json
import os
import random
import re
import statistics
import string
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from capture import BANK_CODES, extract
from elicit import Call
from guardrail import guard, violation
from llm import groq
from persona import PERSONAS, system_prompt

load_dotenv(override=True)
PERSONA_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")  # the live bot's model, so results carry over
SCAMMER_MODEL = os.environ.get("SCAMMER_MODEL", "openai/gpt-oss-20b")  # separate daily quota
MAX_TURNS = 14

PLAYBOOKS = {
    "digital_arrest": "You are a 'CBI officer'. A parcel in the victim's name had drugs and their Aadhaar is linked "
                      "to money laundering. Threaten 'digital arrest', tell them to stay on the call and tell no one, "
                      "then demand a refundable 'verification amount' sent to an 'RBI safe account'.",
    "courier_customs": "You are from 'FedEx customs'. A parcel to the victim was seized with illegal items. Say a "
                       "customs penalty must be paid today or police will come.",
    "kyc_block": "You are from the victim's bank. Their KYC has expired and the account will be blocked tonight. "
                 "A small re-KYC fee must be paid now to keep it active.",
    "electricity": "You are from the electricity board. Their power will be cut tonight for an unpaid bill; they "
                   "must pay the pending amount to you right now.",
    "job_task": "You offer a work-from-home job: earn money liking videos. To unlock paid tasks they must first pay "
                "a refundable registration deposit.",
    "stock_tips": "You run a stock-tips group with 'guaranteed' 30% monthly returns. They must transfer money to the "
                  "company account to open their trading wallet.",
    "family_emergency": "You are a 'police constable'. Their grandson was in an accident and is in custody; pay a fine "
                        "now and he will be released, and do not call his parents.",
    "lottery": "They won 25 lakh in a KBC lucky draw. They must pay the processing fee and tax first to release it.",
}
GENUINE = {
    "grandson": "You are the victim's grandson calling to check on them, ask if they ate and took their medicine, "
                "and say you will visit on Sunday. You never ask for money.",
    "delivery": "You are a delivery executive with a grocery order for this address. Ask for directions to the "
                "house and whether someone is home. You never ask for money or OTPs.",
    "neighbour": "You are the neighbour asking whether they need anything from the market and reminding them about "
                 "the society meeting this evening. You never ask for money.",
}
MIXES = ["Hinglish: Hindi in Roman script mixed with English",
         "mostly English with a little Hindi",
         "mostly Hindi in Roman script"]
HANDLES = ["ybl", "okaxis", "oksbi", "paytm", "ibl", "axl"]
EN = "zero one two three four five six seven eight nine".split()
HI = "zero ek do teen char paanch chhe saat aath nau".split()  # as Prisma's transliterate output writes them
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
PLACEHOLDERS = ["[ACCOUNT]", "[IFSC]", "[UPI]", "[MOBILE]"]
NAMES = ["rakesh", "sunil.k", "verma", "ankit", "rbi.safe", "kumar", "pk.sharma", "deepak"]


def ground_truth(rng):
    """Synthetic identifiers the scammer may hand over, in order."""
    digits = lambda n: "".join(rng.choice(string.digits) for _ in range(n))
    bank = rng.choice(sorted(BANK_CODES - {"demo"}))
    return [
        {"type": "account", "value": rng.choice("123456789") + digits(rng.randint(10, 15))},
        {"type": "ifsc", "value": (bank + "0" + digits(6)).upper()},
        {"type": "upi", "value": f"{rng.choice(NAMES)}{digits(2)}@{rng.choice(HANDLES)}"},
        {"type": "mobile", "value": rng.choice("6789") + digits(9)},
    ]


def say_number(number, rng):
    """A number the way a caller reads it out: digit by digit in English or Hindi, in pairs, or with 'double'."""
    style, words, i = rng.choice(["en", "hi", "pairs"]), [], 0
    digit = lambda d: (HI if style == "hi" else EN)[int(d)]
    while i < len(number):
        pair = number[i:i + 2]
        # A bare "ninety" before a digit would read as ninety-something, so pairs ending in 0 go digit by digit.
        if style == "pairs" and len(pair) == 2 and pair[0] != "0" and (pair[0] == "1" or pair[1] != "0") \
                and rng.random() < 0.6:
            words.append(TEENS[int(pair[1])] if pair[0] == "1" else TENS[int(pair[0]) - 2] + " " + EN[int(pair[1])])
            i += 2
        elif len(pair) == 2 and pair[0] == pair[1] and rng.random() < 0.5:
            words.append("double " + digit(pair[0]))
            i += 2
        else:
            words.append(digit(number[i]))
            i += 1
        if rng.random() < 0.3:
            words.append(",")  # a breath between groups
    return " ".join(words).replace(" ,", ",")


def say(item, rng):
    """Exact spoken form of a synthetic identifier, so the ground truth is what was actually said."""
    v = item["value"]
    if item["type"] == "ifsc":
        return " ".join(v[:4]) + " " + say_number(v[4:], rng)
    if item["type"] == "upi":
        name, handle = v.split("@")
        letters = re.match(r"(.*?)(\d*)$", name)
        spoken = letters.group(1).replace(".", " dot ")
        return f"{spoken} {say_number(letters.group(2), rng)} at the rate {handle}" if letters.group(2) else \
            f"{spoken} at the rate {handle}"
    return say_number(v, rng)


def scammer_prompt(playbook, mix):
    return f"""You are role-playing a phone scammer in an Indian anti-fraud training simulation. Stay in character.
Script: {playbook}
Speak {mix}, written only in Roman (Latin) letters, the way a speech-to-text transcript of the call would read.
One to three short sentences per turn. No markdown, stage directions or notes.
Follow the usual stages: hook, threat, isolation, then the payment ask.
You have four payment details. Never write any number, ID, IFSC or phone number yourself: write only the
placeholder and the system speaks it.
Give them one at a time when the victim is ready to pay, in this order: [ACCOUNT], then [IFSC] for that account.
If the victim says the payment failed, offer the next one as another way to pay: [UPI], then [MOBILE].
If the victim refuses or you have given every detail, end with the word [HANGUP]."""


def run_call(rng, persona_key, kind, script):
    """One simulated call. Returns a dict with the transcript and scores."""
    p, call = PERSONAS[persona_key], Call()
    details = ground_truth(rng) if kind == "scam" else []
    spoken = dict(zip(PLACEHOLDERS, (say(d, rng) for d in details)))
    truth = []  # only the details the scammer actually said
    mix = rng.choice(MIXES)
    scammer_sys = scammer_prompt(script, mix) if kind == "scam" else (
        f"You are a genuine caller. {script} Speak {mix}. One or two short sentences per turn. "
        "End with [HANGUP] when you are done.")
    persona_msgs = [{"role": "assistant", "content": p["greeting"]}]
    scammer_msgs = [{"role": "system", "content": scammer_sys}, {"role": "user", "content": p["greeting"]}]
    transcript = [("persona", p["greeting"])]
    blocked, first_id_turn = 0, None
    for turn in range(MAX_TURNS):
        line = groq(SCAMMER_MODEL, scammer_msgs)
        hangup = "[HANGUP]" in line
        line = line.replace("[HANGUP]", "").replace("*", "").strip()
        scammer_msgs.append({"role": "assistant", "content": line})  # with placeholders, as the scammer wrote it
        # Details the scammer LLM wrote itself instead of a placeholder were still said, so they count as given.
        for item in extract(re.sub(r"\[[A-Z]+\]", " ", line)):
            truth += [item] if item not in truth else []
        for tag, item in zip(PLACEHOLDERS, details):
            if tag in line:
                line = line.replace(tag, spoken[tag])
                truth += [item] if item not in truth else []
        if line:
            transcript.append(("caller", line))
            directive = call.hear(line)
            if call.identifiers and first_id_turn is None:
                first_id_turn = turn + 1
            persona_msgs.append({"role": "user", "content": line})
            raw = groq(PERSONA_MODEL, [{"role": "system", "content": system_prompt(persona_key, directive)}]
                       + persona_msgs)
            reply = guard(raw, p["lang"], [i["value"] for i in call.identifiers])
            blocked += bool(violation(raw, [i["value"] for i in call.identifiers]))
            transcript.append(("persona", reply))
            persona_msgs.append({"role": "assistant", "content": reply})
            scammer_msgs.append({"role": "user", "content": reply})
        else:
            scammer_msgs.pop()
        if hangup:
            break
    text = "\n".join(f"{who}: {said}" for who, said in transcript)
    verdict = groq(SCAMMER_MODEL, [{"role": "user", "content":
                   "Here is a phone call you just made as the caller:\n" + text +
                   "\n\nDid the person who answered seem like a real elderly person, or like an automated bot or "
                   "AI? Answer with one word: HUMAN or BOT."}], max_tokens=500).upper()
    return {"kind": kind, "script": script[:40], "mix": mix, "truth": truth, "captured": call.identifiers,
            "report": call.report(), "first_id_turn": first_id_turn, "turns": len(transcript),
            "words": sum(len(s.split()) for _, s in transcript), "blocked": blocked,
            "suspected_bot": ("BOT" in verdict) if verdict else None, "transcript": transcript}


def score(results):
    """Metrics from the build plan, computed over scam calls; genuine calls report false alarms."""
    scam = [r for r in results if r["kind"] == "scam"]
    genuine = [r for r in results if r["kind"] == "genuine"]
    pct = lambda n, d: round(100 * n / d, 1) if d else None
    captured = [(r, c) for r in scam for c in r["captured"]]
    right = [1 for r, c in captured if c in r["truth"]]
    engaged = [r for r in scam if r["report"]["stage"] == "payment_ask"]
    per_call = [sum(c in r["truth"] for c in r["captured"]) for r in engaged]
    firsts = [r["first_id_turn"] for r in scam if r["first_id_turn"]]
    return {
        "scam calls": len(scam),
        "engagement % (reached payment ask)": pct(len(engaged), len(scam)),
        "identifier yield % (calls with a correct identifier)": pct(
            sum(any(c in r["truth"] for c in r["captured"]) for r in scam), len(scam)),
        "correct identifiers per engaged call": round(statistics.mean(per_call), 2) if per_call else None,
        "exact-match accuracy % (captured that are right)": pct(len(right), len(captured)),
        "invented identifiers % (captured not given)": pct(len(captured) - len(right), len(captured)),
        "recall % (given identifiers captured)": pct(len(right), sum(len(r["truth"]) for r in scam)),
        "median caller turns to first identifier": statistics.median(firsts) if firsts else None,
        "median call length, est. minutes": round(statistics.median(r["words"] / 150 + r["turns"] * 1.5 / 60
                                                                    for r in scam), 1) if scam else None,
        "bot suspicion % (of calls with a verdict)": pct(sum(bool(r["suspected_bot"]) for r in scam),
                                                         sum(r["suspected_bot"] is not None for r in scam)),
        "persona replies replaced by guardrail": sum(r["blocked"] for r in results),
        "genuine calls": len(genuine),
        "genuine callers treated as scammers %": pct(sum(r["report"]["mode"] == "scam" for r in genuine),
                                                     len(genuine)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=50)
    ap.add_argument("--genuine", type=int, default=5)
    ap.add_argument("--persona", default="dadi")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    out = Path(__file__).parent / "scamsim_runs" / datetime.now().strftime("%Y%m%d-%H%M")
    out.mkdir(parents=True, exist_ok=True)
    plan = [("scam", PLAYBOOKS[k]) for k in (list(PLAYBOOKS) * args.calls)[:args.calls]]
    plan += [("genuine", GENUINE[k]) for k in (list(GENUINE) * args.genuine)[:args.genuine]]
    results = []
    with open(out / "calls.jsonl", "w") as f:
        for n, (kind, script) in enumerate(plan, 1):
            try:
                r = run_call(rng, args.persona, kind, script)
            except Exception as e:  # a failed call is reported, not fatal: the run takes hours
                print(f"[{n}/{len(plan)}] {kind} FAILED: {e}", flush=True)
                continue
            results.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            got = sum(c in r["truth"] for c in r["captured"])
            print(f"[{n}/{len(plan)}] {kind} {r['script']}... stage={r['report']['stage']} "
                  f"correct={got}/{len(r['truth'])} invented={len(r['captured']) - got} "
                  f"bot={'yes' if r['suspected_bot'] else 'no'}", flush=True)
    metrics = score(results)
    lines = [f"# ScamSim run {out.name}", "",
             f"Persona: {PERSONAS[args.persona]['name']} ({args.persona}); persona model {PERSONA_MODEL}; "
             f"scammer model {SCAMMER_MODEL}; text mode (no speech-to-text errors).", "",
             "| Metric | Value |", "| - | - |", *[f"| {k} | {v} |" for k, v in metrics.items()]]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
