from capture import extract
from guardrail import guard, strip_unknown_tags, violation


def vals(text):
    return [(i["type"], i["value"]) for i in extract(text)]


def test_upi_spoken():
    assert vals("haan ji, ramesh dot kumar at the rate okaxis pe bhejo") == [("upi", "ramesh.kumar@okaxis")]


def test_upi_digits_not_double_counted():
    assert vals("nine eight seven six five four three two one zero at the rate paytm") == [("upi", "9876543210@paytm")]


def test_mixed_language_mobile():
    # Hindi + English + Kannada digits in one breath, with 'double'
    assert vals("number likho nau saat four two ಎರಡು double five 6 7 8") == [("mobile", "9742255678")]


def test_native_script_digits():
    assert vals("ಖಾತೆ ಸಂಖ್ಯೆ ೧೨೩೪೫೬೭೮೯೦೧೨") == [("account", "123456789012")]
    assert vals("नंबर नौ आठ सात छह पाँच चार तीन दो एक शून्य") == [("mobile", "9876543210")]


def test_account_and_spelled_ifsc():
    got = vals("account number 1234 5678 9012 3, IFSC S B I N zero zero zero one two three four")
    assert got == [("ifsc", "SBIN0001234"), ("account", "1234567890123")]


def test_ifsc_with_letter_o_and_full_stop():
    assert vals("IFSC D E M O zero zero zero one two three four.") == [("ifsc", "DEMO0001234")]
    assert vals("number hai nine eight seven six five, four three two one zero.") == [("mobile", "9876543210")]


def test_real_prisma_v25_transcript_in_devanagari():
    got = vals("मेन सी बी आई से बोल रहा हूँ, अकाउंट नंबर लिखो ज़ीरो ज़ीरो ज़ीरो ज़ीरो वन वन वन वन टू टू टू टू थ्री "
               "आई एफ एस सी डी ई एम ओ ज़ीरो ज़ीरो ज़ीरो वन टू थ्री फोर")
    assert got == [("ifsc", "DEMO0001234"), ("account", "0000111122223")]


def test_real_prisma_v3_transcript_code_mixed():
    got = vals("मैं CBI से बोल रहा हूँ, account number लिखो ज़ीरो ज़ीरो ज़ीरो ज़ीरो one one one one two two two two three "
               "IFSC code ज़ीरो ज़ीरो ज़ीरो one two three four।")
    assert got == [("account", "0000111122223")]


def test_ifsc_bank_code_said_as_a_word():
    assert vals("IFSC DEMO zero zero zero one two three four") == [("ifsc", "DEMO0001234")]
    assert vals("IFSC code hai SBIN 0001234") == [("ifsc", "SBIN0001234")]
    assert vals("IFSC code likho. SBI N zero zero zero one two three four.") == [("ifsc", "SBIN0001234")]  # real stream
    assert vals("SBIN 0001234") == [("ifsc", "SBIN0001234")]  # label said in an earlier breath
    assert vals("IFSC DEEMO zero zero zero one two three four.") == [("ifsc", "DEMO0001234")]  # real stream
    # Never invent a bank code from whatever word comes before the digits.
    assert vals("IFSC code 0001234") == []
    assert vals("IFSC likh 0001234") == []
    assert vals("IFSC SBI 0001234") == []


def test_native_script_at_the_rate_and_dot():
    assert vals("cbi डॉट verify एट द रेट demo पे भेजो") == [("upi", "cbi.verify@demo")]
    assert vals("cbi ಡಾಟ್ verify ಅಟ್ ದ ರೇಟ್ demo") == [("upi", "cbi.verify@demo")]


def test_mobile_with_country_code():
    assert vals("call me on +91 98450 12345") == [("mobile", "9845012345")]


def test_short_number_words_stay_words():
    assert vals("beta doosra account do na, ek minute") == []
    assert vals("pay 50000 rupees in 2 hours") == []


def test_email_is_not_upi_and_links():
    assert vals("mail cbi.officer@gmail.com or open rbi-verify dot in slash kyc") == [
        ("email", "cbi.officer@gmail.com"), ("url", "rbi-verify.in/kyc")]
    assert vals("mobile 98450-12345") == [("mobile", "9845012345")]
    assert ("url", "http://bit.ly/x9") in vals("click http://bit.ly/x9 now")


