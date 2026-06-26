# bots/appointment/departments.py
#
# Treatment category catalog for the clinic appointment bot — 6 categories
# matching the clinic's real service lines. Each just needs a slug + label +
# description used for AI symptom-matching and for the structured
# Treatment Enquiry / Book Appointment category lists.

DEPARTMENTS = {
    "skin": {
        "label": "Skin Treatments",
        "emoji": "",
        "description": (
            "Facials, peels, acne, pigmentation, brightening, anti-aging skin treatments: "
            "HydraFacial, Chemical Peel, Microneedling, Microneedling + PRP, PRP Skin "
            "Rejuvenation, Acne Treatment, Pigmentation Treatment, Laser Skin Resurfacing, "
            "Skin Brightening."
        ),
    },
    "hair": {
        "label": "Hair Treatments",
        "emoji": "",
        "description": (
            "Hair fall, thinning, and scalp treatments: PRP Hair Therapy, Hair Growth "
            "Therapy, Mesotherapy, Scalp Analysis."
        ),
    },
    "laser": {
        "label": "Laser Treatments",
        "emoji": "",
        "description": (
            "Laser-based hair removal and skin treatments: Laser Hair Removal, Pigmentation "
            "Laser, Acne Scar Laser, Carbon Laser Facial, Laser Skin Resurfacing."
        ),
    },
    "injectables": {
        "label": "Injectables",
        "emoji": "",
        "description": (
            "Botox and dermal fillers: Botox, Lip Fillers, Cheek Fillers, Jawline Fillers, "
            "Under Eye Fillers."
        ),
    },
    "body": {
        "label": "Body Treatments",
        "emoji": "",
        "description": (
            "Body shaping and tightening: Body Contouring, Fat Dissolving Injections, "
            "HIFU Tightening, RF Tightening, Cellulite Reduction."
        ),
    },
    "dental": {
        "label": "Dental Treatments",
        "emoji": "",
        "description": (
            "Teeth and gum care: Teeth Whitening, Scaling & Polishing, Dental Veneers, "
            "Dental Crowns, Root Canal Treatment, Dental Implants, Smile Design."
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
