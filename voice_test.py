"""A real voice call without a microphone: streams role-played WAVs to the running bot over WebRTC and
reports what Ajji sounded like and when. Start the bot first, then run: .venv/bin/python voice_test.py

Saves what the bot said to auditions/voice_test_bot.wav so you can listen to the call.
"""
import asyncio
import json
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

AUDIO = Path(__file__).parent / "auditions"
LINES = [AUDIO / "scammer_line.wav", AUDIO / "scammer_upi.wav", AUDIO / "scammer_ifsc_short.wav"]
GREETING_WAIT, GAP = 5.0, 9.0  # seconds of mic silence before the first line and after each line
SPEECH_RMS = 300  # above this, a frame of bot audio counts as speech


def build_mic_track(lines):
    """Concatenate the lines with silence, as one mic stream. Returns the path and each line's end time."""
    with wave.open(str(lines[0])) as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
    silence = lambda s: bytes(int(s * rate) * width * channels)
    pcm, ends, t = silence(GREETING_WAIT), [], GREETING_WAIT
    for line in lines:
        with wave.open(str(line)) as w:
            audio = w.readframes(w.getnframes())  # Timbre's header overstates the length, so time the bytes
        pcm += audio
        t += len(audio) / (rate * width * channels)
        ends.append(t)
        pcm += silence(GAP)
        t += GAP
    path = Path(tempfile.mkstemp(suffix=".wav")[1])
    with wave.open(str(path), "wb") as w:
        w.setframerate(rate), w.setsampwidth(width), w.setnchannels(channels)
        w.writeframes(pcm)
    return path, ends, t


def speech_spans(windows, min_gap=0.25):
    """Merge (time, rms) windows into (start, end) spans of speech."""
    spans = []
    for t, rms in windows:
        if rms < SPEECH_RMS:
            continue
        if spans and t - spans[-1][1] <= min_gap:
            spans[-1][1] = t
        else:
            spans.append([t, t])
    return spans


def watch_dashboard(events):
    def run():
        try:
            with urllib.request.urlopen("http://localhost:8000/events") as r:
                for raw in r:
                    if raw.startswith(b"data: "):
                        ev = json.loads(raw[6:])
                        if ev["type"] == "start":  # the feed opens with the previous call's history
                            events.clear()
                        events.append(ev)
        except OSError:
            pass
    threading.Thread(target=run, daemon=True).start()


async def main():
    mic, ends, total = build_mic_track(LINES)
    events, windows, pcm_out = [], [], []
    watch_dashboard(events)
    pc = RTCPeerConnection()
    pc.createDataChannel("chat")
    pc.addTrack(MediaPlayer(str(mic)).audio)
    started = {}

    @pc.on("track")
    def on_track(track):
        async def read():
            while True:
                frame = await track.recv()
                started.setdefault("t0", time.monotonic())
                samples = frame.to_ndarray().astype(np.int16)
                pcm_out.append((samples.tobytes(), frame.sample_rate, len(frame.layout.channels)))
                windows.append((time.monotonic() - started["t0"], float(np.sqrt(np.mean(samples.astype(float) ** 2)))))
        asyncio.ensure_future(read())

    await pc.setLocalDescription(await pc.createOffer())
    req = urllib.request.Request("http://localhost:7860/api/offer", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}).encode())
    answer = json.load(urllib.request.urlopen(req, timeout=30))
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
    print(f"Calling for about {total:.0f}s...", flush=True)
    await asyncio.sleep(total + 2)

    spans = speech_spans(windows)
    print("\nBot speech (seconds from call start):")
    for s, e in spans:
        print(f"  {s:6.2f} to {e:6.2f}")
    print("\nFirst bot sound after each caller line (approximate):")
    for line, end in zip(LINES, ends):
        after = [s for s, _ in spans if s > end]
        print(f"  {line.name}: {after[0] - end:.2f}s" if after else f"  {line.name}: no bot audio")
    print(f"\nDashboard ({next((e['name'] for e in events if e['type'] == 'start'), 'no call')}):")
    for e in events:
        if e["type"] == "turn":
            found = [i["value"] for i in e["found"]]
            print(f"  {e['speaker']}: {e['text']}" + (f"  CAUGHT {found}" if found else ""))
    if pcm_out:
        _, rate, channels = pcm_out[0]
        with wave.open(str(AUDIO / "voice_test_bot.wav"), "wb") as w:
            w.setframerate(rate), w.setsampwidth(2), w.setnchannels(channels)
            w.writeframes(b"".join(p for p, _, _ in pcm_out))
        print(f"\nSaved {AUDIO / 'voice_test_bot.wav'}")
    heard = any(e["type"] == "turn" and e["speaker"] == "scammer" for e in events)
    if not heard:
        print("No caller turn reached the bot: live speech-to-text did not produce a transcript.")
    await pc.close()
    sys.exit(0 if heard else 1)


if __name__ == "__main__":
    asyncio.run(main())
