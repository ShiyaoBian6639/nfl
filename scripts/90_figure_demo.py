#!/usr/bin/env python
"""Prototype the house figure style on one drill rep.

Produces `reports/figures/drill_anatomy.png`: the view that argues the whole thesis of
a Combine-tracking submission -- the stopwatch records one number, the trace records
where the athlete actually lost and regained speed.

    python scripts/90_figure_demo.py [--drill THREE_CONE_DRILL] [--theme light|dark]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from nflbdb import ingest, viz
from nflbdb.kinematics import derivatives, detect_cuts, to_uniform_grid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drill", default="THREE_CONE_DRILL")
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--event-id", default=None)
    args = ap.parse_args()

    t = viz.use_theme(args.theme)

    ct = (ingest.scan("combine_tracking")
          .filter((pl.col("entity_type") == "PLAYER")
                  & (pl.col("drill_name").cast(pl.Utf8) == args.drill))
          .collect())
    if ct.is_empty():
        print(f"no frames for drill {args.drill!r}", file=sys.stderr)
        return 1

    eid = args.event_id or ct["event_id"][0]
    g = ct.filter(pl.col("event_id") == eid).sort("time")
    tt = g["time"].dt.timestamp("ms").to_numpy() / 1000.0
    tt -= tt[0]
    tg, (xg, yg), _ = to_uniform_grid(tt, g["x"].to_numpy(), g["y"].to_numpy())
    k = derivatives(tg, xg, yg, cutoff_hz=2.0)
    cuts = detect_cuts(k, min_speed_drop_frac=0.15, min_heading_change_deg=30)

    fig = plt.figure(figsize=(12.2, 5.6))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.05, 1.25], height_ratios=[1, 1],
                          wspace=0.22, hspace=0.42)
    ax_path = fig.add_subplot(gs[:, 0])
    ax_sp = fig.add_subplot(gs[0, 1])
    ax_a = fig.add_subplot(gs[1, 1], sharex=ax_sp)

    # ---- left: the path, coloured by speed
    viz.drill_canvas(ax_path)
    viz.speed_ribbon(ax_path, k.x, k.y, k.speed, lw=4.0, cbar_location="bottom")
    ax_path.plot(k.x[0], k.y[0], "o", mfc=t.surface, mec=t.text_secondary, mew=2, ms=9, zorder=5)
    ax_path.plot(k.x[-1], k.y[-1], "o", color=t.text_secondary, ms=9,
                 mec=t.surface, mew=1.5, zorder=5)
    viz.annotate_cuts(ax_path, k, cuts)
    pad = 1.5
    ax_path.set_xlim(k.x.min() - pad, k.x.max() + pad)
    ax_path.set_ylim(k.y.min() - pad, k.y.max() + pad)
    viz.finish(ax_path, title="Where the time actually goes",
               subtitle=f"{args.drill.replace('_', ' ').title()} · {len(cuts)} "
                        f"change-of-direction events detected")

    # ---- top right: speed with the cut windows shaded
    ax_sp.plot(k.t - k.t[0], k.speed, color=t.series[0], lw=2.2)
    for i, c in enumerate(cuts, 1):
        ax_sp.axvspan(c.t_start - k.t[0], c.t_end - k.t[0], color=t.series[1], alpha=0.10, lw=0)
        ax_sp.annotate(str(i), (c.t_min - k.t[0], c.min_speed), textcoords="offset points",
                       xytext=(0, -15), ha="center", color=t.text_primary,
                       fontsize=9, fontweight="600")
        ax_sp.plot(c.t_min - k.t[0], c.min_speed, "o", color=t.series[1], ms=7,
                   mec=t.surface, mew=1.4, zorder=4)
    ax_sp.set_ylabel("speed (yd/s)")
    ax_sp.tick_params(labelbottom=False)
    viz.finish(ax_sp, title="Speed trace",
               subtitle="shaded = time inside a cut; the stopwatch sees only the total")

    # ---- bottom right: braking vs re-acceleration, one axis
    ax_a.axhline(0, color=t.grid, lw=1.0)
    ta = k.a_tan
    ax_a.fill_between(k.t - k.t[0], 0, np.clip(ta, 0, None),
                      color=t.series[2], alpha=0.85, lw=0, label="propulsion")
    ax_a.fill_between(k.t - k.t[0], 0, np.clip(ta, None, 0),
                      color=t.series[1], alpha=0.85, lw=0, label="braking")
    # aqua is below 3:1 on the light surface -> direct labels, not legend-only
    ax_a.text(0.985, 0.90, "propulsion", transform=ax_a.transAxes, ha="right",
              color=t.text_secondary, fontsize=9, fontweight="600")
    ax_a.text(0.985, 0.08, "braking", transform=ax_a.transAxes, ha="right",
              color=t.text_secondary, fontsize=9, fontweight="600")
    ax_a.set_ylabel("tangential accel (yd/s²)")
    ax_a.set_xlabel("time since movement onset (s)")
    viz.finish(ax_a, title="Braking and re-acceleration",
               subtitle="the component the official drill time cannot separate")

    out = viz.save(fig, f"drill_anatomy_{args.theme}")
    print(f"wrote {out[0]}")
    print(f"  event_id={eid}  frames={k.t.size}  peak_speed={k.speed.max():.2f} yd/s  "
          f"cuts={len(cuts)}")
    for i, c in enumerate(cuts, 1):
        print(f"  cut {i}: entry {c.entry_speed:5.2f} -> min {c.min_speed:5.2f} yd/s  "
              f"({c.speed_lost_pct:4.0%} lost)  swing {c.heading_change_deg:5.0f}°  "
              f"brake {c.peak_decel:6.2f}  reaccel {c.peak_reaccel:5.2f} yd/s²  "
              f"r={c.min_turn_radius:.2f} yd")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
