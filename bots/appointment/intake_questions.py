# bots/appointment/intake_questions.py
#
# Per-category patient intake questionnaire, compacted from the clinic's full
# spec into the questions that actually change clinical/sales handling.
# Each entry:
#   key       - memory field this answer is stored in. Re-uses existing flat
#               memory keys (allergies, medical_conditions, current_medications,
#               pregnancy_status, previous_treatments, concern, goal) wherever the
#               question is conceptually the same field, just asked with
#               category-specific wording — keeps PatientProfile/CRM persistence
#               working unchanged. Genuinely new fields use a new key.
#   question  - exact text shown to the patient
#   type      - "buttons" (<=3 options, WhatsApp button limit), "list" (4-10
#               options), or "text_or_skip" (free text, with a Skip/None button)
#   options   - [(value, label), ...] for buttons/list
#   skip_if   - optional string flag the engine checks against memory before
#               asking; currently only "gender_male" is used (never ask a male
#               patient about pregnancy/breastfeeding)

INTAKE_QUESTIONS = {
    "skin": [
        {"key": "concern", "question": "What is your main skin concern?", "type": "list", "options": [
            ("acne", "Acne"), ("scars", "Acne scars"), ("pigmentation", "Pigmentation/Dark spots"),
            ("dull", "Dull / Uneven skin"), ("aging", "Fine lines / Aging"), ("other", "Other"),
        ]},
        {"key": "skin_duration", "question": "How long have you had this concern?", "type": "buttons", "options": [
            ("lt3m", "<3 months"), ("3to12m", "3-12 months"), ("gt1y", ">1 year"),
        ]},
        {"key": "skin_type", "question": "What is your skin type?", "type": "buttons", "options": [
            ("oily", "Oily"), ("dry", "Dry"), ("combo", "Combo/Sensitive"),
        ]},
        {"key": "previous_treatments", "question": "Have you tried any previous skin treatments?", "type": "text_or_skip"},
        {"key": "allergies", "question": "Any skin allergies, active infections, or wounds?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "current_medications", "question": "Taking Accutane/Isotretinoin, blood thinners, or steroids?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "pregnancy_status", "question": "Are you pregnant or breastfeeding?", "type": "buttons", "options": [
            ("no", "No"), ("yes", "Yes"),
        ], "skip_if": "gender_male"},
    ],
    "hair": [
        {"key": "concern", "question": "What is your main hair concern?", "type": "list", "options": [
            ("fall", "Hair fall"), ("thinning", "Hair thinning"), ("bald_spots", "Bald spots"),
            ("weak", "Weak hair"), ("scalp", "Scalp issues"),
        ]},
        {"key": "hair_duration", "question": "When did you start noticing hair loss?", "type": "buttons", "options": [
            ("lt6m", "<6 months"), ("6to12m", "6-12 months"), ("gt1y", ">1 year"),
        ]},
        {"key": "hair_area", "question": "Where is the hair loss mainly occurring?", "type": "list", "options": [
            ("hairline", "Hairline"), ("crown", "Crown area"), ("overall", "Overall thinning"), ("patchy", "Patchy areas"),
        ]},
        {"key": "previous_treatments", "question": "Any previous hair treatments (PRP / medication / transplant)?", "type": "text_or_skip"},
        {"key": "medical_conditions", "question": "Any scalp conditions (dandruff, itching, infection)?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "current_medications", "question": "Are you currently taking hair loss medication?", "type": "buttons", "options": [
            ("no", "No"), ("yes", "Yes"),
        ]},
        {"key": "pregnancy_status", "question": "Are you pregnant or breastfeeding?", "type": "buttons", "options": [
            ("no", "No"), ("yes", "Yes"),
        ], "skip_if": "gender_male"},
    ],
    "laser": [
        {"key": "treatment_area", "question": "Which area would you like to treat?", "type": "list", "options": [
            ("face", "Face"), ("underarms", "Underarms"), ("arms", "Arms"), ("legs", "Legs"),
            ("bikini", "Bikini"), ("back", "Back"), ("full_body", "Full body"),
        ]},
        {"key": "laser_first_time", "question": "Is this your first laser treatment?", "type": "buttons", "options": [
            ("yes", "Yes"), ("no", "No"),
        ]},
        {"key": "skin_tone", "question": "What is your skin tone?", "type": "buttons", "options": [
            ("fair", "Fair"), ("medium", "Medium"), ("dark", "Dark"),
        ]},
        {"key": "recent_procedures", "question": "Recent waxing, chemical peel, or sun tanning in this area?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "allergies", "question": "Do you have sensitive skin or any known allergies?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "current_medications", "question": "Taking any photosensitive medication?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "pregnancy_status", "question": "Are you pregnant or breastfeeding?", "type": "buttons", "options": [
            ("no", "No"), ("yes", "Yes"),
        ], "skip_if": "gender_male"},
    ],
    "injectables": [
        {"key": "concern", "question": "What would you like to improve?", "type": "list", "options": [
            ("wrinkles", "Wrinkles"), ("lip_volume", "Lip volume"), ("cheek_volume", "Cheek volume"),
            ("jawline", "Jawline definition"), ("under_eye", "Under-eye area"), ("other", "Other"),
        ]},
        {"key": "previous_treatments", "question": "Have you had fillers or Botox before? If so, when?", "type": "text_or_skip"},
        {"key": "goal", "question": "What result are you looking for?", "type": "buttons", "options": [
            ("natural", "Natural enhancement"), ("noticeable", "Noticeable change"),
        ]},
        {"key": "allergies", "question": "Any allergies, including a past reaction to fillers/injections?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "current_medications", "question": "Taking any blood-thinning medication?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "medical_conditions", "question": "Do you have any autoimmune conditions?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "pregnancy_status", "question": "Are you pregnant or breastfeeding?", "type": "buttons", "options": [
            ("no", "No"), ("yes", "Yes"),
        ], "skip_if": "gender_male"},
    ],
    "body": [
        {"key": "concern", "question": "What is your main concern?", "type": "list", "options": [
            ("fat_reduction", "Fat reduction"), ("tightening", "Body tightening"), ("cellulite", "Cellulite"),
            ("laxity", "Skin laxity"), ("shaping", "Body shaping"),
        ]},
        {"key": "treatment_area", "question": "Which area would you like to treat?", "type": "list", "options": [
            ("abdomen", "Abdomen"), ("arms", "Arms"), ("thighs", "Thighs"), ("waist", "Waist"), ("other", "Other"),
        ]},
        {"key": "previous_treatments", "question": "Tried weight loss programs or body treatments before?", "type": "text_or_skip"},
        {"key": "body_stats", "question": "What is your current weight & height? (optional, skip if you're not sure)", "type": "text_or_skip"},
        {"key": "medical_conditions", "question": "Any implants, medical devices, or medical conditions?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "current_medications", "question": "Are you currently taking any medication?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "pregnancy_status", "question": "Are you pregnant or breastfeeding?", "type": "buttons", "options": [
            ("no", "No"), ("yes", "Yes"),
        ], "skip_if": "gender_male"},
    ],
    "dental": [
        {"key": "concern", "question": "What is your main dental concern?", "type": "list", "options": [
            ("pain", "Tooth pain"), ("missing", "Missing tooth"), ("broken", "Broken tooth"),
            ("yellow", "Yellow teeth"), ("gum", "Gum problems"), ("smile", "Smile improvement"),
        ]},
        {"key": "dental_xray", "question": "Do you have dental X-rays available?", "type": "buttons", "options": [
            ("yes", "Yes"), ("no", "No"),
        ]},
        {"key": "recent_dentist_visit", "question": "Have you visited a dentist recently?", "type": "buttons", "options": [
            ("yes", "Yes"), ("no", "No"),
        ]},
        {"key": "allergies", "question": "Allergic to any dental materials/medicines, or gum bleeding?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "current_medications", "question": "Taking blood thinners?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
        {"key": "medical_conditions", "question": "Do you have diabetes or any other medical conditions?", "type": "buttons", "options": [
            ("none", "None"), ("yes", "Yes"),
        ]},
    ],
}


def next_intake_question(department: str, memory: dict) -> dict | None:
    """Returns the next unanswered question for this department, or None when
    the whole intake sequence is complete. Conditionally skips per skip_if."""
    for q in INTAKE_QUESTIONS.get(department, []):
        if memory.get(q["key"]):
            continue
        if q.get("skip_if") == "gender_male" and (memory.get("gender") or "").strip().lower() == "male":
            continue
        return q
    return None
