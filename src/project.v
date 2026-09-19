/*
 * Badminton Scorekeeper ASIC
 * BWF rally scoring with deuce, cap, serve tracking and single-level undo/redo.
 *
 * Copyright (c) 2026 Bianca Manganaan
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_badminton_scorekeeper (
    input  wire [7:0] ui_in,    // dedicated inputs
    output wire [7:0] uo_out,   // dedicated outputs
    input  wire [7:0] uio_in,   // bidirectional, input path (unused)
    output wire [7:0] uio_out,  // bidirectional, output path
    output wire [7:0] uio_oe,   // bidirectional, enable (1 = drive out)
    input  wire       ena,      // always 1 when selected
    input  wire       clk,      // nominal 10 kHz
    input  wire       rst_n     // active low reset
);

  // ------------------------------------------------------------------
  // Parameters
  // ------------------------------------------------------------------
  localparam DEB_BITS = 8;      // 256 clocks ~= 25 ms lockout at 10 kHz

  localparam ST_PLAY  = 2'd0;
  localparam ST_GAME  = 2'd1;   // a game just ended, waiting for NEXT
  localparam ST_MATCH = 2'd2;   // match over, waiting for NEXT

  // ------------------------------------------------------------------
  // Retained state (17 bits total). Everything else is recomputed.
  // ------------------------------------------------------------------
  reg [16:0] cur, shadow;

  wire [4:0] score_a = cur[4:0];
  wire [4:0] score_b = cur[9:5];
  wire       server  = cur[10];     // 0 = side A serves, 1 = side B
  wire [1:0] games_a = cur[12:11];
  wire [1:0] games_b = cur[14:13];
  wire [1:0] state   = cur[16:15];

  // ------------------------------------------------------------------
  // Rules configuration: target from ui_in[5:4], cap = target + 9
  // ------------------------------------------------------------------
  reg [4:0] target;
  always @(*) begin
    case (ui_in[5:4])
      2'b00:   target = 5'd21;  // BWF standard
      2'b01:   target = 5'd15;
      2'b10:   target = 5'd11;
      default: target = 5'd5;   // short test format
    endcase
  end

  wire [5:0] tgt = {1'b0, target};
  wire [5:0] cap = tgt + 6'd9;

  // ------------------------------------------------------------------
  // Win evaluators. Fed with the INCREMENTED score, so the same block
  // gives both "this point wins the game" and "this side is at game point".
  //
  //   win = (s_w >= T  AND  s_w >= s_l + 2)  OR  s_w == C
  //
  // s_w >= s_l + 2 is used instead of s_w - s_l >= 2 to avoid unsigned
  // underflow when the scorer is behind.
  // ------------------------------------------------------------------
  wire [5:0] sa   = {1'b0, score_a};
  wire [5:0] sb   = {1'b0, score_b};
  wire [5:0] sa_n = sa + 6'd1;
  wire [5:0] sb_n = sb + 6'd1;

  wire win_a = ((sa_n >= tgt) && (sa_n >= sb + 6'd2)) || (sa_n == cap);
  wire win_b = ((sb_n >= tgt) && (sb_n >= sa + 6'd2)) || (sb_n == cap);

  // ------------------------------------------------------------------
  // Button front end: 2-flop synchroniser, rising-edge detect,
  // shared lockout counter for debounce.
  // ------------------------------------------------------------------
  reg [3:0] sync0, sync1, sync2;
  reg [DEB_BITS-1:0] lockout;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sync0 <= 4'd0;
      sync1 <= 4'd0;
      sync2 <= 4'd0;
    end else begin
      sync0 <= ui_in[3:0];
      sync1 <= sync0;
      sync2 <= sync1;
    end
  end

  wire [3:0] rise = sync1 & ~sync2;
  wire       busy = |lockout;
  wire [3:0] ev   = busy ? 4'd0 : rise;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)      lockout <= {DEB_BITS{1'b0}};
    else if (|ev)    lockout <= {DEB_BITS{1'b1}};
    else if (busy)   lockout <= lockout - 1'b1;
  end

  // priority: point A > point B > undo > next
  wire ev_a    = ev[0];
  wire ev_b    = ev[1] & ~ev[0];
  wire ev_undo = ev[2] & ~(|ev[1:0]);
  wire ev_next = ev[3] & ~(|ev[2:0]);

  // ------------------------------------------------------------------
  // Next-state logic
  // ------------------------------------------------------------------
  wire       won       = ev_a ? win_a  : win_b;
  wire [1:0] cur_games = ev_a ? games_a : games_b;

  reg [16:0] nxt;
  always @(*) begin
    nxt = cur;
    case (state)
      ST_PLAY: begin
        if (ev_a || ev_b) begin
          if (ev_a) nxt[4:0] = sa_n[4:0];
          else      nxt[9:5] = sb_n[4:0];

          // Rally scoring: the side that wins the rally always serves next.
          nxt[10] = ev_b;

          if (won) begin
            if (ev_a) nxt[12:11] = games_a + 2'd1;
            else      nxt[14:13] = games_b + 2'd1;
            nxt[16:15] = (cur_games == 2'd1) ? ST_MATCH : ST_GAME;
          end
        end
      end

      ST_GAME: begin
        // server already holds the winner of the last rally, which is the
        // winner of the game, who serves first in the next game.
        if (ev_next) begin
          nxt[4:0]   = 5'd0;
          nxt[9:5]   = 5'd0;
          nxt[16:15] = ST_PLAY;
        end
      end

      default: begin // ST_MATCH
        if (ev_next) nxt = 17'd0;
      end
    endcase
  end

  wire change = (nxt != cur);

  // ------------------------------------------------------------------
  // State register with single-level undo. Undo SWAPS with the shadow,
  // so the same button serves as undo and redo alternately.
  // No RAM on the tile, so deeper history is out of scope.
  // ------------------------------------------------------------------
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cur    <= 17'd0;
      shadow <= 17'd0;
    end else if (change) begin
      shadow <= cur;
      cur    <= nxt;
    end else if (ev_undo) begin
      cur    <= shadow;
      shadow <= cur;
    end
  end

  // ------------------------------------------------------------------
  // Display: 4-digit multiplex, shared segment decoder
  // ------------------------------------------------------------------
  function [3:0] bcd_t;
    input [4:0] s;
    begin
      bcd_t = (s >= 5'd30) ? 4'd3 :
              (s >= 5'd20) ? 4'd2 :
              (s >= 5'd10) ? 4'd1 : 4'd0;
    end
  endfunction

  function [3:0] bcd_u;
    input [4:0] s;
    reg   [4:0] r;
    begin
      r = (s >= 5'd30) ? (s - 5'd30) :
          (s >= 5'd20) ? (s - 5'd20) :
          (s >= 5'd10) ? (s - 5'd10) : s;
      bcd_u = r[3:0];
    end
  endfunction

  // bit order is {g,f,e,d,c,b,a} so uo_out[0] = segment a
  function [6:0] seg7;
    input [3:0] d;
    begin
      case (d)
        4'd0: seg7 = 7'b0111111;
        4'd1: seg7 = 7'b0000110;
        4'd2: seg7 = 7'b1011011;
        4'd3: seg7 = 7'b1001111;
        4'd4: seg7 = 7'b1100110;
        4'd5: seg7 = 7'b1101101;
        4'd6: seg7 = 7'b1111101;
        4'd7: seg7 = 7'b0000111;
        4'd8: seg7 = 7'b1111111;
        4'd9: seg7 = 7'b1101111;
        default: seg7 = 7'b0000000;
      endcase
    end
  endfunction

  reg [1:0] digit;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) digit <= 2'd0;
    else        digit <= digit + 2'd1;
  end

  reg [3:0] dval;
  reg       blank;
  always @(*) begin
    case (digit)
      2'd0: begin dval = bcd_t(score_a); blank = (bcd_t(score_a) == 4'd0); end
      2'd1: begin dval = bcd_u(score_a); blank = 1'b0;                     end
      2'd2: begin dval = bcd_t(score_b); blank = (bcd_t(score_b) == 4'd0); end
      default: begin dval = bcd_u(score_b); blank = 1'b0;                  end
    endcase
  end

  // decimal point on a tens digit = that side has won a game
  wire dp = (digit == 2'd0) ? (games_a != 2'd0) :
            (digit == 2'd2) ? (games_b != 2'd0) : 1'b0;

  assign uo_out = {dp, (blank ? 7'b0000000 : seg7(dval))};

  // ------------------------------------------------------------------
  // Indicators
  // ------------------------------------------------------------------
  wire in_play    = (state == ST_PLAY);
  wire game_point = in_play && (win_a || win_b);

  assign uio_out = { (state == ST_MATCH),   // [7] match over
                     game_point,            // [6] game point / match point
                     in_play &&  server,    // [5] side B serving
                     in_play && !server,    // [4] side A serving
                     (4'b0001 << digit) };  // [3:0] digit enable, one-hot

  assign uio_oe = 8'hFF;

  wire _unused = &{ena, uio_in, ui_in[7:6], 1'b0};

endmodule
