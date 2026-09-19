# Badminton Scorekeeper — Tiny Tapeout

A one-tile ASIC implementing BWF rally scoring for badminton: deuce, the 29-all cap,
serve tracking, best-of-three match structure, and single-level undo/redo.

Built for the DLSU Badminton Society.

- Design details and pinout: [`docs/info.md`](docs/info.md)
- RTL: [`src/project.v`](src/project.v)
- Testbench: [`test/`](test/)

## Status

| | |
|---|---|
| Top module | `tt_um_badminton_scorekeeper` |
| Tiles | 1x1 |
| Nominal clock | 10 kHz |
| Yosys generic cell count | 648 cells, 56 flip-flops |
| Tests | 12 cocotb tests, all passing |

## Which template to start from

This is a **Verilog** project, not a Wokwi one. Start from
`https://github.com/TinyTapeout/ttihp-verilog-template` (or the SKY equivalent if you
target a Sky130 shuttle), then copy in the files from this repo:

```
info.yaml          -> replace
src/project.v      -> replace
docs/info.md       -> replace
test/tb.v          -> replace
test/test.py       -> replace
test/requirements.txt -> replace
test/Makefile      -> keep the template's, unless you need the RTL-only version here
```

Do **not** overwrite `.github/`, `LICENSE`, or `.gitignore` from the template. The
GitHub Actions workflows in `.github/` are what build your GDS.

## Running the tests

```bash
cd test
pip install -r requirements.txt
sudo apt-get install -y iverilog
make
```

Expect `TESTS=12 PASS=12 FAIL=0`. A waveform is written to `test/tb.vcd`.

## Build and submit

1. Push to GitHub, then Settings → Pages → Source → **GitHub Actions**.
2. Actions → **gds** → Run workflow. Wait for green checks.
3. Read the **Utilisation %** in the gds summary. If it is above roughly 90%,
   change `tiles: "1x1"` to `"1x2"` in `info.yaml` and re-run.
4. tinytapeout.com → Submit your design → sign in with GitHub → point it at this repo.
5. Press **Submit a new revision** after every change. Only the latest revision goes
   to the shuttle, and nothing is accepted after the closing date.

## Bench setup

| Signal | Pins | Hardware |
|---|---|---|
| Buttons | `ui[3:0]` | 4 momentary switches, 10 kΩ pull-downs |
| Target select | `ui[5:4]` | 2-position DIP switch |
| Segments | `uo[6:0]` | 4-digit common-cathode display, 330 Ω per segment |
| Decimal point | `uo[7]` | same display |
| Digit enable | `uio[3:0]` | digit drivers, one-hot, active high |
| Indicators | `uio[7:4]` | 4 LEDs, 330 Ω each |

The demo board's onboard single 7-segment digit will show the multiplexed pattern but
not a readable score, so the external 4-digit display is required.

## License

Apache-2.0, matching the Tiny Tapeout templates.
