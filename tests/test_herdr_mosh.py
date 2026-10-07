"""maintenance/herdr-mosh: the output filter that drops herdr's opaque background fill."""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
loader = importlib.machinery.SourceFileLoader("herdr_mosh", str(ROOT / "maintenance/herdr-mosh"))
spec = importlib.util.spec_from_loader("herdr_mosh", loader)
mosh = importlib.util.module_from_spec(spec)
loader.exec_module(mosh)

FILL = mosh.fill_colors("1e1e1e,232136")


def run(*chunks: bytes, fill=FILL) -> bytes:
    out, held = b"", b""
    for chunk in chunks:
        written, held = mosh.feed(held, chunk, fill)
        out += written
    return out + held


@pytest.mark.parametrize(
    "bg",
    [b"48;2;30;30;30", b"48;2;35;33;54", b"48:2:30:30:30", b"48:2::30:30:30", b"48:2:0:30:30:30"],
)
def test_fill_background_becomes_default(bg):
    assert run(b"\x1b[" + bg + b"m  x") == b"\x1b[49m  x"


@pytest.mark.parametrize(
    "seq",
    [
        b"\x1b[38;2;30;30;30m",  # fill RGB as a foreground
        b"\x1b[58;2;30;30;30m",  # as an underline color
        b"\x1b[38:2::30:30:30m",
        b"\x1b[48;5;234m",  # indexed background
        b"\x1b[48;2;33;32;46m",  # a truecolor background off the list
        b"\x1b[48;2;30;30m",  # a truncated group
        b"\x1b[48:2::30:30m",
    ],
)
def test_other_colors_stay_byte_identical(seq):
    assert run(seq + b"x") == seq + b"x"


def test_mixed_sgr_keeps_its_other_parameters_in_order():
    assert run(b"\x1b[0;1;38;2;224;222;244;48;2;35;33;54;4m") == b"\x1b[0;1;38;2;224;222;244;49;4m"


def test_group_values_are_never_read_as_a_background():
    # The B of a foreground and the N of an indexed color can be 48, followed
    # by `2` (dim) and the fill digits: no background in either sequence.
    for seq in (b"\x1b[38;2;1;1;48;2;30;30;30m", b"\x1b[38;5;48;2;30;30;30m"):
        assert run(seq) == seq


@pytest.mark.parametrize("cut", range(1, len(b"\x1b[48;2;30;30;30m")))
def test_a_sequence_split_across_two_reads(cut):
    seq = b"ab\x1b[48;2;30;30;30mcd"
    assert run(seq[: cut + 2], seq[cut + 2 :]) == b"ab\x1b[49mcd"


def test_non_sgr_sequences_pass_byte_identical():
    stream = (
        b"\x1b[?2026h\x1b[3;7H\x1b[2K\x1b]11;rgb:1e1e/1e1e/1e1e\x07\x1b]0;48;2;30;30;30\x1b\\"
        b"\x1b[>4;2m\x1b[48;2;30;30;30 q\x1bP+q544e\x1b\\\x1b7\x1b8\r\n48;2;30;30;30"
    )
    assert run(stream) == stream
    assert run(*(stream[i : i + 1] for i in range(len(stream)))) == stream


def test_empty_fill_changes_nothing():
    seq = b"\x1b[48;2;30;30;30m\x1b[48:2::35:33:54m"
    assert run(seq, fill=mosh.fill_colors("")) == seq


def test_fill_list_parses_hex_with_or_without_hash():
    assert mosh.fill_colors(" #1E1E1E , 232136,") == {(30, 30, 30), (35, 33, 54)}
