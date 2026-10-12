"""Seeded synthetic member/claims fixtures for the eval harness.

Builds a fixture data dir shaped exactly like app/data/ (members.json,
claims.json, plans.json, providers.json, frames.json) so the app's tools can
be pointed at it via VSP_DATA_DIR without any code changes.

The six hand-written demo members (M001-M006) are carried over unchanged,
then N synthetic members (SYN-001...) are added. Synthetic members are not
random noise: plan, coverage, dependents, allowance usage, claim status and
individual-plan billing are cycled so every combination the agents branch on
shows up, and plan amounts always come from plans.json so expected answers
stay consistent with what the tools will return.

    python -m evals.generators.synthetic_data --count 24 --seed 7
"""

import argparse
import itertools
import json
import random
import shutil
from pathlib import Path

from evals.paths import APP_DATA_DIR, FIXTURES_DIR

PLAN_NAMES = ["Signature", "Choice", "Advantage", "Enhanced Advantage"]

# Fictional names only -- never seed fixtures with real people's data.
FIRST_NAMES = [
    "Avery", "Jordan", "Morgan", "Riley", "Casey", "Quinn", "Rowan", "Elena",
    "Marcus", "Hana", "Tobias", "Ines", "Kofi", "Leila", "Mateo", "Noor",
    "Oscar", "Priyanka", "Soren", "Talia", "Umar", "Vera", "Wen", "Yusuf",
]
LAST_NAMES = [
    "Albright", "Benedetti", "Castellano", "Dunmore", "Eskildsen", "Farrow",
    "Galloway", "Hartigan", "Iwasaki", "Jablonski", "Kessler", "Lindqvist",
    "Moreau", "Nakamura", "Okafor", "Pemberton", "Quintero", "Rasmussen",
]
CHILD_NAMES = ["Milo", "Ada", "Felix", "Iris", "Leo", "Nora", "Theo", "Zara"]
EMPLOYERS = ["Acme Corp", "Beacon Health Systems", "Northlake Manufacturing", "Meridian Bank", "Lakeview Schools"]
OON_PROVIDER = "Out-of-network provider"

# (coverage_type, number of dependents)
COVERAGE_SHAPES = [("Member Only", 0), ("Member + Spouse", 1), ("Family", 2), ("Family", 3), ("Member + Child", 1)]
CLAIM_SHAPES = ["none", "processed", "pending", "oon"]


def _load(name: str):
    with open(APP_DATA_DIR / name) as f:
        return json.load(f)


def _member_number(index: int, rng: random.Random) -> str:
    return f"VSP-9{index:03d}-{rng.randint(1000, 9999)}"


