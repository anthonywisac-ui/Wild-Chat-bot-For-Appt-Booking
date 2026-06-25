# bots/appointment/services/language_policy.py
#
# Shared language constraint injected into every AI prompt that produces
# patient-facing text. The small/fast model used here generated inconsistent,
# sometimes broken Roman Urdu / Hindi script even when the patient was
# writing in plain English — unacceptable for a professional clinic. The
# clinic has decided: English only, full stop, no exceptions.

LANGUAGE_RULE = (
    "LANGUAGE RULE: Respond ONLY in professional, clear English. "
    "NEVER use Urdu, Hindi, Roman Urdu, Arabic, or any mixed-language phrasing, "
    "even if the patient writes in another language or script. "
    "If the patient writes in Urdu/Hindi/Arabic, politely respond in English. "
    "All buttons, lists, confirmations, and messages must be English only."
)
