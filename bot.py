"""Live call loop: caller audio -> Prisma STT -> elicitation + Groq persona -> guardrail -> Timbre TTS.

Run `uv run bot.py -t webrtc`, open http://localhost:7860/client and play the scammer.
The dashboard runs alongside on http://localhost:8000. The default persona is Dadi (Hindi); PERSONA=<key> from
persona.py switches language.
"""
import asyncio
import hashlib
import os
import random
import threading
import time
import wave
from pathlib import Path

import certifi
import numpy as np
from dotenv import load_dotenv
from gnani.tts.client import AudioConfig, GnaniTTSClient
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    InterruptionFrame, LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame,
    OutputAudioRawFrame, TranscriptionFrame, TTSAudioRawFrame, TTSSpeakFrame, UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat_gnani import GnaniSTTService, GnaniTTSService
from pipecat_gnani import stt as gnani_stt

import dashboard
from elicit import GOALS, Call
from guardrail import guard
from persona import PERSONAS, system_prompt
from report import build_report, save

load_dotenv(override=True)
os.environ.setdefault("SSL_CERT_FILE", certifi.where())  # python.org builds on macOS ship no CA bundle for websockets
PERSONA = os.environ.get("PERSONA", "dadi")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
CLIPS = Path(__file__).parent / "fillers"
# Silence Prisma needs before it closes a segment. Default is 500. On live calls 300 was fastest and the only value
# that kept every digit of a test mobile number (3 calls each). The docs suggest 400-600 at 8 kHz, so re-test by phone.
MIN_SILENCE_MS = os.environ.get("MIN_SILENCE_MS", "300")

# The plugin has no option for these Prisma headers. Its version is pinned, so wrapping its builder is safe.
_stt_headers = gnani_stt._build_ws_option_headers
gnani_stt._build_ws_option_headers = lambda settings: {
    **_stt_headers(settings), "x-min-silence-ms": MIN_SILENCE_MS, "x-idle-timeout-sec": "300"}


def report_turn(speaker, text, call, found=(), directive=None):
    call.transcript.append(("caller" if speaker == "scammer" else "persona", text))
    ev = {"type": "turn", "speaker": speaker, "text": text, "found": list(found), "report": call.report()}
    if directive:
        ev["directive"] = directive
    dashboard.publish(ev)


class Elicit(FrameProcessor):
    """Sits after the user aggregator: once per finished caller turn, runs the state machine and
    rewrites the system prompt with the persona's next goal before the LLM sees the context."""

    def __init__(self, call):
        super().__init__()
        self.call, self.directive = call, GOALS["screen"]

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and not getattr(frame, "speculation", False):
            msgs = frame.context.get_messages()
            user = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
            if user and isinstance(user.get("content"), str):
                before = len(self.call.identifiers)
                self.directive = self.call.hear(user["content"])
                msgs[0] = {"role": "system", "content": system_prompt(PERSONA, self.directive)}
                frame.context.set_messages(msgs)
                report_turn("scammer", user["content"], self.call, self.call.identifiers[before:])
        await self.push_frame(frame, direction)


class Guard(FrameProcessor):
    """Sits between LLM and TTS: holds each reply until it's complete, then speaks it only if it's safe.
    ponytail: whole-reply buffering costs the LLM's full generation time; guard per sentence if latency hurts."""

    def __init__(self, call, elicit):
        super().__init__()
        self.call, self.elicit, self.buf = call, elicit, None

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self.buf = []
        elif isinstance(frame, LLMTextFrame) and self.buf is not None:
            self.buf.append(frame.text)
            return
        elif isinstance(frame, InterruptionFrame):
            self.buf = None
        elif isinstance(frame, LLMFullResponseEndFrame) and self.buf is not None:
            raw = " ".join("".join(self.buf).split())  # the model emits narrow no-break spaces
            safe = guard(raw, PERSONAS[PERSONA]["lang"], [i["value"] for i in self.call.identifiers])
            if safe != raw:
                logger.warning(f"Guardrail replaced reply: {raw!r}")
            self.buf = None
            if safe:
                await self.push_frame(LLMTextFrame(safe), direction)
                report_turn("persona", safe, self.call, directive=self.elicit.directive)
        await self.push_frame(frame, direction)


