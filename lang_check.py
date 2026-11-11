"""Checks each persona language with no human listener: Timbre speaks numbers in that language, Prisma's live stream
transcribes them, capture must get them right; then Groq must reply in the right script and Timbre must speak it.

Run: .venv/bin/python lang_check.py [persona ...]. This can't judge whether the language sounds natural.
"""
import asyncio
import os
import sys
import time
import unicodedata
import wave
from pathlib import Path

import certifi
import numpy as np
import requests
import soxr
from dotenv import load_dotenv
from gnani.stt.client import GnaniSTTStreamClient
from gnani.tts.client import GnaniTTSClient

from capture import NATIVE_DIGITS, extract
from elicit import GOALS
from guardrail import guard, violation
from persona import PERSONAS, system_prompt

load_dotenv(override=True)
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
OUT = Path(__file__).parent / "auditions" / "languages"
SCRIPTS = {"kn": "KANNADA", "hi": "DEVANAGARI", "mr": "DEVANAGARI", "ta": "TAMIL", "te": "TELUGU", "ml": "MALAYALAM",
           "bn": "BENGALI", "gu": "GUJARATI", "pa": "GURMUKHI"}
ACCOUNT = "0000111122223"  # deliberately hard: long repeats are where Prisma miscounts
VARIED = "3141592653589"
MOBILE = "9876500000"
UPI_LINE = "UPI ID likho: ramesh dot verify at the rate demo."
TTS_ONE_AT_A_TIME = asyncio.Lock()  # Timbre answers 429 to a second simultaneous request on this account
STREAMS = asyncio.Semaphore(6)


def script_share(text, lang):
    """Fraction of letters written in the language's own script."""
    letters = [c for c in text if c.isalpha()]
    return sum(unicodedata.name(c, "").startswith(SCRIPTS[lang]) for c in letters) / max(1, len(letters))


def pcm16k(path):
    with wave.open(str(path)) as w:
        raw, rate = w.readframes(w.getnframes()), w.getframerate()
    return soxr.resample(np.frombuffer(raw, dtype=np.int16), rate, 16000).astype(np.int16).tobytes()


async def transcribe(path, hints):
    async with STREAMS:
        stream = GnaniSTTStreamClient(language_code="indic-auto", model="prisma-v3.0", sample_rate=16000,
                                      language_candidates=hints, format="transliterate")
        await stream.connect()
        data = pcm16k(path) + bytes(16000 * 2 * 2)
        for i in range(0, len(data), 1024):
            await stream.send_audio(data[i:i + 1024])
            await asyncio.sleep(0.032)
        return " ".join(t.text for t in await stream.close())


def speak(text, voice, lang, name):
    """Timbre audio, cached so re-runs don't spend credits. Returns the path."""
    path = OUT / f"{name}.wav"
    if not path.exists():
        GnaniTTSClient().synthesize(text, voice, model="timbre-v3.0", language=f"{lang}-IN", output_file=path)
    return path


async def check(key):
    p, results = PERSONAS[key], {}
    lang, hints = p["lang"], p["stt_hints"].split(",")
    words = NATIVE_DIGITS[lang]
    spell = lambda number: " ".join(words[int(d)] for d in number)
    clips = {
        "repeated digits": (f"{lang}_account", spell(ACCOUNT), ACCOUNT),
        "varied digits": (f"{lang}_varied", spell(VARIED), VARIED),
        "english digits": (f"{lang}_mobile", "Mobile number: nine eight seven six five zero zero zero zero zero.", MOBILE),
        "upi id": (f"{lang}_upi", UPI_LINE, "ramesh.verify@demo"),
    }
    paths = {}
    for label, (name, text, _) in clips.items():
        async with TTS_ONE_AT_A_TIME:
            paths[label] = await asyncio.to_thread(speak, text, "Avinash", lang, name)
    texts = await asyncio.gather(*[transcribe(paths[label], hints) for label in clips])
    for (label, (_, _, want)), text in zip(clips.items(), texts):
        results[label] = (want in [i["value"] for i in extract(text)], text)
    return key, results


def reply_check(key):
    p = PERSONAS[key]
    start = time.perf_counter()
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        json={"model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"), "reasoning_effort": "low", "messages": [
            {"role": "system", "content": system_prompt(key, GOALS["threat"])},
            {"role": "user", "content": "Aapke against arrest warrant hai, money laundering case."}]},
        timeout=30)
    r.raise_for_status()
    raw = " ".join(r.json()["choices"][0]["message"]["content"].split())
    reply = guard(raw, p["lang"])  # what the bot would actually speak
    share = script_share(reply, p["lang"])
    spoken = speak(reply, p["voice"], p["lang"], f"{p['lang']}_reply")
    return reply, share, violation(raw), time.perf_counter() - start, spoken.stat().st_size > 1000


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    keys = sys.argv[1:] or list(PERSONAS)
    failed = []
    for key, results in await asyncio.gather(*[check(k) for k in keys]):
        p = PERSONAS[key]
        print(f"\n{p['name']} ({p['line']})")
        for label, (ok, text) in results.items():
            print(f"  {'pass' if ok else 'FAIL'}  {label}: {text}")
            if not ok:
                failed.append(f"{key}: {label}")
        reply, share, bad, secs, audio = await asyncio.to_thread(reply_check, key)
        ok = share >= 0.5 and not bad and audio
        print(f"  {'pass' if ok else 'FAIL'}  reply ({share:.0%} own script, {secs:.1f}s, guardrail {bad or 'clean'}): {reply}")
        if not ok:
            failed.append(f"{key}: reply")
    print(f"\n{'All languages passed' if not failed else 'Failures: ' + ', '.join(failed)}")
    print(f"Replies to review with a native speaker are in {OUT}/")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
