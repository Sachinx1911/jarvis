"""Health, money, identity documents, other people's contact details and politics are
"sensitive" in code, not only in the prompts; family names, where things are kept,
schedules and preferences stay "normal". Synthetic examples only (public repo)."""

import json

import pytest

from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.memory.extract import Extractor
from jarvis.memory.model import Memory
from jarvis.memory.sensitivity import inherit_sensitive, raise_sensitivity, sensitive_categories
from jarvis.memory.store import MemoryStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision

DECISION = RouteDecision("memory_extractor", "fake", "fake-1", "low", "test")


@pytest.mark.parametrize("text,category", [
    # English
    ("Dad was diagnosed with diabetes last year", "health"),
    ("My BP reading was 140/90 this morning", "health"),
    ("fasting sugar 110 in the last report", "health"),
    ("I take 500 mg of the tablet after dinner", "health"),
    ("Mom has an appointment at the hospital on Friday", "health"),
    ("My salary is credited on the 1st", "money"),
    ("Home loan EMI is 25,000 on the 5th", "money"),
    ("bank balance should stay above 10k", "money"),
    ("passport number ends with 42", "identity"),
    ("Priya's email is priya.demo@example.com", "contact"),
    ("Ramesh's mobile is 98765 43210", "contact"),
    ("Uncle's address is Flat no 12, Demo Society", "contact"),
    ("I voted for the independent candidate", "politics"),
    ("He is a BJP party worker", "politics"),
    # romanized Marathi
    ("babanna madhumeh ahe", "health"),
    ("mi kal davakhanyat gelo hoto", "health"),
    ("maza pagar 1 tarkhela yeto", "money"),
    ("gharacha karja hapta 5 tarkhela jato", "money"),
    ("aadhar cha number lihun thev", "identity"),
    ("mamancha patta Kothrud la ahe", "contact"),
    ("mi matdan kela", "politics"),
    ("nivadnukit kontya umedvarala nivadla", "politics"),
    # Devanagari Marathi
    ("बाबांना मधुमेह आहे", "health"),
    ("आईचा रक्तदाब वाढला आहे", "health"),
    ("मला अ\u200dॅलर्जी आहे", "health"),        # spelled with a zero-width joiner
    ("माझा पगार एक तारखेला येतो", "money"),
    ("घराच्या कर्जाचा हप्ता पाच तारखेला", "money"),
    ("आधार कार्डचा नंबर", "identity"),
    ("रमेशचा मोबाईल नंबर ९८७६५४३२१०", "contact"),   # Devanagari digits
    ("मामांचा पत्ता लिहून ठेव", "contact"),
    ("मी निवडणुकीत मतदान केले", "politics"),
    ("तो शिवसेनेचा कार्यकर्ता आहे", "politics"),
])
def test_sensitive_examples(text, category):
    assert category in sensitive_categories(text)


@pytest.mark.parametrize("text", [
    # English: family names, where things are kept, schedules, preferences, work
    "My sister's name is Priya and she lives in Pune",
    "Car keys are in the drawer near the door",
    "The medicine box is in the kitchen cupboard",
    "Passport is kept in the bedroom locker",
    "I keep my passport photocopies in the blue folder",
    "Gym every morning at 6",
    "doctor appointment every Tuesday at 5 pm",
    "Prefers short answers in bullet points",
    "No sugar in my tea",
    "Birthday party for Aarav on Sunday",
    "Always address me as Sachin",
    "Never send email without asking me first",
    "Demo project runs with make run; order 1234 shipped",
    "My office wifi network is called DemoNet-5G",
    "My uncle works in the hospitality industry",
    "Our farmhouse is in Karjat",
    "The bank is next to the station",
    # romanized Marathi
    "aai che naav Sunita ahe",
    "chavi drawer madhe ahe",
    "mala chaha avadto, sakhar nako",
    "somvari sakali gym la jato",
    "orbit project npm start ne chalto",
    # Devanagari Marathi
    "माझ्या बहिणीचं नाव मीरा आहे",
    "चाव्या ड्रॉवरमध्ये ठेवल्या आहेत",
    "पासपोर्ट कपाटात ठेवला आहे",
    "दर सोमवारी सकाळी जिमला जातो",
    "मला चहा आवडतो",
    "कर्जतला आमचे फार्महाउस आहे",
    "प्रत्येक ईमेल पाठवण्याआधी मला विचार",
])
def test_normal_examples_stay_normal(text):
    assert sensitive_categories(text) == []


