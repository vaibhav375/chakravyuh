"""Offline check of the two pipeline stages bot.py adds. Run with: uv run test_bot.py"""
import asyncio
import time

import numpy as np
from pipecat.frames.frames import (
    LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, OutputAudioRawFrame,
    TranscriptionFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame, VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import SleepFrame, run_test

import bot
from elicit import Call

FILLER, BACK = (b"\x01\x00" * 160, 16000), (b"\x02\x00" * 160, 16000)


async def test_elicit_rewrites_system_prompt():
    call = Call()
    ctx = LLMContext([{"role": "system", "content": "old"},
                      {"role": "user", "content": "Main CBI se bol raha hoon, account 0000 1111 2222 3"}])
    down, _ = await run_test(bot.Elicit(call), frames_to_send=[LLMContextFrame(ctx)],
                             expected_down_frames=[LLMContextFrame])
    system = down[0].context.get_messages()[0]["content"]
    assert "Shanti Devi" in system and "Read back 0000111122223" in system  # Dadi is the default persona
    assert call.identifiers == [{"type": "account", "value": "0000111122223"}]


async def test_guard_replaces_leaks_and_passes_safe_replies():
    call, elicit = Call(), bot.Elicit(Call())
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("ನನ್ನ OTP "), LLMTextFrame("4 5 6 7 8 9"), LLMFullResponseEndFrame(),
              LLMFullResponseStartFrame(), LLMTextFrame("ಯಾರು "), LLMTextFrame("ಅಪ್ಪ?"), LLMFullResponseEndFrame()]
    down, _ = await run_test(bot.Guard(call, elicit), frames_to_send=frames, expected_down_frames=[
        LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame,
        LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame])
    texts = [f.text for f in down if isinstance(f, LLMTextFrame)]
    assert texts[0].startswith("<sigh>") and "456789" not in texts[0]
    assert texts[1] == "ಯಾರು ಅಪ್ಪ?"


async def audio_from(filler_stage, frames):
    down, _ = await run_test(filler_stage, frames_to_send=frames, expected_down_frames=None)
    return [f.audio for f in down if isinstance(f, OutputAudioRawFrame)]


async def test_filler_starts_soon_after_voice_stops():
    audio = await audio_from(bot.Filler([FILLER], [BACK], delay=0.05), [
        VADUserStoppedSpeakingFrame(stop_secs=0.2), SleepFrame(sleep=0.15), UserStoppedSpeakingFrame()])
    assert audio == [FILLER[0]]  # once: the turn end right after must not add a second one


async def test_filler_is_cancelled_if_the_caller_resumes():
    audio = await audio_from(bot.Filler([FILLER], [BACK], delay=0.2), [
        VADUserStoppedSpeakingFrame(stop_secs=0.2), SleepFrame(sleep=0.05), VADUserStartedSpeakingFrame(),
        SleepFrame(sleep=0.3)])
    assert audio == []


async def test_filler_waits_out_the_gap_between_sounds():
    audio = await audio_from(bot.Filler([FILLER], [BACK], delay=0.01, min_gap=10), [
        VADUserStoppedSpeakingFrame(stop_secs=0.2), SleepFrame(sleep=0.05), VADUserStartedSpeakingFrame(),
        VADUserStoppedSpeakingFrame(stop_secs=0.2), SleepFrame(sleep=0.05)])
    assert audio == [FILLER[0]]


async def test_backchannels_run_during_long_turns_and_stop_at_the_end():
    audio = await audio_from(bot.Filler([FILLER], [BACK], backchannel_every=0.1, min_gap=0), [
        UserStartedSpeakingFrame(), SleepFrame(sleep=0.25), UserStoppedSpeakingFrame(), SleepFrame(sleep=0.2)])
    assert audio == [BACK[0], BACK[0], FILLER[0]]


async def test_transcript_is_final_only_once_the_caller_is_quiet():
    clock = bot.TurnClock()
    frame = lambda: TranscriptionFrame(text="hello", user_id="", timestamp="")
    down, _ = await run_test(bot.TranscriptWatch(clock), frames_to_send=[frame()], expected_down_frames=None)
    assert down[0].finalized is False  # still talking
    clock.speech_end = time.time() - 1
    down, _ = await run_test(bot.TranscriptWatch(clock), frames_to_send=[frame()], expected_down_frames=None)
    assert down[0].finalized is True


def test_trim_silence_drops_quiet_ends():
    pcm = np.concatenate([np.zeros(5000), np.full(1000, 3000), np.zeros(5000)]).astype(np.int16).tobytes()
    trimmed = bot.trim_silence(pcm, pad=100)
    assert len(trimmed) == (1000 + 200 - 1) * 2
    assert bot.trim_silence(bytes(4000)) == bytes(4000)  # all silent: left alone


if __name__ == "__main__":
    bot.dashboard.publish = lambda ev: None
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            result = fn()
            if asyncio.iscoroutine(result):
                asyncio.run(result)
    print("ok")
