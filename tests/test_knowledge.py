"""The knowledge base is meant to be edited by hand, so it gets its
own tests. A stray colon inside an unquoted sentence is enough to
break every YAML file, and that must fail here rather than at runtime.
"""

import yaml

from succession_radar.matching.matcher import KNOWLEDGE_DIR, load_knowledge

EXPECTED_FILES = {
    "buyers_china",
    "deal_structures",
    "fit_criteria",
    "origination_playbook",
    "valuation_heuristics",
}


def test_every_knowledge_file_parses():
    for path in KNOWLEDGE_DIR.glob("*.yaml"):
        with open(path, encoding="utf-8") as f:
            assert yaml.safe_load(f) is not None, f"{path.name} is empty"


def test_expected_files_present():
    assert EXPECTED_FILES <= set(load_knowledge())


def test_buyers_have_required_fields():
    for buyer in load_knowledge()["buyers_china"]["buyers"]:
        for field in ("key", "name_cn", "name_en", "motive", "prefers"):
            assert field in buyer, f"{buyer.get('key')} is missing {field}"
