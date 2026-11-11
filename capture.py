"""Identifier capture: turn code-mixed STT text into validated UPI IDs, accounts, IFSCs, mobiles and links."""
import re
import string
import unicodedata

# Digit words 0-9 in each persona language's own script. The persona reads numbers back with these, and the guardrail
# blocks them, so a language missing here could leak invented numbers.
NATIVE_DIGITS = {
    "hi": "शून्य एक दो तीन चार पाँच छह सात आठ नौ".split(),
    "kn": "ಸೊನ್ನೆ ಒಂದು ಎರಡು ಮೂರು ನಾಲ್ಕು ಐದು ಆರು ಏಳು ಎಂಟು ಒಂಬತ್ತು".split(),
    "ta": "பூஜ்யம் ஒன்று இரண்டு மூன்று நான்கு ஐந்து ஆறு ஏழு எட்டு ஒன்பது".split(),
    "te": "సున్నా ఒకటి రెండు మూడు నాలుగు ఐదు ఆరు ఏడు ఎనిమిది తొమ్మిది".split(),
    "ml": "പൂജ്യം ഒന്ന് രണ്ട് മൂന്ന് നാല് അഞ്ച് ആറ് ഏഴ് എട്ട് ഒമ്പത്".split(),
    "mr": "शून्य एक दोन तीन चार पाच सहा सात आठ नऊ".split(),
    "bn": "শূন্য এক দুই তিন চার পাঁচ ছয় সাত আট নয়".split(),
    "gu": "શૂન્ય એક બે ત્રણ ચાર પાંચ છ સાત આઠ નવ".split(),
    "pa": "ਸਿਫ਼ਰ ਇੱਕ ਦੋ ਤਿੰਨ ਚਾਰ ਪੰਜ ਛੇ ਸੱਤ ਅੱਠ ਨੌਂ".split(),
}

# Spoken digits as STT romanizes them, plus native-script variants -> digit.
DIGIT_WORDS = {
    # English (not bare "o": it's the letter in spelled IFSCs like "D E M O")
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    # Hindi, romanized
    "shunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4",
    "panch": "5", "paanch": "5", "chhe": "6", "chhah": "6", "che": "6", "chah": "6",
    "saat": "7", "aath": "8", "nau": "9", "no": "9",
    # Hindi, Devanagari
    "शून्य": "0", "ज़ीरो": "0", "जीरो": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4",
    "पांच": "5", "पाँच": "5", "छह": "6", "छः": "6", "सात": "7", "आठ": "8", "नौ": "9",
    # Kannada, romanized
    "sonne": "0", "ondu": "1", "eradu": "2", "mooru": "3", "muru": "3", "naalku": "4",
    "nalku": "4", "aidu": "5", "aaru": "6", "aru": "6", "elu": "7", "yelu": "7",
    "entu": "8", "ente": "8", "ombattu": "9", "ombhattu": "9",
    # Kannada script
    "ಸೊನ್ನೆ": "0", "ಒಂದು": "1", "ಎರಡು": "2", "ಮೂರು": "3", "ನಾಲ್ಕು": "4", "ಐದು": "5",
    "ಆರು": "6", "ಏಳು": "7", "ಎಂಟು": "8", "ಒಂಬತ್ತು": "9",
    # English digits as STT writes them in native script
    "वन": "1", "टू": "2", "थ्री": "3", "फोर": "4", "फ़ोर": "4", "फाइव": "5", "फ़ाइव": "5", "सिक्स": "6",
    "सेवन": "7", "एट": "8", "नाइन": "9",
    "ಜೀರೋ": "0", "ಝೀರೋ": "0", "ಒನ್": "1", "ಟು": "2", "ತ್ರೀ": "3", "ಫೋರ್": "4", "ಫೈವ್": "5", "ಸಿಕ್ಸ್": "6",
    "ಸೆವೆನ್": "7", "ಎಯ್ಟ್": "8", "ಏಟ್": "8", "ನೈನ್": "9",
    # Romanized, as Prisma's transliterate format writes them
    "poojiyam": "0", "poojyam": "0", "pujyam": "0", "onnu": "1", "ondru": "1", "rendu": "2", "irandu": "2",  # Tamil
    "moonu": "3", "moondru": "3", "naalu": "4", "naangu": "4", "anju": "5", "aindhu": "5", "ezhu": "7", "ettu": "8",
    "onbadhu": "9", "ombadhu": "9",
    "sunna": "0", "okati": "1", "moodu": "3", "naalugu": "4", "edu": "7", "yedu": "7", "enimidi": "8",  # Telugu
    "tommidi": "9",
    "randu": "2", "moonnu": "3", "anchu": "5", "onpathu": "9", "ompathu": "9",  # Malayalam
    "shunny": "0", "shunye": "0", "onru": "1", "moonru": "3", "suna": "0",  # seen in lang_check.py runs
    "chh": "6", "thombidi": "9", "enmidi": "8", "choy": "6", "ath": "8",
    "don": "2", "paach": "5", "saha": "6", "nav": "9",  # Marathi and Gujarati
    "shunno": "0", "shunyo": "0", "dui": "2", "tin": "3", "chhoy": "6", "shaat": "7", "aat": "8", "noy": "9",  # Bengali
    "be": "2", "tran": "3", "chha": "6",  # Gujarati
    "sifar": "0", "ik": "1", "ikk": "1", "tinn": "3", "panj": "5", "satt": "7", "atth": "8", "naun": "9",  # Punjabi
}
for _words in NATIVE_DIGITS.values():
    DIGIT_WORDS.update({word: str(i) for i, word in enumerate(_words)})
