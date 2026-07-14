"""
Archetype Generator — Produces N synthetic customer personas from archetype definitions.

Each persona inherits traits from a base archetype and adds randomized noise
(age, tech level, patience, language style, demographics, optional quirk)
to create diverse but statistically grounded feedback profiles.
"""

import json
import random
from pathlib import Path
from typing import Any

PROFILES_PATH = Path(__file__).parent.parent / "profiles.json"

LANGUAGE_STYLES = ["formal", "casual", "terse", "emoji-heavy"]

LANGUAGE_STYLE_WEIGHTS: dict[str, list[float]] = {
    "power_user":            [0.3, 0.3, 0.3, 0.1],
    "casual_user":           [0.05, 0.5, 0.15, 0.3],
    "privacy_skeptic":       [0.5, 0.3, 0.15, 0.05],
    "change_resistant":      [0.2, 0.3, 0.4, 0.1],
    "early_adopter":         [0.1, 0.4, 0.1, 0.4],
    "budget_conscious":      [0.2, 0.4, 0.3, 0.1],
    "accessibility_advocate":[0.4, 0.3, 0.2, 0.1],
    "enterprise_admin":      [0.6, 0.2, 0.15, 0.05],
    "newcomer":              [0.1, 0.5, 0.1, 0.3],
    "data_driven":           [0.4, 0.2, 0.3, 0.1],
    "social_sharer":         [0.05, 0.35, 0.05, 0.55],
}


def load_profiles(path: Path | None = None) -> dict[str, Any]:
    p = path or PROFILES_PATH
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _pick_weighted(options: list[str], weights: list[float]) -> str:
    return random.choices(options, weights=weights, k=1)[0]


def _pick_tech_level(weights: dict[str, float]) -> str:
    levels = list(weights.keys())
    probs = list(weights.values())
    return _pick_weighted(levels, probs)


def _pick_demographic(category: list[dict[str, Any]]) -> dict[str, str]:
    ids = [item["id"] for item in category]
    weights = [item["weight"] for item in category]
    labels = [item["label"] for item in category]
    idx = random.choices(range(len(ids)), weights=weights, k=1)[0]
    return {"id": ids[idx], "label": labels[idx]}


def generate_personas(total: int, profiles: dict[str, Any] | None = None, seed: int | None = None) -> list[dict[str, Any]]:
    """Generate *total* persona dicts distributed across archetypes.

    Returns a shuffled list so batch order doesn't cluster by archetype.
    """
    if seed is not None:
        random.seed(seed)

    if profiles is None:
        profiles = load_profiles()

    archetypes = profiles["archetypes"]
    quirk_pool = profiles.get("quirk_pool", [])
    demographics = profiles.get("demographics", {})

    allocated: list[tuple[dict, int]] = []
    remaining = total

    for i, arch in enumerate(archetypes):
        if i == len(archetypes) - 1:
            count = remaining
        else:
            count = max(1, round(total * arch["percentage"]))
            count = min(count, remaining)
        remaining -= count
        allocated.append((arch, count))

    personas: list[dict[str, Any]] = []
    persona_index = 0

    for arch, count in allocated:
        arch_id = arch["id"]
        lang_weights = LANGUAGE_STYLE_WEIGHTS.get(arch_id, [0.25] * 4)

        for _ in range(count):
            age = random.randint(arch["age_range"][0], arch["age_range"][1])
            tech_level = _pick_tech_level(arch["tech_level_weights"])
            patience = random.randint(arch["patience_range"][0], arch["patience_range"][1])
            language_style = _pick_weighted(LANGUAGE_STYLES, lang_weights)
            quirk = random.choice(quirk_pool) if random.random() < 0.3 else None

            persona: dict[str, Any] = {
                "persona_id": f"{arch_id}_{persona_index:03d}",
                "archetype_id": arch_id,
                "archetype_label": arch["label"],
                "soul": arch["soul"],
                "response_style": arch["response_style"],
                "satisfaction_bias": arch["satisfaction_bias"],
                "age": age,
                "tech_level": tech_level,
                "patience": patience,
                "language_style": language_style,
                "quirk": quirk,
                "skills": arch.get("skills", []),
            }

            if demographics:
                if "regions" in demographics:
                    persona["region"] = _pick_demographic(demographics["regions"])["label"]
                if "usage_tenure" in demographics:
                    persona["tenure"] = _pick_demographic(demographics["usage_tenure"])["label"]
                if "plan_tier" in demographics:
                    persona["plan"] = _pick_demographic(demographics["plan_tier"])["label"]
                if "use_case" in demographics:
                    persona["use_case"] = _pick_demographic(demographics["use_case"])["label"]
                if "emotional_state" in demographics:
                    persona["emotional_state"] = _pick_demographic(demographics["emotional_state"])["label"]

            personas.append(persona)
            persona_index += 1

    random.shuffle(personas)
    return personas


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic customer personas from archetypes.")
    parser.add_argument("--count", type=int, default=10, help="Total number of personas to generate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    args = parser.parse_args()

    result = generate_personas(args.count, seed=args.seed)
    output = json.dumps(result, indent=2)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Generated {len(result)} personas → {args.output}")
    else:
        print(output)