def load_clip(text, p):
    """A filler clip as (pcm, sample_rate). Timbre makes it once; it's cached so calls spend no credits on it."""
    path = CLIPS / f"{p['voice']}_{hashlib.sha1(text.encode()).hexdigest()[:10]}.wav"
    if not path.exists():
        CLIPS.mkdir(exist_ok=True)
        GnaniTTSClient().synthesize(text, p["voice"], model="timbre-v3.0", language=f"{p['lang']}-IN", speed=0.85,
                                    audio_config=AudioConfig(sample_rate=16000), output_file=path)
    with wave.open(str(path)) as w:
        return trim_silence(w.readframes(w.getnframes())), w.getframerate()


def trim_silence(pcm, threshold=400, pad=800):
    """Drop silence at both ends: leading silence would delay the filler, trailing would delay the reply."""
    loud = np.flatnonzero(np.abs(np.frombuffer(pcm, dtype=np.int16)) > threshold)
    return pcm if not len(loud) else pcm[max(0, loud[0] - pad) * 2:(loud[-1] + pad) * 2]


class TurnClock:
    """Per-turn latency breakdown, in seconds from when the caller actually stopped talking."""

    def __init__(self):
        self.speech_end, self.marks = None, {}

    def mark(self, stage):
        if self.speech_end:
            self.marks[stage] = time.time() - self.speech_end

    def report(self):
        logger.info("Latency: " + ", ".join(f"{k} {v:.2f}s" for k, v in self.marks.items()))
        self.marks = {}


class TranscriptWatch(FrameProcessor):
    """Sits right after STT. Prisma only ever sends finished segments, but the plugin doesn't mark them final, so
    the turn would wait out its timeout with the text already here. Mark one final once the caller has gone quiet.
    ponytail: an older segment landing just after a short follow-up ends the turn early; the follow-up then starts
    a new turn. Rare, and it only costs a re-generated reply."""

    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            self.clock.mark("transcript")
            frame.finalized = self.clock.speech_end is not None
        await self.push_frame(frame, direction)


class Filler(FrameProcessor):
    """Sits just before the output. Plays a short sound once the caller goes quiet, covering the wait for Prisma and
    the LLM, and a backchannel during long monologues. New caller speech interrupts them when it opens a turn,
    because the output transport drops queued audio on an interruption."""

    def __init__(self, fillers, backchannels, backchannel_every=6.0, clock=None, delay=0.1, min_gap=4.0):
        super().__init__()
        self.fillers, self.backchannels, self.every = fillers, backchannels, backchannel_every
        self.delay, self.min_gap = delay, min_gap  # VAD's 0.2 s + delay = the 300 ms target; gap stops constant "hmm"s
        self.loop, self.pending, self.last, self.last_sound, self.awaiting_reply = None, None, None, 0.0, False
        self.clock = clock or TurnClock()

    def _pick(self, clips):
        self.last = random.choice([c for c in clips if c is not self.last] or clips)
        return self.last

    def _quiet(self):
        return time.monotonic() - self.last_sound >= self.min_gap

    async def _play(self, clip):
        self.last_sound = time.monotonic()
        await self.push_frame(OutputAudioRawFrame(audio=clip[0], sample_rate=clip[1], num_channels=1))

    async def _filler(self):
        if self._quiet():
            await self._play(self._pick(self.fillers))
            self.clock.mark("filler")

    async def _filler_after_pause(self):
        await asyncio.sleep(self.delay)
        await self._filler()

    async def _backchannel_loop(self):
        while True:
            await asyncio.sleep(self.every)
            if self._quiet():
                await self._play(self._pick(self.backchannels))

    async def _cancel(self, name):
        task = getattr(self, name)
        if task:
            setattr(self, name, None)
            await self.cancel_task(task)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            await self._cancel("loop")
            self.loop = self.create_task(self._backchannel_loop())
            self.awaiting_reply = False
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            await self._cancel("pending")
            self.clock.speech_end, self.clock.marks = None, {}
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self.clock.speech_end = frame.timestamp - frame.stop_secs
            self.clock.mark("vad")
            await self._cancel("pending")
            self.pending = self.create_task(self._filler_after_pause())
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.clock.mark("turn_end")
            await self._cancel("loop")
            await self.push_frame(frame, direction)
            if not self.pending or self.pending.done():
                await self._filler()  # a turn VAD didn't end
            self.awaiting_reply = True
            return
        elif isinstance(frame, TTSAudioRawFrame) and self.awaiting_reply:
            self.clock.mark("reply")
            self.clock.report()
            self.awaiting_reply = False
        await self.push_frame(frame, direction)

    async def cleanup(self):
        await super().cleanup()
        await self._cancel("loop")
        await self._cancel("pending")


