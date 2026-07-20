"""Strategy Maker — Commit 1: block library + rationale enforcement."""
import pytest

from maker.blocks import BLOCKS, CONDITION_SLOTS, SLOTS, Block, blocks_for_slot, get_block


def test_every_block_has_a_rationale():
    for name, b in BLOCKS.items():
        assert b.rationale and b.rationale.strip(), f"{name} missing rationale"


def test_empty_rationale_is_rejected():
    with pytest.raises(ValueError):
        Block("setup", "x", {"p": [1]}, "")
    with pytest.raises(ValueError):
        Block("setup", "x", {"p": [1]}, "   ")


def test_unknown_slot_is_rejected():
    with pytest.raises(ValueError):
        Block("bogus", "x", {"p": [1]}, "a story")


def test_empty_param_grid_is_rejected():
    with pytest.raises(ValueError):
        Block("setup", "x", {}, "a story")


def test_all_six_slots_are_populated():
    for slot in SLOTS:
        assert blocks_for_slot(slot), f"no blocks for slot {slot}"


def test_condition_slots_are_the_budgeted_three():
    assert set(CONDITION_SLOTS) == {"regime", "setup", "trigger"}


def test_library_shape_and_lookup():
    assert len(BLOCKS) >= 20
    assert get_block("nday_extreme").slot == "setup"
    assert get_block("atr_trail").slot == "exit"
    assert set(SLOTS) == {"universe", "regime", "setup", "trigger", "exit", "hold"}


def test_blocks_are_frozen_immutable():
    b = get_block("nday_extreme")
    with pytest.raises(Exception):
        b.name = "changed"  # frozen dataclass
