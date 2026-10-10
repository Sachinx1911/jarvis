from jarvis.memory.translit import (
    add_script_forms,
    canonical_roman,
    expand_words,
    index_variants,
    query_keys,
    roman_forms,
    text_keys,
    to_devanagari,
    words,
)


def test_devanagari_words_stay_whole():
    # Python's \w alone splits these at every vowel sign.
    assert words("माझा कॉलेज प्रोजेक्ट, आठवड्यात।") == ["माझा", "कॉलेज", "प्रोजेक्ट", "आठवड्यात"]


def test_roman_forms_match_common_romanized_spellings():
    cases = {
        "माझा": "maza", "बहीण": "bahin", "दवाखाना": "davakhana", "आई": "ai", "चहा": "chaha",
        "गाडी": "gadi", "महिन्यात": "mahinyat", "गेल्या": "gelya", "काल": "kal", "ज्ञान": "dnyan",
        "मंगळवार": "mangalvar", "करतो": "karto", "आठवड्यात": "athavdyat", "डॉक्टर": "doktar",
        "प्लॅन": "plan", "आंबा": "amba",
    }
    for dev, roman in cases.items():
        assert roman in roman_forms(dev), (dev, roman_forms(dev))


def test_medial_schwa_variant_kept_too():
    assert roman_forms("करतो") == ["karto", "karato"]
    assert set(roman_forms("मित्र")) == {"mitr", "mitra"}


def test_canonical_roman_absorbs_spelling_variants():
    assert canonical_roman("aai") == canonical_roman("ai") == "ai"
    assert canonical_roman("majha") == canonical_roman("maza")
    assert canonical_roman("wadil") == "vadil"
    assert canonical_roman("pakka") == "paka"
    assert canonical_roman("gaadi") == roman_forms("गाडी")[0]


def test_to_devanagari_rough_guess():
    assert to_devanagari("bahin") == "बहिन"
    assert to_devanagari("maza") == "मझा"
    assert to_devanagari("pakka") == "पक्का"
    assert to_devanagari("123") == "" and to_devanagari("") == ""


def test_expand_words_adds_keys_and_drops_devanagari_stopwords():
    out = expand_words(["माझा", "भाऊ", "आहे", "gaadi"], {"maza", "ahe"})
    assert "माझा" not in out and "आहे" not in out          # their romanized keys are stopwords
    assert {"भाऊ", "bhau", "gaadi", "gadi"} <= set(out)


def test_index_variants_only_adds_new_keys():
    extra = index_variants("माझी बहीण pune")
    assert "bahin" in extra.split() and "pune" not in extra.split()


def test_add_script_forms_both_ways():
    out = add_script_forms("sister pune बहीण bahin", english_text="The user's sister lives in Pune.").split()
    assert "bahin" in out and "बहिन" in out          # Devanagari of the romanized word
    assert not any(w for w in out if w.startswith("सि"))  # English words get no Devanagari guess
    assert add_script_forms("") == ""


def test_text_and_query_keys_meet_across_inflections():
    raw = text_keys("आज २ पुस्तकं घेतली")
    assert "pustakan" in raw.split()
    keys = query_keys(["pustaka"])
    assert "pustak" in keys and any(k in raw for k in keys)
