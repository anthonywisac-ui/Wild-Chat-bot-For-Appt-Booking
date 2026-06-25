# bots/appointment/services/language_policy.py
#
# Shared language constraint injected into every AI prompt that produces
# patient-facing text. Without this, the model sometimes defaults to
# Devanagari Hindi script when asked for "Urdu" — which this clinic's
# patients can't read comfortably. Roman Urdu (Urdu words spelled in
# English/Latin letters) is what's actually expected here.

LANGUAGE_RULE = (
    "LANGUAGE RULE: Reply only in Roman Urdu (Urdu language written using English/Latin "
    "letters, e.g. 'aap kaise hain'), plain English, or Arabic — matching whichever language "
    "the patient is using. NEVER reply in Hindi/Devanagari script (e.g. कैसे हैं), even if the "
    "patient writes in Hindi script — respond in Roman Urdu instead. Do not mix Devanagari "
    "characters into your reply under any circumstance."
)