DIGIT_WORDS = {unicodedata.normalize("NFC", k): v for k, v in DIGIT_WORDS.items()}
# ponytail: letter names and "at the rate" only cover Hindi and Kannada script. The bot's transliterate format writes
# them in Latin for every language, so add others if a format that keeps native script is ever used.
# Spelled English letters as STT writes them; only used for the IFSC search, since many are ordinary words ("के").
LETTERS = dict(zip(
    "ए बी सी डी ई एफ जी एच आई जे के एल एम एन ओ पी क्यू आर एस टी यू वी डब्ल्यू एक्स वाई ज़ेड जेड".split(),
    "a b c d e f g h i j k l m n o p q r s t u v w x y z z".split()))
LETTERS |= dict(zip(
    "ಎ ಬಿ ಸಿ ಡಿ ಇ ಎಫ್ ಜಿ ಎಚ್ ಐ ಜೆ ಕೆ ಎಲ್ ಎಂ ಎನ್ ಓ ಪಿ ಕ್ಯೂ ಆರ್ ಎಸ್ ಟಿ ಯು ವಿ ಡಬ್ಲ್ಯೂ ಎಕ್ಸ್ ವೈ ಝಡ್".split(),
    "a b c d e f g h i j k l m n o p q r s t u v w x y z".split()))
