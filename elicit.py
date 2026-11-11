"""Elicitation state machine: tracks the scam's stage from each scammer turn and tells the persona LLM what to aim for next."""
import re
import time

from capture import extract, normalize

STAGES = ["screen", "hook", "threat", "isolation", "payment_ask"]

# ponytail: keyword cues per stage; swap for LLM stage tagging once the live loop runs and ScamSim shows misses.
CUES = {
    "hook": ["cbi", "police", "ed", "enforcement", "narcotics", "customs", "courier", "fedex", "parcel", "rbi",
             "kyc", "sim", "trai", "electricity", "bijli", "lottery", "officer", "inspector", "पुलिस", "ಪೊಲೀಸ್",
             # job, investment, prize and family-emergency scripts (ScamSim missed these at first)
             "invest", "investment", "returns", "profit", "trading", "stock", "stocks", "shares", "crypto",
             "guaranteed", "work from home", "part time", "task", "tasks", "salary", "earn", "prize", "kbc",
             "lucky draw", "you won", "jeet gaye", "jeeta", "inaam", "accident", "hospital", "custody"],
    "threat": ["arrest", "warrant", "case", "fir", "jail", "illegal", "laundering", "drugs", "giraftar", "giraftaar",
               "block", "blocked", "disconnect", "cut", "गिरफ्तार", "ಬಂಧನ",
               "kaidhu", "kaithu", "kaidu", "atak", "dharpakad", "giraftaari"],
    "isolation": ["don't tell", "do not tell", "mat batana", "kisi ko mat", "stay on", "video call", "skype",
                  "akele", "alone", "phone mat", "call mat", "don't disconnect", "yaarigu helabedi"],
    "payment_ask": ["pay", "payment", "transfer", "send money", "bhejo", "bhej do", "jama", "deposit", "upi",
                    "ifsc", "rupees", "rupaye", "fine", "refundable", "fee", "charges", "wallet", "ಹಣ", "पैसे",
                    "panam", "dabbu", "paisalu", "paise", "paisa", "taka", "anuppu", "pampandi", "pathva", "pathao"],
    "demand": ["otp", "anydesk", "teamviewer", "quick support", "install", "download", "apk", "aadhaar", "aadhar",
               "pan", "card", "cvv", "pin", "password", "screen share"],
}
CUE_RX = {k: re.compile(r"(?<![a-z])(?:%s)(?![a-z])" % "|".join(map(re.escape, v))) for k, v in CUES.items()}

GOALS = {
    "screen": "Answer neutrally as an elderly woman and ask who is calling and why.",
    "hook": "Sound confused but polite; ask which office they are from and let them explain at length.",
    "threat": "Sound frightened; ask what you must do to fix it, and agree slowly.",
    "isolation": "Promise to stay on the line and tell no one; complain about being alone and slow with phones.",
    "payment_ask": "Agree to pay but say you need the exact account or UPI details; ask them to say it slowly.",
}
GENUINE = ("This looks like a genuine caller. Say you are an AI assistant answering for the family, "
           "take their name and message, and end politely.")
STALLS = [
    "Stall: you can't find your glasses and must look for them.",
    "Stall: the OTP or message hasn't arrived yet, the phone is very slow.",
    "Stall: this is your grandson's old phone and you don't know how to do that.",
    "Stall: someone is at the door / the pressure cooker is whistling, ask them to hold.",
]
FAIL_REASONS = ["the bank app says server error", "it says daily limit exceeded",
                "it says the account name is not matching", "the money came back"]
SCREEN_TURNS = 3  # scammer turns without any scam cue before we treat the caller as genuine


class Call:
    def __init__(self, now=time.monotonic):
        self.now, self.start = now, now()
        self.mode, self.stage = "screen", "screen"
        self.stage_times = {"screen": 0.0}
        self.identifiers, self.fails, self.stalls = [], 0, 0
        self.quiet_turns, self.pending_fail = 0, False
        self.number_so_far = ""
        self.started_at, self.transcript = time.time(), []  # (speaker, text), for the post-call report

    def _enter(self, stage):
        if STAGES.index(stage) > STAGES.index(self.stage):  # stages only move forward
            self.stage = stage
            self.stage_times[stage] = round(self.now() - self.start, 1)

    def hear(self, text):
        """Feed one scammer turn (transcript text); returns the directive for the persona's next reply."""
        heard = f"{self.number_so_far} {text}"  # a pause can end the turn in the middle of a number
        new = [i for i in extract(heard) if i not in self.identifiers]
        self.identifiers += new
        unfinished = re.search(r"(?<!\d)(\d{4,8})\W*$", normalize(heard))
        self.number_so_far = unfinished.group(1) if unfinished else ""
        norm = normalize(text)
        hits = {k for k, rx in CUE_RX.items() if rx.search(norm)}

        if self.mode == "screen":
            if hits or new:
                self.mode = "scam"
            else:
                self.quiet_turns += 1
                if self.quiet_turns >= SCREEN_TURNS:
                    self.mode = "genuine"
        if self.mode == "genuine":
            return GENUINE

        for stage in STAGES[1:]:
            if stage in hits:
                self._enter(stage)
        if new:
            self._enter("payment_ask")
            self.pending_fail = True
            return ("Read back " + ", ".join(i["value"] for i in new) +
                    " slowly, digit by digit, and ask if it is correct.")
        if "demand" in hits:
            self.stalls += 1
            return STALLS[(self.stalls - 1) % len(STALLS)]
        if self.pending_fail:
            types = {i["type"] for i in self.identifiers}
            if "account" in types and "ifsc" not in types:
                return "Say the bank is asking for the IFSC code; ask them to spell it letter by letter."
            self.pending_fail = False
            self.fails += 1
            return (f"Say the payment failed ({FAIL_REASONS[(self.fails - 1) % len(FAIL_REASONS)]}) "
                    "and ask for a different account or UPI ID to try.")
        return GOALS[self.stage]

    def report(self):
        return {"mode": self.mode, "stage": self.stage, "stage_times": self.stage_times,
                "identifiers": self.identifiers, "payment_fails": self.fails,
                "duration": round(self.now() - self.start, 1)}
