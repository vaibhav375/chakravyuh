# Submission form text

Paste-ready answers for the Great Indian AI Internship Challenge form. Fill in the two bracketed items before you
submit. Figures come from the build plan's sources (I4C data via IANS, TechCrunch, Drishti IAS).

## Project title

Chakravyuh: an AI honeypot that traps phone scammers in Indian languages

## The problem you are solving

Indians reported losing ₹19,813 crore to cyber fraud in 2025. Scams such as digital arrest, fake KYC or SIM blocks,
courier threats and lottery fees reach victims by phone. The main in-call protection in India, Google's on-device scam
detection, runs only on Pixel 9 and later phones and only in Hindi and English. Elderly, regional-language and
feature-phone users get no help during the call. And the national Suspect Registry of mule accounts is built from
complaints, so most accounts are flagged only after someone has been cheated.

## The solution

Chakravyuh answers suspected scam calls as a believable elderly persona, keeps the scammer talking, and coaxes out
their bank accounts with IFSC, UPI IDs and phone numbers. It validates each identifier as it is spoken, reads it back,
then says "payment failed" to collect the next one. After the call it writes a report shaped like a cyber-crime
complaint, so banks and the Suspect Registry can block mule accounts before a real victim pays. It speaks Hindi by
default, with personas in eight more Indian languages, and a guardrail stops it from ever saying a number the caller
didn't give. Genuine callers are told they are talking to an AI.

## Who will use it

- Telecom operators: route calls from numbers they already flag to persona lines.
- Bank and fintech fraud teams: receive validated mule identifiers to block.
- Families: forward an elderly parent's unanswered calls to Chakravyuh.
- I4C and state cyber cells: a feed of identifiers and live scam scripts in regional languages.

## Gnani AI models and APIs used

- Prisma v3.0 realtime speech-to-text over WebSocket: automatic language detection with Hindi, English and a regional
  language as hints, transliterated output, tuned silence detection.
- Timbre v3.0 text-to-speech over WebSocket for the persona's replies at speed 0.85 with sound tags (coughs, sighs,
  pauses), and the REST endpoint for cached filler sounds.
- Both through Gnani's Pipecat plugin (pipecat-gnani).

Do not list Prisma batch transcription, voice cloning or Evon: they are in the original plan but not built.

## Each member's contribution

[Solo: "Built everything: the real-time voice agent, identifier capture, guardrail, ScamSim evaluation, dashboard and
reports." For a team, one line per person.]

## Demo video and post links

[LinkedIn post URL] · [X post URL] · Video: upload natively to both posts.

## Numbers you can quote

From the README's results, measured on scripted, Timbre-generated speech (not a human voice):

- First sound 0.30 s after the caller stops; median reply 1.68 s.
- 15 of 15 synthetic identifiers caught across 3 voice calls; a mobile number split across two turns is still caught.
- Number capture passes in 6 of 9 languages in automated checks.
<!-- SCAMSIM-NUMBERS -->