LETTERS = {unicodedata.normalize("NFC", k): v for k, v in LETTERS.items()}
REPEAT_WORDS = {"double": 2, "triple": 3}
PUNCT = string.punctuation + "…।“”‘’"  # stripped from both ends of a word before it's read as a digit
# English numbers read in pairs, the usual way Indians read out phone numbers: "ninety eight forty five".
TEENS = {w: str(10 + i) for i, w in enumerate(
    "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: str(i) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
UNITS = {w: str(i) for i, w in enumerate("one two three four five six seven eight nine".split(), 1)}
MIN_RUN = 4  # a run of spoken digits shorter than this is ordinary speech ("account do na")

AT = re.compile(r"\s*(?:\bat\s*the\s*rate(?:\s*of)?\b|\batrate\b|@)\s*")
DOT = re.compile(r"\s+\bdot\b\s+")
SLASH = re.compile(r"\s+\bslash\b\s+")
# Replaced before digit parsing, because "एट" alone also means eight.
NATIVE_AT = re.compile(r"(?:एट|ऐट)\s*(?:द|दी|दा)?\s*रेट|(?:ಅಟ್|ಎಟ್)\s*(?:ದ|ದಿ)?\s*ರೇಟ್")
NATIVE_DOT = re.compile(r"डॉट|ಡಾಟ್")

EMAIL = re.compile(r"\b[a-z0-9._-]+@[a-z0-9-]+(?:\.[a-z]{2,})+\b")
UPI = re.compile(r"\b[a-z0-9][a-z0-9._-]{1,255}@[a-z]{2,64}(?!\.?\w)")
URL = re.compile(r"\b(?:https?://\S+|www\.\S+|[a-z0-9-]+\.(?:com|in|net|org|xyz|app|link|site|online|info|co)\b(?:/\S*)?)")
IFSC = re.compile(r"\b[a-z]{4}0[a-z0-9]{6}\b")
BRANCH = re.compile(r"\b0[a-z0-9]{6}\b")
# Bank code said apart from the branch ("SBIN 0001234", STT's "SBI N 0001234"). Only known codes count, so
# "likh 0001234" can't become an invented IFSC. DEMO is the synthetic bank used in role-played calls.
# ponytail: common banks only; load the full RBI IFSC list if ScamSim shows misses on smaller banks.
BANK_CODES = set("""sbin hdfc icic utib punb barb cnrb ubin kkbk yesb idib bkid ioba indb idfb fdrl cbin mahb psib
    ucba airp pytm karb kvbl sibl tmbl ciub ratn bdbl aubl esfb ujvn jaka dlxb ntbl demo""".split())
MISHEARD_CODES = {"deemo": "demo"}  # how Prisma currently writes the spoken synthetic bank code
MOBILE = re.compile(r"^(?:91|0)?([6-9]\d{9})$")
DIGITS = re.compile(r"\b\d{9,18}\b")


def _ascii_digits(tok):
    """'೯೮' / '९८' -> '98'; anything that isn't all digits comes back unchanged."""
    if tok and all(unicodedata.decimal(c, None) is not None for c in tok):
        return "".join(str(unicodedata.decimal(c)) for c in tok)
    return tok


def _join_digit_runs(text):
    """Collapse runs like 'nau saat four 2 double five' into '974255'."""
    out, run, raw = [], [], []
    toks = text.split()

    def before_at(i):
        following = " ".join(t.strip(PUNCT) for t in toks[i:i + 3])
        return following.startswith(("at the rate", "at rate", "atrate")) or (i < len(toks) and toks[i][:1] == "@")

    def flush(i):
        digits = "".join(run)
        if len(digits) >= MIN_RUN:
            out.append(digits)
        elif run and before_at(i):  # "verma three two at the rate ibl": the digits belong to the UPI name
            if out and out[-1] != "dot" and out[-1].isalnum():
                out[-1] += digits
            else:
                out.append(digits)
        else:
            out.extend(raw)
        run.clear(); raw.clear()

    i = 0
    while i < len(toks):
        tok = toks[i]
        word = tok.strip(PUNCT)
        d = _ascii_digits(word)
        if word == "at" and run and i + 1 < len(toks) and toks[i + 1].strip(PUNCT) in DIGIT_WORDS:
            word = "aat"  # Bengali eight, written "at": only between digits, or "at the rate" would break
        if word in REPEAT_WORDS and i + 1 < len(toks):
            nxt = toks[i + 1].strip(PUNCT)
            nd = DIGIT_WORDS.get(nxt) or (_ascii_digits(nxt) if _ascii_digits(nxt).isdigit() else None)
            if nd:
                run.append(nd * REPEAT_WORDS[word]); raw += [tok, toks[i + 1]]
                i += 2
                continue
        if word in TENS:
            nxt = toks[i + 1].strip(PUNCT) if i + 1 < len(toks) else ""
            if nxt in UNITS:
                run.append(TENS[word] + UNITS[nxt]); raw += [tok, toks[i + 1]]
                i += 2
                continue
            run.append(TENS[word] + "0"); raw.append(tok)
        elif word in TEENS:
            run.append(TEENS[word]); raw.append(tok)
        elif word in DIGIT_WORDS or d.isdigit():
            run.append(DIGIT_WORDS.get(word, d)); raw.append(tok)
        else:
            flush(i)
            out.append(tok)
        i += 1
    flush(len(toks))
    return " ".join(out)


def normalize(text):
    text = unicodedata.normalize("NFC", text).lower().replace("।", " ").replace(",", " ")
    text = re.sub(r"\b(%s)-(?=[a-z])" % "|".join(TENS), r"\1 ", text)  # "ninety-eight"
    text = NATIVE_DOT.sub(" dot ", NATIVE_AT.sub(" at the rate ", text))
    text = _join_digit_runs(re.sub(r"(?<=\d)-(?=\d)", " ", text))
    text = AT.sub("@", text)
    return SLASH.sub("/", DOT.sub(".", text))


def _split_bank_codes(text):
    """Bank codes in words just before a 7-character branch: 'sbi n 0001234' -> 'SBIN0001234'."""
    for m in BRANCH.finditer(text):
        words = text[:m.start()].split()[-4:]
        for n in range(1, len(words) + 1):
            code = "".join(words[-n:])
            code = MISHEARD_CODES.get(code, code)
            if code in BANK_CODES:
                yield (code + m.group()).upper()
                break


def _squash_spelled(text):
    """'s b i n 0001234' -> 'sbin0001234' so letter-by-letter IFSCs match.
    ponytail: also glues stray single letters in normal speech; only used for the IFSC search."""
    text = re.sub(r"\bi f s c\b", "ifsc", text)  # the spoken label, not part of the code
    return re.sub(r"\b[a-z0-9]\b(?:\s+(?:[a-z]\b|\d+\b))+", lambda m: m.group().replace(" ", ""), text)


def extract(text):
    """Validated identifiers in order of appearance, deduped: [{'type': 'upi', 'value': 'x@ybl'}, ...]."""
    norm = normalize(text)
    found = []

    def add(kind, value):
        item = {"type": kind, "value": value}
        if item not in found:
            found.append(item)

    # Each match is blanked out so its parts (a UPI's digits, an email's domain) aren't counted twice.
    for kind, rx in (("email", EMAIL), ("upi", UPI), ("url", URL)):
        for m in rx.finditer(norm):
            add(kind, m.group())
        norm = rx.sub(" ", norm)
    spelled = " ".join(LETTERS.get(t, t) for t in norm.split())
    for m in IFSC.finditer(_squash_spelled(spelled)):
        add("ifsc", m.group().upper())
    for code in _split_bank_codes(spelled):
        add("ifsc", code)
    for m in DIGITS.finditer(norm):
        mob = MOBILE.match(m.group())
        add("mobile", mob.group(1)) if mob else add("account", m.group())
    return found