def test_raise_only_never_lower_never_touch_secret():
    m = Memory(name="bp tablet", evidence="bp tablet every morning")
    assert raise_sensitivity(m) == ["health"] and m.sensitivity == "sensitive"
    pub = Memory(name="loan emi date", evidence="loan EMI on the 5th", sensitivity="public")
    assert raise_sensitivity(pub) == ["money"] and pub.sensitivity == "sensitive"
    already = Memory(name="likes tea", evidence="I like tea", sensitivity="sensitive")
    assert raise_sensitivity(already) == [] and already.sensitivity == "sensitive"
    secret = Memory(name="bp", evidence="bp tablet", sensitivity="secret")
    assert raise_sensitivity(secret) == [] and secret.sensitivity == "secret"
    normal = Memory(name="likes tea", evidence="I like tea")
    assert raise_sensitivity(normal) == [] and normal.sensitivity == "normal"
    # every text field counts, e.g. the model's English summary of a Marathi note
    summary = Memory(name="monthly money", evidence="dar mahinyala paise yetat",
                     summary_en="The user's salary arrives every month.")
    assert raise_sensitivity(summary) == ["money"]


def test_inherit_sensitive():
    new = Memory(name="x", evidence="x")
    assert inherit_sensitive(new, Memory(name="y", evidence="y", sensitivity="sensitive"))
    assert new.sensitivity == "sensitive"
    plain = Memory(name="x", evidence="x")
    assert not inherit_sensitive(plain, Memory(name="y", evidence="y")) and plain.sensitivity == "normal"


# ---- the extractor enforces it ----

@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    mem = MemoryStore(tmp_path, store)
    yield mem, AuditLog(tmp_path / "data" / "audit.jsonl")
    store.close()


def _cand(**kw):
    base = {"name": "bike service", "type": "fact", "subject": "bike", "summary_en": "The bike needs service every 3000 km.",
            "keywords": "bike service km", "when_to_use": "bike maintenance", "sensitivity": "normal",
            "evidence": "my bike needs servicing every 3000 km", "source": "user-said", "body": "every 3000 km"}
    return {**base, **kw}


def _saved_events(audit: AuditLog) -> list[dict]:
    lines = audit.path.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == "memory_saved"]


@pytest.mark.parametrize("said,summary", [
    ("Dad was diagnosed with thyroid last month", "Dad has a thyroid condition."),
    ("babanna madhumeh ahe", "Dad has diabetes."),
    ("मी निवडणुकीत मतदान केले", "The user voted in the election."),
])
def test_extracted_candidate_marked_normal_by_model_is_raised(env, said, summary):
    mem, audit = env
    ex = Extractor(mem, FakeProvider(script=[{"json": {"candidates": [
        _cand(name="family detail", subject="family", summary_en=summary, keywords="family", evidence=said, body=said),
    ]}}]), DECISION, audit)
    assert ex.extract_session([said])[0][0] == "ADD"
    assert mem.list()[0].sensitivity == "sensitive"
    assert _saved_events(audit)[0]["auto_sensitive"]


@pytest.mark.parametrize("said,summary", [
    ("my bike needs servicing every 3000 km", "The bike needs service every 3000 km."),
    ("aai che naav Sunita ahe", "The user's mother is named Sunita."),
    ("चाव्या ड्रॉवरमध्ये ठेवल्या आहेत", "The keys are kept in the drawer."),
])
def test_extracted_normal_candidate_stays_normal(env, said, summary):
    mem, audit = env
    ex = Extractor(mem, FakeProvider(script=[{"json": {"candidates": [
        _cand(name="home detail", subject="home", summary_en=summary, keywords="home", evidence=said, body=said),
    ]}}]), DECISION, audit)
    assert ex.extract_session([said])[0][0] == "ADD"
    assert mem.list()[0].sensitivity == "normal" and _saved_events(audit)[0]["auto_sensitive"] == []


