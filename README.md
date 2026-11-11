# Chakravyuh

An AI honeypot that answers scam calls as a believable Indian grandmother, keeps the scammer talking, and captures
the mule accounts, IFSCs, UPI IDs and phone numbers they hand over, so they can be blocked before a real victim pays.

Built for the Great Indian AI Internship Challenge on Gnani's speech stack (Prisma v3.0 and Timbre v3.0).

**Every scammer in this repository's tests and demos is role-played or simulated, and every account, IFSC, UPI ID and
phone number is synthetic.**

## Why

Indians reported losing ₹19,813 crore to cyber fraud in 2025 (I4C data via IANS). Digital-arrest, fake-KYC, courier
and lottery scams reach victims by phone. The main in-call protection in India, Google's on-device scam detection,
runs only on Pixel 9 and later phones and only in Hindi and English. The Suspect Registry of mule accounts is built
from complaints, so most accounts are flagged only after someone has paid. Chakravyuh collects them during the call.

## How a call works

1. The persona answers neutrally ("हाँ? हैलो? कौन?") and listens.
2. A state machine tracks the scam's stage from each caller turn: hook, threat, isolation, payment ask. A caller with
   no scam cues after three turns is treated as genuine, and the persona says it is an AI assistant taking a message.
3. In persona mode she stalls, complies slowly, and asks for payment details one at a time.
4. Every identifier is parsed from the transcript and validated as it is spoken, then read back digit by digit.
5. "Payment failed" loop: after each read-back she says the transfer failed and asks for another account or UPI ID.
6. When the caller hangs up, a JSON report shaped like a cyber-crime complaint is written to `reports/`.

## Architecture

```
caller audio (WebRTC; phone line not built yet)
  -> Silero VAD + Smart Turn                       turn taking
  -> Prisma v3.0 realtime STT                      indic-auto, 3 language hints, transliterate, 300 ms silence
  -> TranscriptWatch                               marks finished segments final so the turn ends at once
  -> Elicit                                        state machine + identifier capture -> goal for the next reply
  -> Groq gpt-oss-120b                             persona reply, prompt rewritten every turn
  -> Guard                                         blocks invented numbers and PAN-like text, strips unknown tags
  -> Timbre v3.0 realtime TTS                      persona voice at speed 0.85, sound tags like <coughs>
  -> Filler                                        a short "hmm..." 0.3 s after the caller stops, backchannels
  -> caller
  dashboard (SSE, port 8000) <- every turn;  reports/<id>.json <- every call
```

| File | What it does |
| - | - |
| `bot.py` | The live call pipeline (Pipecat + the Gnani plugin), dashboard server and post-call report |
| `capture.py` | Turns code-mixed transcripts into validated identifiers: digit words in 9 languages and English pairs ("ninety eight"), "at the rate", spelled IFSCs, a bank-code table |
| `elicit.py` | Scam-stage state machine, stalls, read-backs, the payment-failed loop, numbers split across turns |
| `guardrail.py` | The persona never says a number the caller didn't give, in any of the 9 languages |
| `persona.py` | Nine personas (Hindi Dadi is the default) and the per-turn system prompt |
| `report.py`, `llm.py` | Post-call report with Groq scam classification; Groq client that waits out rate limits |
| `dashboard.py`, `dashboard.html` | Live view: stage rings, transcript, caught identifiers, report link |
| `scamsim.py` | ScamSim: an LLM scammer runs 8 playbooks against the bot's own brain, scored on identifiers |
| `voice_test.py` | A real voice call to the running bot from WAV files over WebRTC |
| `lang_check.py` | Per-language check through Timbre, Prisma and Groq with no human listener |
| `smoke.py` | Key check, voice auditions and a Prisma round trip |

## Run it

```bash
uv sync
```

Put `GNANI_API_KEY` and `GROQ_API_KEY` in `.env`, then:

```bash
.venv/bin/python bot.py -t webrtc
```

Open http://localhost:7860/client (headphones on) to call the persona and http://localhost:8000 for the dashboard.
`PERSONA=paati` (Tamil) or any key in `persona.py` switches language. `python3 dashboard.py --demo` plays a scripted
call without any API keys.

Tests (no network): `for t in test_*.py; do .venv/bin/python $t; done`, 49 tests.

## Results so far

Measured on this machine, November 2026. All voice tests use Timbre-generated speech over WebRTC, not a human voice
or phone audio.

**Latency** (seconds after the caller stops talking, 9 turns, from the bot's own timer):

| Stage | Before tuning | After |
| - | - | - |
| First sound (filler) | ~2.0 | 0.30 |
| Final transcript | ~1.17 | ~0.9 |
| Reply audio, median | 2.64 | 1.68 |
| Reply audio, worst | 3.11 | 3.35 |

**Capture on voice calls:** 15 of 15 identifiers across 3 calls with the Kannada persona, and 5 of 5 on each of 2
calls with Dadi, including a mobile number split across two turns.

**Languages** (`lang_check.py`: Timbre speaks numbers, Prisma's live stream transcribes them):

| Persona | Language | Numbers | Reply in own script |
| - | - | - | - |
| Dadi | Hindi | pass | pass |
| Ajji | Kannada | pass | pass |
| Paati | Tamil | pass | pass |
| Ammamma | Telugu | pass | pass |
| Aaji | Marathi | pass | pass |
| Dida | Bengali | pass | pass |
| Ammachi | Malayalam | repeated digits miscounted by STT | pass |
| Beeji | Punjabi | repeated digits miscounted by STT | pass |
| Ba | Gujarati | repeated and varied digits fail | pass |

<!-- SCAMSIM -->

## What we learned building it

- Prisma v3.0's `transliterate` format was the only one that kept every identifier in Latin script. With `keywords`
  set it replaced IFSC digits with dashes on the live stream, and keywords also biased "CBI" into "SBI", so the bot
  sends none.
- The Pipecat plugin never marks Prisma's segments final, so every turn waited out a 1 s timer with the text already
  there. Marking them final once the caller is quiet cut turn-end from ~2.0 s to ~0.9 s.
- Prisma's output on the same audio changed between days (a spoken "D E M O" became "DEEMO"); re-run `voice_test.py`
  before recording anything.
- Timbre allows one request at a time per account, and Groq's free tier allows 1,000 requests a day per model.
- gpt-oss sometimes answers as an invented tool call; `llm.py` recovers the words from Groq's error.

## Safety

The persona has a fake identity and never reads out anything shaped like an Aadhaar, PAN, card, OTP or account number
unless the caller gave it. Every reply passes the guardrail before it is spoken. Calls are inbound only; genuine
callers are told they are speaking to an AI. Get legal review before any live pilot.

## Limits

- No phone line yet: calls come in over WebRTC. 8 kHz telephony audio is untested.
- Persona text in the eight regional languages is machine-written and needs a native speaker's review.
- Scam stages come from keyword cues; an LLM tagger would generalise better.
- Bank codes said as separate words are recognised only for the 36 banks in `capture.py`.
- Not built from the original plan: Prisma batch transcription, voice cloning, Evon v3.3, campaign grouping.

## Gnani models used

- **Prisma v3.0** realtime speech-to-text over WebSocket (`indic-auto`, language hints, transliterate output), plus
  the REST endpoint in `smoke.py` and `lang_check.py` tests.
- **Timbre v3.0** text-to-speech over WebSocket for replies, and REST for the cached filler and backchannel clips.
