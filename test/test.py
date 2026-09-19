# SPDX-FileCopyrightText: (c) 2026 Bianca Manganaan
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

# ----------------------------------------------------------------------
# Constants mirroring the RTL
# ----------------------------------------------------------------------

BTN_A, BTN_B, BTN_UNDO, BTN_NEXT = 0, 1, 2, 3

# must exceed the 8-bit debounce lockout in the RTL
SETTLE = 300

# reverse of the seg7 function, bit order {g,f,e,d,c,b,a}
SEG_DECODE = {
    0b0111111: 0,
    0b0000110: 1,
    0b1011011: 2,
    0b1001111: 3,
    0b1100110: 4,
    0b1101101: 5,
    0b1111101: 6,
    0b0000111: 7,
    0b1111111: 8,
    0b1101111: 9,
    0b0000000: None,  # blanked
}

TARGET_21, TARGET_15, TARGET_11, TARGET_5 = 0, 1, 2, 3


# ----------------------------------------------------------------------
# Golden model
# ----------------------------------------------------------------------

class Model:
    """Reference implementation of the same rules, in plain Python."""

    PLAY, GAME_END, MATCH_END = 0, 1, 2

    def __init__(self, target=21):
        self.target = target
        self.cap = target + 9
        self.reset()

    def reset(self):
        self.a = 0
        self.b = 0
        self.games_a = 0
        self.games_b = 0
        self.server = 0
        self.state = self.PLAY

    def point(self, side):
        if self.state != self.PLAY:
            return
        if side == 0:
            self.a += 1
        else:
            self.b += 1
        self.server = side

        won, lost = (self.a, self.b) if side == 0 else (self.b, self.a)
        if (won >= self.target and won >= lost + 2) or won == self.cap:
            if side == 0:
                self.games_a += 1
                total = self.games_a
            else:
                self.games_b += 1
                total = self.games_b
            self.state = self.MATCH_END if total == 2 else self.GAME_END

    def next_button(self):
        if self.state == self.GAME_END:
            self.a = 0
            self.b = 0
            self.state = self.PLAY
        elif self.state == self.MATCH_END:
            self.reset()

    def scores(self):
        return (self.a, self.b)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

async def start(dut, target_sel=TARGET_21):
    """Bring up the clock and release reset."""
    clock = Clock(dut.clk, 100, units="us")  # 10 kHz
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = target_sel << 4
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)


async def press(dut, bit, target_sel=TARGET_21):
    """Press and release a button, then wait out the debounce lockout."""
    base = target_sel << 4
    dut.ui_in.value = base | (1 << bit)
    await ClockCycles(dut.clk, 4)
    dut.ui_in.value = base
    await ClockCycles(dut.clk, SETTLE)


async def read_scores(dut):
    """Sample the multiplexed display for a full refresh cycle."""
    digits = {}
    for _ in range(12):
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")
        sel = int(dut.uio_out.value) & 0xF
        if sel != 0 and (sel & (sel - 1)) == 0:  # exactly one bit set
            idx = sel.bit_length() - 1
            pattern = int(dut.uo_out.value) & 0x7F
            digits[idx] = SEG_DECODE.get(pattern, "?")

    assert set(digits.keys()) == {0, 1, 2, 3}, f"missing digits: {digits}"
    for k, v in digits.items():
        assert v != "?", f"digit {k} showed an undecodable pattern"

    a = (digits[0] or 0) * 10 + (digits[1] or 0)
    b = (digits[2] or 0) * 10 + (digits[3] or 0)
    return a, b


def serve_side(dut):
    """Return 0 for A, 1 for B, or None if neither indicator is lit."""
    uio = int(dut.uio_out.value)
    if uio & (1 << 4):
        return 0
    if uio & (1 << 5):
        return 1
    return None


def match_over(dut):
    return bool(int(dut.uio_out.value) & (1 << 7))


def game_point(dut):
    return bool(int(dut.uio_out.value) & (1 << 6))


async def rally_to(dut, a_points, b_points, target_sel=TARGET_21):
    """Alternate points so neither side ever gets a 2-point lead early."""
    a = b = 0
    while a < a_points or b < b_points:
        if a < a_points:
            await press(dut, BTN_A, target_sel)
            a += 1
        if b < b_points:
            await press(dut, BTN_B, target_sel)
            b += 1


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

@cocotb.test()
async def test_reset(dut):
    """After reset the board reads 0-0 and side A serves."""
    await start(dut)
    a, b = await read_scores(dut)
    assert (a, b) == (0, 0), f"expected 0-0, got {a}-{b}"
    assert serve_side(dut) == 0
    assert not match_over(dut)


@cocotb.test()
async def test_basic_scoring(dut):
    """Points land on the right side and the display tracks them."""
    await start(dut)
    for _ in range(3):
        await press(dut, BTN_A)
    for _ in range(2):
        await press(dut, BTN_B)
    a, b = await read_scores(dut)
    assert (a, b) == (3, 2), f"expected 3-2, got {a}-{b}"


@cocotb.test()
async def test_serve_follows_rally_winner(dut):
    """Whoever wins the rally serves next, regardless of who served."""
    await start(dut)
    await press(dut, BTN_A)
    assert serve_side(dut) == 0
    await press(dut, BTN_A)
    assert serve_side(dut) == 0, "server should not change on a hold"
    await press(dut, BTN_B)
    assert serve_side(dut) == 1, "service should transfer on a side-out"


@cocotb.test()
async def test_two_digit_display(dut):
    """Scores above 9 render across both digits with the tens blanked at 0."""
    await start(dut)
    await rally_to(dut, 12, 10)
    a, b = await read_scores(dut)
    assert (a, b) == (12, 10), f"expected 12-10, got {a}-{b}"


