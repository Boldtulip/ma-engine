"""Heir absence: is there a likely successor inside the company?

In Chinese family companies, a successor almost always appears in the
public records before taking over: as a shareholder, a director, or a
supervisor, and almost always sharing the founder's surname. If no
younger person with the founder's surname holds any position or
shares, the company has no visible successor.

This is a heuristic. A daughter-in-law running the company or a
successor with the mother's surname will be missed. The reason string
says exactly what was checked so a person can verify it.
"""

from __future__ import annotations

from ma_engine.adapters.base import Company
from ma_engine.signals import Signal, signal
from ma_engine.signals.age import estimate_age, split_name


@signal("heir_absence")
def heir_absence_signal(company: Company, params: dict | None = None) -> Signal:
    params = params or {}
    gap = int(params.get("generation_gap_years", 18))

    owner = company.controller()
    if owner is None:
        return Signal("heir_absence", 0.0, 0.0, "No individual owner found in the records.")

    surname, _ = split_name(owner.name)
    others = [
        p
        for p in company.shareholders + company.executives
        if not p.is_company and p.name != owner.name
    ]
    same_surname = [p for p in others if split_name(p.name)[0] == surname]

    if not others:
        return Signal(
            "heir_absence", 1.0, 0.7,
            f"{owner.name} is the only person in the shareholder and executive records.",
        )

    if not same_surname:
        return Signal(
            "heir_absence", 0.9, 0.6,
            f"None of the {len(others)} other people on record share "
            f"the owner's surname {surname}.",
        )

    # Someone shares the surname. Check whether they look like a younger
    # generation (disclosed or name-estimated age gap of `gap` years or more).
    owner_age = owner.age or estimate_age(owner.name)[0]
    for p in same_surname:
        p_age = p.age or estimate_age(p.name)[0]
        if owner_age and p_age and owner_age - p_age >= gap:
            return Signal(
                "heir_absence", 0.1, 0.6,
                f"{p.name} ({p.role or 'on record'}) shares surname {surname} and is "
                f"roughly a generation younger, so a likely successor.",
            )

    names = ", ".join(p.name for p in same_surname[:3])
    return Signal(
        "heir_absence", 0.4, 0.4,
        f"{names} share(s) the owner's surname but none is clearly a younger "
        f"generation; the successor picture is unclear.",
    )
