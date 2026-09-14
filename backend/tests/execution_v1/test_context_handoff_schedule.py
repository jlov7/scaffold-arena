from __future__ import annotations

import pytest

from execution_v1.context_handoff_schedule import apply_frozen_context_schedule
from protocol_v1.canonical import sha256


def units():
    return [{"scenario_id":"case", "harness_id":"harness", "endpoint_id":"endpoint", "provider_model":"qwen3.5:4b", "repetition_index":0, "treatment":{"context_policy":p}} for p in ("isolated", "full_inherited", "curated")]


def extension(cells):
    body={"version":"1","shuffle_algorithm":"predeclared-policy-interleaved-v1","randomization_seed":7,"cells":cells}
    return {**body,"schedule_digest":sha256(body)}


def cells(seeds=(9,9,9)):
    return [{"scenario_id":"case","context_policy":p,"repetition_index":0,"endpoint_id":"endpoint","provider_model":"qwen3.5:4b","declared_seed":seed,"ordinal":i} for i,(p,seed) in enumerate(zip(("isolated","full_inherited","curated"),seeds))]


def test_schedule_is_bijective_and_uses_matched_group_seed() -> None:
    scheduled=apply_frozen_context_schedule(units(), extension(cells()), randomization_seed=7)
    assert len(scheduled)==3 and len({row["seed"] for row in scheduled})==1


def test_schedule_rejects_unequal_group_seeds_extra_factors_and_digest_change() -> None:
    with pytest.raises(ValueError, match="share one declared seed"):
        apply_frozen_context_schedule(units(), extension(cells((9,10,9))), randomization_seed=7)
    invalid=units(); invalid[0]["treatment"]={"context_policy":"isolated","other":"x"}
    with pytest.raises(ValueError, match="co-varied"):
        apply_frozen_context_schedule(invalid, extension(cells()), randomization_seed=7)
    bad=extension(cells()); bad["cells"][0]["ordinal"]=2
    with pytest.raises(ValueError, match="digest"):
        apply_frozen_context_schedule(units(), bad, randomization_seed=7)