@cocotb.test()
async def test_plain_win_at_21(dut):
    """21-15 ends the game."""
    await start(dut)
    await rally_to(dut, 15, 15)
    for _ in range(6):
        await press(dut, BTN_A)
    a, b = await read_scores(dut)
    assert (a, b) == (21, 15), f"expected 21-15, got {a}-{b}"

    # game has ended: further points are ignored
    await press(dut, BTN_A)
    a, b = await read_scores(dut)
    assert (a, b) == (21, 15), "points registered after the game ended"


@cocotb.test()
async def test_deuce_requires_two_point_lead(dut):
    """At 20-all, 21-20 must NOT end the game but 22-20 must."""
    await start(dut)
    await rally_to(dut, 20, 20)
    a, b = await read_scores(dut)
    assert (a, b) == (20, 20), f"expected 20-20, got {a}-{b}"

    await press(dut, BTN_A)  # 21-20
    a, b = await read_scores(dut)
    assert (a, b) == (21, 20)

    # if the game had wrongly ended, this point would be swallowed
    await press(dut, BTN_B)
    a, b = await read_scores(dut)
    assert (a, b) == (21, 21), "21-20 incorrectly ended the game"

    await press(dut, BTN_A)  # 22-21, still no two-point lead
    await press(dut, BTN_A)  # 23-21, wins
    a, b = await read_scores(dut)
    assert (a, b) == (23, 21)
    await press(dut, BTN_A)
    a, b = await read_scores(dut)
    assert (a, b) == (23, 21), "two-point lead did not end the game"


@cocotb.test()
async def test_cap_at_30(dut):
    """At 29-all the next point wins even without a two-point lead."""
    await start(dut)
    await rally_to(dut, 29, 29)
    a, b = await read_scores(dut)
    assert (a, b) == (29, 29), f"expected 29-29, got {a}-{b}"

    assert game_point(dut), "both sides should be at game point at 29-all"

    await press(dut, BTN_B)  # 29-30, wins on the cap
    a, b = await read_scores(dut)
    assert (a, b) == (29, 30)
    await press(dut, BTN_A)
    a, b = await read_scores(dut)
    assert (a, b) == (29, 30), "the cap did not end the game"


@cocotb.test()
async def test_game_point_indicator(dut):
    """GAME_POINT asserts exactly when one more point would win."""
    await start(dut)
    await rally_to(dut, 19, 15)
    assert not game_point(dut), "19-15 is not game point"
    await press(dut, BTN_A)  # 20-15
    assert game_point(dut), "20-15 is game point"


@cocotb.test()
async def test_next_game_and_serve_carry(dut):
    """NEXT zeroes the scores and leaves the serve with the game winner."""
    await start(dut, TARGET_5)
    for _ in range(5):
        await press(dut, BTN_B, TARGET_5)
    a, b = await read_scores(dut)
    assert (a, b) == (0, 5)

    await press(dut, BTN_NEXT, TARGET_5)
    a, b = await read_scores(dut)
    assert (a, b) == (0, 0), "NEXT did not reset the scores"
    assert serve_side(dut) == 1, "the game winner should serve first"


@cocotb.test()
async def test_match_over_after_two_games(dut):
    """Best of three: two games ends the match."""
    await start(dut, TARGET_5)
    for _ in range(5):
        await press(dut, BTN_A, TARGET_5)
    await press(dut, BTN_NEXT, TARGET_5)
    for _ in range(5):
        await press(dut, BTN_A, TARGET_5)

    assert match_over(dut), "MATCH_OVER should assert after two games"

    await press(dut, BTN_A, TARGET_5)
    a, b = await read_scores(dut)
    assert (a, b) == (5, 0), "points registered after the match ended"

    await press(dut, BTN_NEXT, TARGET_5)
    a, b = await read_scores(dut)
    assert (a, b) == (0, 0)
    assert not match_over(dut)


@cocotb.test()
async def test_undo_and_redo(dut):
    """Undo restores the previous state; pressing it again redoes."""
    await start(dut)
    await press(dut, BTN_A)
    await press(dut, BTN_A)
    await press(dut, BTN_B)
    a, b = await read_scores(dut)
    assert (a, b) == (2, 1)
    assert serve_side(dut) == 1

    await press(dut, BTN_UNDO)
    a, b = await read_scores(dut)
    assert (a, b) == (2, 0), "undo did not roll back the score"
    assert serve_side(dut) == 0, "undo did not roll back the serve"

    await press(dut, BTN_UNDO)
    a, b = await read_scores(dut)
    assert (a, b) == (2, 1), "second undo should redo"
    assert serve_side(dut) == 1


@cocotb.test()
async def test_random_against_model(dut):
    """Randomised rallies compared against the Python golden model."""
    random.seed(1234)
    await start(dut, TARGET_11)
    model = Model(target=11)

    for i in range(400):
        if model.state == Model.PLAY:
            side = random.randint(0, 1)
            await press(dut, BTN_A if side == 0 else BTN_B, TARGET_11)
            model.point(side)
        else:
            await press(dut, BTN_NEXT, TARGET_11)
            model.next_button()

        a, b = await read_scores(dut)
        assert (a, b) == model.scores(), (
            f"step {i}: DUT {a}-{b}, model {model.scores()}"
        )
        assert match_over(dut) == (model.state == Model.MATCH_END), (
            f"step {i}: MATCH_OVER mismatch"
        )

    dut._log.info("400 randomised rallies matched the golden model")
