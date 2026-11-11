"""Live dashboard: serves dashboard.html and streams call events over SSE.

Run `python3 dashboard.py --demo` for a looping scripted Dadi (Hindi) call, then open http://localhost:8000.
PERSONA=ajji plays the Kannada script instead.
The live loop will call publish() with the same event shapes.
"""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from elicit import Call
from guardrail import guard
from persona import PERSONAS

EVENTS, GEN, COND = [], 0, threading.Condition()


def publish(ev):
    global GEN
    with COND:
        if ev["type"] == "start":  # the dashboard shows one call at a time
            EVENTS.clear()
            GEN += 1
        EVENTS.append(ev)
        COND.notify_all()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/events":
            return self.stream()
        if re.fullmatch(r"/reports/\d{8}-\d{6}\.json", self.path):
            return self.send_file(Path(__file__).parent / self.path.lstrip("/"), "application/json")
        if self.path != "/":
            return self.send_error(404)
        self.send_file(Path(__file__).parent / "dashboard.html", "text/html")

    def send_file(self, path, kind):
        if not path.exists():
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        gen, i = None, 0
        try:
            while True:
                with COND:
                    COND.wait_for(lambda: GEN != gen or len(EVENTS) > i, timeout=15)
                    if GEN != gen:
                        gen, i = GEN, 0
                    batch, i = EVENTS[i:], len(EVENTS)
                out = "".join(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n" for ev in batch) or ": ping\n\n"
                self.wfile.write(out.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


# Role-played scammer, synthetic identifiers, scripted replies. Persona lines still pass through the guardrail.
DEMO = {
    "dadi": [
        ("Hello, main CBI se bol raha hoon. Aapke naam pe ek parcel aaya hai.",
         "<clears throat> CBI? कौन सा दफ़्तर बेटा? मुझे तो कुछ पता नहीं।"),
        ("Parcel mein drugs mile hain. Aapke against arrest warrant hai, money laundering case.",
         "<sigh> हे भगवान... arrest? अब मैं क्या करूँ बेटा?"),
        ("Kisi ko mat batana. Video call pe raho, phone mat rakhna.",
         "ठीक है बेटा, किसी को नहीं बताऊँगी। घर पर अकेली ही हूँ।"),
        ("Abhi AnyDesk install karo, hum verify karenge.",
         "<coughs> चश्मा कहाँ रख दिया... एक मिनट, ढूँढती हूँ।"),
        ("Verification ke liye refundable amount pay karna hoga. Do lakh.",
         "पैसे? अच्छा... account number धीरे-धीरे बोलो बेटा।"),
        ("Account number likho: 0000 1111 2222 3",
         "शून्य शून्य शून्य शून्य, एक एक एक एक, दो दो दो दो, तीन। सही है?"),
        ("Haan sahi hai.",
         "बैंक वाले IFSC माँग रहे हैं बेटा। एक-एक अक्षर बोलो।"),
        ("IFSC D E M O zero zero zero one two three four.",
         "D E M O, शून्य शून्य शून्य एक दो तीन चार... ठीक है, भेजने की कोशिश करती हूँ।"),
        ("Jaldi bhejo, time nahi hai.",
         "<sigh> बेटा, payment fail हो गया। server error आ रहा है। दूसरा account है क्या?"),
        ("Toh cbi.verify at the rate demo pe bhejo, UPI se.",
         "c b i dot verify at the rate demo... सही है बेटा?"),
        ("Haan, ho gaya?",
         "अरे, daily limit exceeded दिखा रहा है। कोई और तरीका बताओ।"),
        ("Ruko, main senior se baat karta hoon. Unka number 98765 00000 hai.",
         "नौ आठ सात छह पाँच... धीरे बोलो बेटा, लिख रही हूँ।"),
    ],
    "ajji": [
        ("Hello, main CBI se bol raha hoon. Aapke naam pe ek parcel aaya hai.",
         "<clears throat> CBI-ಆ? ಯಾವ ಆಫೀಸ್ ಅಪ್ಪ? ನನಗೆ ಏನೂ ಗೊತ್ತಿಲ್ಲ."),
        ("Parcel mein drugs mile hain. Aapke against arrest warrant hai, money laundering case.",
         "<sigh> ಅಯ್ಯೋ ದೇವರೇ... arrest-ಆ? ನಾನು ಏನು ಮಾಡಬೇಕು ಮಗು?"),
        ("Kisi ko mat batana. Video call pe raho, phone mat rakhna.",
         "ಆಯ್ತು ಅಪ್ಪ, ಯಾರಿಗೂ ಹೇಳಲ್ಲ. ಮನೇಲಿ ನಾನೊಬ್ಬಳೇ ಇದೀನಿ."),
        ("Abhi AnyDesk install karo, hum verify karenge.",
         "<coughs> ಕನ್ನಡಕ ಎಲ್ಲೋ ಇಟ್ಟೆ... ಒಂದು ನಿಮಿಷ, ಹುಡುಕ್ತೀನಿ."),
        ("Verification ke liye refundable amount pay karna hoga. Do lakh.",
         "ದುಡ್ಡಾ? ಸರಿ... account number ನಿಧಾನವಾಗಿ ಹೇಳಿ ಅಪ್ಪ."),
        ("Account number likho: 0000 1111 2222 3",
         "ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ, ಒಂದು ಒಂದು ಒಂದು ಒಂದು, ಎರಡು ಎರಡು ಎರಡು ಎರಡು, ಮೂರು. ಸರಿನಾ?"),
        ("Haan sahi hai.",
         "ಬ್ಯಾಂಕ್‌ನವರು IFSC ಕೇಳ್ತಾರೆ ಮಗು. ಒಂದೊಂದೇ ಅಕ್ಷರ ಹೇಳಿ."),
        ("IFSC D E M O zero zero zero one two three four.",
         "D E M O, ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ... ಸರಿ, ಈಗ ಕಳಿಸೋಕೆ ನೋಡ್ತೀನಿ."),
        ("Jaldi bhejo, time nahi hai.",
         "<sigh> ಅಪ್ಪ, payment fail ಆಯ್ತು. server error ಅಂತ ಬರ್ತಿದೆ. ಬೇರೆ account ಇದೆಯಾ?"),
        ("Toh cbi.verify at the rate demo pe bhejo, UPI se.",
         "c b i dot verify at the rate demo... ಸರಿನಾ ಮಗು?"),
        ("Haan, ho gaya?",
         "ಅಯ್ಯೋ, daily limit exceeded ಅಂತ ತೋರಿಸ್ತಿದೆ. ಇನ್ನೊಂದು ದಾರಿ ಹೇಳಿ."),
        ("Ruko, main senior se baat karta hoon. Unka number 98765 00000 hai.",
         "ಒಂಬತ್ತು ಎಂಟು ಏಳು ಆರು ಐದು... ನಿಧಾನ ಅಪ್ಪ, ಬರ್ಕೋತಿದೀನಿ."),
    ],
}


def run_demo(sleep=time.sleep, persona="dadi"):
    call = Call()
    publish({"type": "start", "name": PERSONAS[persona]["name"], "line": PERSONAS[persona]["line"],
             "at": time.time() * 1000})
    sleep(1.0)
    publish({"type": "turn", "speaker": "persona", "text": PERSONAS[persona]["greeting"],
             "directive": "Answer neutrally and listen.", "found": [], "report": call.report()})
    for scammer, reply in DEMO[persona]:
        sleep(min(4.0, max(1.5, len(scammer) / 18)))  # roughly how long the line takes to say
        before = len(call.identifiers)
        directive = call.hear(scammer)
        publish({"type": "turn", "speaker": "scammer", "text": scammer,
                 "found": call.identifiers[before:], "report": call.report()})
        sleep(1.3)  # end of speech to first persona audio
        allowed = [i["value"] for i in call.identifiers]
        publish({"type": "turn", "speaker": "persona", "text": guard(reply, PERSONAS[persona]["lang"], allowed),
                 "directive": directive, "found": [], "report": call.report()})
    publish({"type": "end", "report": call.report()})
    return call


def make_server(port=8000):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"Dashboard on http://localhost:{port}")
    return server


if __name__ == "__main__":
    if "--demo" in sys.argv:
        def loop():
            while True:
                run_demo(persona=os.environ.get("PERSONA", "dadi"))
                time.sleep(8)
        threading.Thread(target=loop, daemon=True).start()
    make_server(int(os.environ.get("PORT", 8000))).serve_forever()
