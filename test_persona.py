from capture import NATIVE_DIGITS, normalize
from elicit import Call
from guardrail import STALL, violation
from persona import PERSONAS, system_prompt


def test_prompt_carries_identity_and_directive():
    directive = Call().hear("Main CBI se bol raha hoon")
    for name, p in PERSONAS.items():
        prompt = system_prompt(name, directive)
        assert p["identity"] in prompt and prompt.endswith(directive)


def test_read_back_gets_exact_digit_words_the_guardrail_allows():
    prompt = system_prompt("ajji", "Read back DEMO0001234 slowly, digit by digit.")
    spoken = "D E M O ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ ಒಂದು ಎರಡು ಮೂರು ನಾಲ್ಕು"
    assert spoken in prompt
    assert violation(spoken, ["DEMO0001234"]) is None
    assert violation(spoken) == "digits"  # the same words are blocked unless the caller gave them


def test_every_language_can_read_back_and_cannot_leak_digits():
    for name, p in PERSONAS.items():
        words = NATIVE_DIGITS[p["lang"]]
        assert len(words) == 10, name
        spoken = " ".join(words[int(d)] for d in "9876543210")
        assert normalize(spoken) == "9876543210", name  # capture and guardrail both read this language's digits
        assert violation(spoken) == "digits", name  # an invented number is blocked...
        assert violation(spoken, ["9876543210"]) is None, name  # ...and the caller's own is allowed
        assert p["lang"] in STALL, name
        assert spoken in system_prompt(name, "Read back 9876543210 slowly."), name


def test_persona_text_is_guardrail_clean():
    # Nothing the persona is given to say or know may look like real data.
    for p in PERSONAS.values():
        for text in (p["greeting"], p["identity"], STALL[p["lang"]], *p["fillers"], *p["backchannels"]):
            assert violation(text) is None, text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