def test_guardrail_blocks_leaks():
    assert violation("mera aadhaar 2345 6789 0123 hai") == "digits"
    assert violation("OTP hai saat do nau ek chaar paanch") == "digits"
    assert violation("PAN ABCDE1234F") == "pan"
    assert violation("haan beta, main abhi bank jaati hoon") is None
    assert guard("card 4111 1111 1111 1111", "kn").startswith("<sigh>")


def test_guardrail_sees_through_ellipses_and_sound_tags():
    assert violation("9… 8… 7… 6… 5… 4…") == "digits"
    assert violation("1234 <pauses> 5678") == "digits"
    # The exact read-back Ajji produced on a live call is still allowed.
    assert violation("0000… <clears throat> 1… 1… 1… 1… <pauses> 2… 2… 2… 2… 3.", ["0000111122223"]) is None


def test_real_prisma_spellings_of_digit_words():
    assert vals("Shunny shunny shunny shunny, ek ek ek ek, do do do do, teen.") == [("account", "0000111122223")]
    assert vals("poojyam poojyam poojyam poojyam onru onru onru onru irandu irandu irandu irandu moonru.") == [
        ("account", "0000111122223")]
    assert vals("suna suna suna suna, okati okati okati okati, rendu rendu rendu rendu, moodu.") == [
        ("account", "0000111122223")]


def test_at_means_eight_only_between_digits():
    assert vals("tin ek char ek paanch noy dui choy paanch tin paanch at noy.") == [("account", "3141592653589")]
    assert vals("nine eight seven six at the rate paytm") == [("upi", "9876@paytm")]


def test_punctuation_stuck_to_words_and_comma_spelled_letters():
    # Both from ScamSim transcripts: markdown around a number, and an IFSC spelled with commas.
    assert vals("Account number is **three zero one eight one five nine zero eight three zero one six six**.") == [
        ("account", "30181590830166")]
    assert vals("IFSC: K, V, B, L, zero, one, three, one, eight, six, zero.") == [("ifsc", "KVBL0131860")]


def test_short_digits_in_a_spoken_upi_id():
    assert vals("UPI hai verma three two at the rate ibl") == [("upi", "verma32@ibl")]
    assert vals("sunil dot k three nine at the rate ybl") == [("upi", "sunil.k39@ybl")]
    assert vals("ramesh dot three two at the rate paytm") == [("upi", "ramesh.32@paytm")]
    assert vals("ek do teen bhejo") == []  # short numbers elsewhere stay words


def test_numbers_read_in_pairs():
    assert vals("mobile ninety eight forty five, zero one, twenty three forty five") == [("mobile", "9845012345")]
    assert vals("number nine eight seven, sixty-five, double zero, twelve, three") == [("mobile", "9876500123")]
    assert vals("twenty thousand rupees bhejo") == []


def test_invented_sound_tags_are_removed():
    assert strip_unknown_tags("<babu>, <coughs> ಯಾರು <murmurs> ಅಪ್ಪ? <clears throat>") == ", <coughs> ಯಾರು ಅಪ್ಪ? <clears throat>"
    assert guard("<babu> ಯಾರು?", "kn") == "ಯಾರು?"


def test_guardrail_allows_two_identifiers_read_back_to_back():
    allowed = ["DEMO0001234", "0000111122223"]
    # The exact reply it wrongly blocked on a live call.
    assert violation("D E M O ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ ಒಂದು ಎರಡು ಮೂರು ನಾಲ್ಕು ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ ಒಂದು ಒಂದು ಒಂದು ಒಂದು "
                     "ಎರಡು ಎರಡು ಎರಡು ಎರಡು ಮೂರು", allowed) is None
    # Invented digits still can't hide next to real ones or be stitched from fragments.
    assert violation("00012340000111122223 998877", allowed) == "digits"
    assert violation("0001234998877", allowed) == "digits"
    assert violation("000111000123", allowed) == "digits"


def test_guardrail_allows_read_back():
    captured = ["1234567890123"]
    assert violation("ek do teen chaar paanch chhe saat... sahi hai?", captured) is None
    assert violation("9876543210 sahi hai?", captured) == "digits"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
