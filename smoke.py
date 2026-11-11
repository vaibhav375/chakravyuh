"""Day-1 smoke test with real keys: Timbre voices, Prisma on a spoken scam line, and Groq persona latency.

Run: uv run smoke.py   (writes voice auditions to auditions/)
"""
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from gnani.stt.client import GnaniSTTClient
from gnani.tts.client import GnaniTTSClient

from capture import extract
from elicit import GOALS
from guardrail import violation
from persona import PERSONAS, system_prompt

load_dotenv(override=True)
OUT = Path(__file__).parent / "auditions"
FEMALE_V3 = ["Lakshmi", "Kalpana", "Shivani", "Chetana", "Vasudha", "Riyaa", "Tarika"]
AJJI_LINE = "<coughs> ಹಲೋ? ಯಾರು ಅಪ್ಪ? <pauses> CBI-ಆ? ಒಂದು ನಿಮಿಷ, ಕನ್ನಡಕ ಹುಡುಕ್ತೀನಿ."
SCAM_LINE = ("Main CBI se bol raha hoon. Account number likho: zero zero zero zero, one one one one, "
             "two two two two, three. IFSC D E M O zero zero zero one two three four.")


def timed(label, fn):
    t = time.perf_counter()
    try:
        out = fn()
    except Exception as e:  # server errors come back as whole HTML pages; keep the first line
        print(f"  {label}: FAILED after {time.perf_counter() - t:.1f}s: {str(e).strip().splitlines()[0][:200]}")
        return None
    print(f"  {label}: {time.perf_counter() - t:.2f}s")
    return out


def speak(path, *args, **kw):
    """Synthesize to `path` unless it's already there (retries shouldn't spend credits)."""
    if path.exists():
        print(f"  {path.name}: cached")
    else:
        timed(path.name, lambda: GnaniTTSClient().synthesize(*args, output_file=path, **kw))


def main():
    stt = GnaniSTTClient()
    OUT.mkdir(exist_ok=True)

    print("1. Timbre v3.0 auditions for Ajji (speed 0.85)")
    for v in FEMALE_V3:
        speak(OUT / f"ajji_{v}.wav", AJJI_LINE, v, model="timbre-v3.0", language="kn-IN", speed=0.85)

    print("2. Prisma v3.0 on a role-played scammer line (Timbre voice Avinash)")
    scam = OUT / "scammer_line.wav"
    speak(scam, SCAM_LINE, "Avinash", model="timbre-v3.0", language="hi-IN")
    for model in ("prisma-v3.0", None):  # None = server default (v2.5), the fallback path
        kw = dict(model="prisma-v3.0", language_candidates=["hi-IN", "en-IN"], format="transliterate") if model else {}
        res = timed(f"stt {model or 'v2.5 default'}",
                    lambda: stt.transcribe(scam, "indic-auto" if model else "hi-IN", **kw))
        if res is None:
            continue
        text = res.get("transcript") or res.get("text") or str(res)
        print(f"    transcript: {text}")
        print(f"    captured:   {extract(text)}")

    print("3. Groq persona reply")
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    r = timed(model, lambda: requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        json={"model": model, "reasoning_effort": "low", "messages": [
            {"role": "system", "content": system_prompt("ajji", GOALS["threat"])},
            {"role": "user", "content": "Aapke against arrest warrant hai, money laundering case."}]},
        timeout=30))
    r.raise_for_status()
    reply = r.json()["choices"][0]["message"]["content"]
    print(f"    reply: {reply}\n    guardrail: {violation(reply) or 'clean'}")
    print(f"\nListen to {OUT}/ and set the best voice in persona.py.")


if __name__ == "__main__":
    missing = [k for k in ("GNANI_API_KEY", "GROQ_API_KEY") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Fill in {', '.join(missing)} in .env first.")
    main()