def _iso(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


def build_members(count: int, seed: int) -> tuple[dict, list]:
    rng = random.Random(seed)
    plans = _load("plans.json")
    providers = _load("providers.json")

    # Cartesian product of the dimensions the agents actually branch on,
    # shuffled once, then cycled -- so even a small `count` gets broad
    # coverage rather than N variations of the same profile.
    combos = list(itertools.product(PLAN_NAMES, COVERAGE_SHAPES, CLAIM_SHAPES, [False, True]))
    rng.shuffle(combos)

    used_names: set[str] = set()
    members: dict = {}
    claims: list = []

    for i in range(count):
        plan_name, (coverage, n_deps), claim_shape, contacts_used = combos[i % len(combos)]
        plan = plans[plan_name]

        while True:
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            if f"{first} {last}" not in used_names:
                break
        name = f"{first} {last}"
        used_names.add(name)

        member_id = f"SYN-{i + 1:03d}"
        number = _member_number(i + 1, rng)
        # Every 5th member is a self-purchased individual plan, so billing
        # has both the "has billing" and "employer-sponsored" branches.
        individual = i % 5 == 4
        last_exam = rng.choice([None, _iso(2024, rng.randint(1, 12), rng.randint(1, 28)), _iso(2026, rng.randint(1, 8), rng.randint(1, 28))])

        member = {
            "member_id": member_id,
            "vsp_member_number": number,
            "name": name,
            "age": rng.randint(22, 70),
            "zip": "60601",  # the provider directory is Chicago-only
            "plan": plan_name,
            "employer": "Self-purchased" if individual else rng.choice(EMPLOYERS),
            "coverage_type": coverage,
            "effective_date": rng.choice(["2026-01-01", "2026-03-01", "2026-07-01"]),
            "copays": {"exam": plan["exam_copay"], "materials": 25},
            "frame_allowance": plan["frame_allowance"],
            "featured_frame_bonus": plan["featured_frame_bonus"],
            "contact_allowance": plan["contact_allowance"],
            "last_exam": {"self": last_exam},
            "frame_allowance_used": {"self": False},
        }
        if contacts_used:
            member["contact_allowance_used"] = {"self": True, "used_on": "2026-02-10"}
            member["frame_allowance_used"]["eligible_this_year"] = False
        if individual:
            member["individual_plan"] = True
            member["billing"] = {
                "premium": round(rng.uniform(14, 40), 2),
                "autopay_day": rng.choice([1, 5, 15, 20, 28]),
                "last_payment": "2026-09-15",
                "last_payment_status": rng.choice(["successful", "successful", "failed"]),
            }

        deps = []
        for d in range(n_deps):
            is_spouse = coverage == "Member + Spouse" or (coverage == "Family" and d == 0 and n_deps == 3)
            if is_spouse:
                # A spouse must not share a full name with any primary member,
                # or the leakage scorer can't tell them apart.
                dep_first = rng.choice([n for n in FIRST_NAMES if n != first and f"{n} {last}" not in used_names])
                used_names.add(f"{dep_first} {last}")
            else:
                dep_first = CHILD_NAMES[(i + d) % len(CHILD_NAMES)]
            deps.append({
                "name": f"{dep_first} {last}",
                "age": rng.randint(30, 65) if is_spouse else rng.randint(3, 17),
                "vsp_member_number": f"{number}-{d + 1:02d}",
                "last_exam": _iso(2025, rng.randint(1, 12), rng.randint(1, 28)),
                "frame_allowance_used": rng.random() < 0.3,
            })
        if deps:
            member["dependents"] = deps

        members[member_id] = member

        in_net = [p for p in providers if plan_name in p["in_network_plans"]]
        if claim_shape == "processed":
            claims.append({
                "member_id": member_id, "date": "2026-02-14", "provider": rng.choice(in_net)["name"],
                "service": "WellVision Exam", "plan_paid": 95, "member_paid": plan["exam_copay"],
                "status": "Processed",
            })
        elif claim_shape == "pending":
            claims.append({
                "member_id": member_id, "date": "2026-08-20", "provider": rng.choice(in_net)["name"],
                "service": "WellVision Exam + frames", "plan_paid": 95 + plan["frame_allowance"],
                "member_paid": plan["exam_copay"], "status": "Pending",
            })
        elif claim_shape == "oon":
            claims.append({
                "member_id": member_id, "date": "2026-06-02", "provider": OON_PROVIDER,
                "service": "WellVision Exam", "plan_paid": plan["oon_exam_reimbursement"],
                "member_paid": 160, "status": "Processed (OON reimbursement)",
            })

    return members, claims


def write_fixtures(out_dir: Path, count: int, seed: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    synthetic_members, synthetic_claims = build_members(count, seed)

    members = {**_load("members.json"), **synthetic_members}
    claims = _load("claims.json") + synthetic_claims

    (out_dir / "members.json").write_text(json.dumps(members, indent=2) + "\n")
    (out_dir / "claims.json").write_text(json.dumps(claims, indent=2) + "\n")
    for name in ("plans.json", "providers.json", "frames.json"):
        shutil.copyfile(APP_DATA_DIR / name, out_dir / name)
    (out_dir / "MANIFEST.json").write_text(json.dumps({"seed": seed, "synthetic_count": count}, indent=2) + "\n")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=FIXTURES_DIR)
    args = parser.parse_args()
    out = write_fixtures(args.out, args.count, args.seed)
    print(f"Wrote fixtures for 6 demo + {args.count} synthetic members to {out}")


if __name__ == "__main__":
    main()