def test_model_sensitive_label_is_never_lowered(env):
    mem, audit = env
    ex = Extractor(mem, FakeProvider(script=[{"json": {"candidates": [_cand(sensitivity="sensitive")]}}]),
                   DECISION, audit)
    ex.extract_session(["my bike needs servicing every 3000 km"])
    assert mem.list()[0].sensitivity == "sensitive"


def test_update_into_normal_memory_makes_it_sensitive(env):
    mem, audit = env
    old = mem.save(Memory(name="dad morning walk", subject="dad", summary_en="Dad walks every morning.",
                          keywords="dad walk morning", evidence="baba roj sakali firayla jatat"))
    said = "baba walk nantar bp chi goli ghetat"
    ex = Extractor(mem, FakeProvider(script=[
        {"json": {"candidates": [_cand(name="dad walk tablet", subject="dad", keywords="dad walk tablet",
                                       summary_en="Dad takes a BP tablet after his morning walk.",
                                       evidence=said, body="BP tablet after the walk")]}},
        {"json": {"action": "UPDATE", "target_id": old.id}},
    ]), DECISION, audit)
    assert ex.extract_session([said]) == [("UPDATE", old.id)]
    assert mem.get(old.id).sensitivity == "sensitive"


def test_superseding_a_sensitive_memory_stays_sensitive(env):
    mem, audit = env
    old = mem.save(Memory(name="mom tablet time", subject="mom", summary_en="Mom's tablet is at 9 pm.",
                          keywords="mom tablet time", evidence="aai chi goli 9 vajta", sensitivity="sensitive"))
    said = "aai chi goli ata 10 vajta"
    ex = Extractor(mem, FakeProvider(script=[
        {"json": {"candidates": [_cand(name="mom tablet time", subject="mom", keywords="mom tablet time",
                                       summary_en="Mom's tablet is now at 10 pm.", evidence=said, body="10 pm")]}},
        {"json": {"action": "SUPERSEDE", "target_id": old.id}},
    ]), DECISION, audit)
    action, new_id = ex.extract_session([said])[0]
    assert action == "SUPERSEDE" and mem.get(new_id).sensitivity == "sensitive"


@pytest.mark.parametrize("text", ["माझा पगार एक तारखेला येतो", "mi kal davakhanyat gelo hoto",
                                  "Ramesh's mobile is 98765 43210"])
def test_remember_sensitive_text_stays_local(env, text):
    """The memory_extractor route allows P1 only: sensitive notes are not sent for enrichment."""
    mem, audit = env
    provider = FakeProvider()
    m = Extractor(mem, provider, DECISION, audit).remember(text)
    assert m.sensitivity == "sensitive" and provider.requests == []
    assert _saved_events(audit)[0]["auto_sensitive"]


def test_remember_checks_the_models_enrichment_too(env):
    mem, audit = env
    provider = FakeProvider(script=[{"json": {
        "name": "Monthly money", "type": "fact", "subject": "money", "summary_en": "The user's salary arrives on the 1st.",
        "keywords": "salary monthly", "when_to_use": "money", "sensitivity": "normal"}}])
    m = Extractor(mem, provider, DECISION, audit).remember("dar mahinyala 1 tarkhela paise yetat")
    assert len(provider.requests) == 1 and m.sensitivity == "sensitive"


def test_remember_normal_text_still_enriched(env):
    mem, audit = env
    provider = FakeProvider(script=[{"json": {
        "name": "Gym time", "type": "fact", "subject": "gym", "summary_en": "The user goes to the gym at 6 am.",
        "keywords": "gym morning vyayam", "when_to_use": "schedule", "sensitivity": "normal"}}])
    m = Extractor(mem, provider, DECISION, audit).remember("maza gym roj sakali 6 vajta asto")
    assert m.sensitivity == "normal" and m.summary_en == "The user goes to the gym at 6 am."
