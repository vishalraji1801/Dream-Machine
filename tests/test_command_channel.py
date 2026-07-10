"""CommandChannel — the file-backed control queue between API and bot."""
import pytest

from src.command_channel import CommandChannel


@pytest.fixture
def chan(tmp_path):
    return CommandChannel(path=str(tmp_path / "commands.jsonl"))


def test_send_then_poll_returns_command(chan):
    chan.send("pause")
    got = chan.poll()
    assert len(got) == 1
    assert got[0]["cmd"] == "pause"
    assert "ts" in got[0]


def test_poll_is_incremental(chan):
    chan.send("pause")
    assert [c["cmd"] for c in chan.poll()] == ["pause"]
    assert chan.poll() == []                      # nothing new
    chan.send("resume")
    assert [c["cmd"] for c in chan.poll()] == ["resume"]


def test_order_is_preserved_and_lossless(chan):
    for c in ("pause", "resume", "square_off", "stop"):
        chan.send(c)
    assert [c["cmd"] for c in chan.poll()] == ["pause", "resume", "square_off", "stop"]


def test_seek_to_end_skips_stale_commands(chan):
    chan.send("stop")            # queued before "startup"
    chan.seek_to_end()
    assert chan.poll() == []     # stale command ignored
    chan.send("pause")
    assert [c["cmd"] for c in chan.poll()] == ["pause"]


def test_unknown_command_rejected(chan):
    with pytest.raises(ValueError):
        chan.send("selfdestruct")


def test_poll_missing_file_is_empty(tmp_path):
    assert CommandChannel(path=str(tmp_path / "none.jsonl")).poll() == []


def test_payload_round_trips(chan):
    chan.send("square_off", source="panic")
    got = chan.poll()[0]
    assert got["cmd"] == "square_off"
    assert got["source"] == "panic"
