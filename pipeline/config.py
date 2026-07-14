"""Static configuration for the SOW26 Kisatori pipeline.

Race UUIDs are trackmaxx's internal per-stage identifiers (distinct from the
public "sow26-N" slug). They were captured from the list.ashx network request
the results page issues. Category UUID maps live in cats_stage{N}.json (one map
name->uuid per stage, because trackmaxx re-issues category UUIDs each stage).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

STAGE_RACE_UUID = {
    1: "7d432d49-894e-4dba-a9a3-26c7f716e808",
    2: "84dcd3ee-8954-4b3d-bc7c-897d02ba6fee",
    3: "b221510d-1c88-48da-9ef0-a29ec6f1051d",
}

TRACKMAXX_LIST = "https://trackmaxx.ch/list/list.ashx"


def stage_categories(stage):
    with open(os.path.join(HERE, f"cats_stage{stage}.json")) as f:
        return json.load(f)


def load_members():
    with open(os.path.join(DATA, "members.json")) as f:
        return json.load(f)
