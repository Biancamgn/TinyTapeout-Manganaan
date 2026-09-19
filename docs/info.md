<!---
This file is used to generate your project datasheet. Please fill in the information
below and delete any unused sections.
-->

## How it works

A hardware scorekeeper implementing the BWF rally-scoring rules for badminton. Two buttons award a point to each side; the chip handles the serve, the deuce, the cap and the best-of-three match structure, and drives a four-digit multiplexed 7-segment display.

### Retained state

The entire machine is 17 flip-flops:

| Field | Width | Meaning |
|---|---|---|
| `score_a`, `score_b` | 5 each | 0 to 30 |
| `games_a`, `games_b` | 2 each | games won, best of 3 |
| `server` | 1 | 0 = side A, 1 = side B |
| `state` | 2 | PLAY / GAME_END / MATCH_END |

Everything else, including service court, game point, match point and the interval at 11, is recomputed combinationally rather than stored.

### The win condition

The three apparent rules (win at 21; at 20-all win by two; at 29-all the next point wins) collapse to one expression, evaluated on the incremented score:

```
win = (s_w >= T && s_w >= s_l + 2) || (s_w == C)
```

with `T` the target and `C = T + 9` the cap. For the standard format `T = 21`, `C = 30`. Check the boundaries: 21-15 wins on the first term; 21-20 satisfies neither and correctly does not end the game; 22-20 wins on the lead; 30-29 wins on the cap.

Because the evaluator is fed `s + 1`, the same block yields the game-point indicator for free: a side is at game point exactly when the evaluator says its next point would win.

### The serve

Under rally scoring, the side that wins a rally always serves next, regardless of who was serving. This reduces to a single unconditional assignment, `server <= scorer`. The service court is the LSB of the server's own score: right court when even, left when odd.

### Undo

There is no RAM on a tile, so undo is a single-level shadow copy of the 17-bit state vector. Undo *swaps* current and shadow rather than overwriting, which makes the same button act as undo and redo alternately. Deeper history would need a stack and is out of scope.

### Clock

The design is intended to run at 10 kHz. Running slow is deliberate: the debounce lockout and the display refresh divider are counters, and every prescaler bit is silicon. At 10 kHz the debounce lockout is 8 bits (about 25 ms) and the display refreshes at 2.5 kHz.

### Display

`uo[6:0]` carries the shared segment pattern, `uio[3:0]` is a one-hot digit enable. Digit order is A-tens, A-units, B-tens, B-units. Leading zeros on the tens digits are blanked. The decimal point on a tens digit indicates that side has won a game.

### Rule variants

`ui[5:4]` selects the target score: `00` = 21 (standard), `01` = 15, `10` = 11, `11` = 5 (short, for bench testing). The cap tracks as `T + 9`.

## How to test

Hold `rst_n` low, release, and the display should read 0 and 0 with `SERVE_A` asserted.

1. Press `BTN_POINT_A`. Side A goes to 1 and `SERVE_A` stays lit.
2. Press `BTN_POINT_B`. Side B goes to 1 and the serve indicator moves to `SERVE_B`.
3. Press `BTN_UNDO`. The display returns to 1-0 and the serve returns to A. Press it again to redo.
4. Set `ui[5:4]` to `11` for the 5-point format and run a quick game to see `GAME_POINT` light at 4, then a game end.
5. At a game end, point buttons are ignored until `BTN_NEXT` is pressed, which zeroes the scores and leaves the serve with the side that won the game.
6. After a side wins two games, `MATCH_OVER` asserts and only `BTN_NEXT` clears it.

The deuce behaviour is the thing worth checking on silicon: reach 20-20, then confirm 21-20 does **not** end the game and 22-20 does.

The cocotb testbench in `test/` covers all of this plus a randomised comparison against a Python golden model.

## External hardware

- 4-digit common-cathode 7-segment display, segments on `uo[6:0]`, digit drivers on `uio[3:0]`
- 4 momentary pushbuttons with pull-downs on `ui[3:0]`
- 4 LEDs with series resistors on `uio[7:4]`
- 2-position DIP switch on `ui[5:4]`

The demo board's onboard single 7-segment digit will show the multiplexed pattern but not a readable score, so the external display is required for real use.