async def bot(runner_args: RunnerArguments):
    p = PERSONAS[PERSONA]
    fillers = await asyncio.to_thread(lambda: [load_clip(t, p) for t in p["fillers"]])
    backchannels = await asyncio.to_thread(lambda: [load_clip(t, p) for t in p["backchannels"]])
    transport = await create_transport(runner_args, {
        "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    })
    stt = GnaniSTTService(
        api_key=os.environ["GNANI_API_KEY"],
        sample_rate=16000,
        settings=GnaniSTTService.Settings(
            model="prisma-v3.0", language="indic-auto", language_candidates=p["stt_hints"].split(","),
            # transliterate keeps every identifier in Latin script. No keywords: on the live stream they replaced
            # IFSC digits with dashes (transliterate only) and biased "CBI" into "SBI" (other formats).
            format="transliterate",
        ),
    )
    tts = GnaniTTSService(
        api_key=os.environ["GNANI_API_KEY"],
        sample_rate=16000,
        settings=GnaniTTSService.Settings(model="timbre-v3.0", voice=p["voice"], language=f"{p['lang']}-IN",
                                          speed=0.85),
    )
    llm = GroqLLMService(api_key=os.environ["GROQ_API_KEY"], settings=GroqLLMService.Settings(
        model=GROQ_MODEL, extra={"reasoning_effort": "low"}))  # low keeps replies near 0.5 s

    call = Call()
    context = LLMContext([{"role": "system", "content": system_prompt(PERSONA, GOALS["screen"])}])
    agg = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))
    elicit, clock = Elicit(call), TurnClock()
    pipeline = Pipeline([
        transport.input(), stt, TranscriptWatch(clock), agg.user(), elicit, llm, Guard(call, elicit), tts,
        Filler(fillers, backchannels, clock=clock), transport.output(), agg.assistant(),
    ])
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
                        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        call.__init__()  # fresh call state per connection
        dashboard.publish({"type": "start", "name": p["name"], "line": p["line"], "at": time.time() * 1000})
        await task.queue_frames([TTSSpeakFrame(p["greeting"])])
        report_turn("persona", p["greeting"], call, directive="Answer neutrally and listen.")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await task.cancel()
        summary = call.report()
        full = await asyncio.to_thread(build_report, summary, call.transcript, p["name"], call.started_at)
        path = await asyncio.to_thread(save, full)
        logger.info(f"Post-call report: {path}")
        dashboard.publish({"type": "end", "report": summary, "post_call": {
            "id": full["report_id"], "scam_type": full["scam"]["scam_type"],
            "agency": full["scam"]["impersonated_agency"]}})

    await PipelineRunner(handle_sigint=runner_args.handle_sigint).run(task)


if __name__ == "__main__":
    from pipecat.runner.run import main

    threading.Thread(target=dashboard.make_server().serve_forever, daemon=True).start()
    main()
