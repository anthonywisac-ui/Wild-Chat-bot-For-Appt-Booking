# bots/appointment/departments.py
#
# Department catalog for the clinic appointment bot. Keep this list small
# and add more departments here as the business grows (each just needs a
# slug + label + description used for AI symptom-matching).

DEPARTMENTS = {
    "dental": {
        "label": "Dental",
        "emoji": "🦷",
        "description": (
            "Teeth, gums, and mouth care: cleanings, fillings, root canals, "
            "extractions, braces/orthodontics, crowns, whitening, toothache, "
            "bleeding gums, jaw pain, bad breath."
        ),
    },
    "aesthetic": {
        "label": "Aesthetic & Cosmetic",
        "emoji": "✨",
        "description": (
            "Skin and appearance treatments: Botox, fillers, laser hair removal, "
            "facials, chemical peels, acne scars, anti-aging, skin whitening, "
            "hydrafacial, body contouring, hair transplant consultations."
        ),
    },
}


def get_department(slug: str) -> dict:
    return DEPARTMENTS.get(slug, {})


def department_list_text() -> str:
    return "\n".join(f"{d['emoji']} {d['label']}" for d in DEPARTMENTS.values())


def department_catalog_for_ai() -> str:
    """A compact text block describing each department, used to prompt the LLM for triage matching."""
    lines = []
    for slug, d in DEPARTMENTS.items():
        lines.append(f"- {slug} ({d['label']}): {d['description']}")
    return "\n".join(lines)
