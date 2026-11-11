"""Output filter: the persona never says anything shaped like real data, except reading back what the scammer gave."""
import re

from capture import normalize

PAN = re.compile(r"\b[a-z]{5}\d{4}[a-z]\b")
LONG_DIGITS = re.compile(r"\d{6,}")  # OTPs, Aadhaar, cards, accounts
SOUND_TAG = re.compile(r"<([^>]*)>")
ALLOWED_TAGS = {"coughs", "sigh", "pauses", "clears throat"}  # the LLM also invents ones like <babu>

STALL = {
    "hi": "<sigh> बेटा, चश्मा नहीं मिल रहा... एक मिनट रुको।",
    "kn": "<sigh> ಕನ್ನಡಕ ಸಿಗ್ತಿಲ್ಲ ಮಗು... ಒಂದು ನಿಮಿಷ ಇರಿ.",
    "ta": "<sigh> கண்ணாடி கிடைக்கல கண்ணா... ஒரு நிமிஷம் இரு.",
    "te": "<sigh> కళ్ళజోడు దొరకలేదు బాబు... ఒక్క నిమిషం ఆగు.",
    "ml": "<sigh> കണ്ണാടി കാണുന്നില്ല മോനേ... ഒരു നിമിഷം.",
    "mr": "<sigh> बाळा, चष्मा सापडत नाही... एक मिनिट थांब.",
    "bn": "<sigh> বাবা, চশমাটা পাচ্ছি না... এক মিনিট দাঁড়াও.",
    "gu": "<sigh> દીકરા, ચશ્મા નથી મળતા... એક મિનિટ ઊભો રે.",
    "pa": "<sigh> ਪੁੱਤ, ਐਨਕਾਂ ਨਹੀਂ ਲੱਭਦੀਆਂ... ਇੱਕ ਮਿੰਟ ਰੁਕ.",
}


def _is_read_back(run, allowed):
    """True if a digit run is the caller's own numbers: whole ones back to back, plus at most one partial."""
    numbers = sorted((re.sub(r"\D", "", a) for a in allowed), key=len, reverse=True)
    for n in numbers:
        if len(n) >= 6:
            run = run.replace(n, "")
    return not run or any(run in n for n in numbers)


def violation(reply, allowed=()):
    """Reason the reply is unsafe, or None. `allowed` = identifier values captured from the scammer (read-back)."""
    norm = normalize(re.sub(r"<[^>]+>", " ", reply))  # a sound tag must not split a digit run
    if PAN.search(norm):
        return "pan"
    for m in LONG_DIGITS.finditer(norm):
        if not _is_read_back(m.group(), allowed):
            return "digits"
    return None


def strip_unknown_tags(reply):
    """Drop tags Timbre doesn't know, so they can't be read out or heard as noise."""
    kept = SOUND_TAG.sub(lambda m: m.group() if m.group(1).strip().lower() in ALLOWED_TAGS else " ", reply)
    return " ".join(kept.split())


def guard(reply, lang="hi", allowed=()):
    return STALL[lang] if violation(reply, allowed) else strip_unknown_tags(reply)
