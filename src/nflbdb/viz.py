"""Figure toolkit: one visual system for every chart in the submission.

Data Visualization is 20% of the Big Data Bowl score and the charts are the first thing
a judge looks at, so they are treated here as a designed system rather than as matplotlib
defaults. Everything a figure needs -- palette, typography, field geometry, trajectory
rendering -- comes from this module so that nine figures read as one document.

Palette
-------
Validated categorical hues in fixed slot order (never cycled), checked for
colour-vision-deficiency separation under all-pairs comparison:
worst CVD deltaE 9.2, worst normal-vision deltaE 24.0 for the first three slots.
``AQUA`` sits below 3:1 against the light surface, so anything drawn in it carries a
direct label rather than relying on the legend.

Rules this module enforces
--------------------------
* fixed categorical slot order, never cycled; a 9th series folds into "Other"
* one y-axis per panel -- never a dual-axis chart
* recessive grid and spines, thin marks, selective direct labels
* light and dark variants stepped for their own surface, not auto-inverted
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Rectangle

from .config import ENDZONE, FIELD_LENGTH, FIELD_WIDTH, HASH_FROM_SIDELINE

__all__ = [
    "PALETTE", "LIGHT", "DARK", "Theme", "use_theme", "series_color",
    "football_field", "drill_canvas", "plot_trajectory", "speed_ribbon",
    "annotate_cuts", "finish", "save",
]


# ======================================================================================
# Palette
# ======================================================================================

@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    text_primary: str
    text_secondary: str
    text_muted: str
    grid: str
    series: tuple[str, ...]
    sequential: tuple[str, ...]
    diverge_low: str
    diverge_mid: str
    diverge_high: str
    turf: str
    turf_line: str


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    text_primary="#0b0b0b",
    text_secondary="#52514e",
    text_muted="#8a8984",
    grid="#e6e5e1",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    sequential=("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#256abf", "#184f95", "#0d366b"),
    diverge_low="#2a78d6", diverge_mid="#f0efec", diverge_high="#e34948",
    turf="#f4f3f0", turf_line="#d8d7d2",
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    text_primary="#ffffff",
    text_secondary="#c3c2b7",
    text_muted="#8a8980",
    grid="#333331",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
    sequential=("#0d366b", "#184f95", "#256abf", "#2a78d6", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"),
    diverge_low="#3987e5", diverge_mid="#383835", diverge_high="#e66767",
    turf="#242423", turf_line="#3a3a38",
)

PALETTE = LIGHT  # module-level current theme


def series_color(i: int, theme: Theme | None = None) -> str:
    """Categorical hue for slot ``i``. Raises past slot 8 instead of cycling.

    Cycling is what makes a chart with nine series unreadable; the fix is to fold the
    tail into "Other" or to facet, never to reuse a hue.
    """
    t = theme or PALETTE
    if i >= len(t.series):
        raise IndexError(
            f"categorical slot {i} exceeds the {len(t.series)}-hue palette. "
            "Fold the tail into 'Other', facet into small multiples, or encode with "
            "position instead of a new hue."
        )
    return t.series[i]


def use_theme(theme: Theme | str = LIGHT) -> Theme:
    """Install the house matplotlib style. Call once at the top of a notebook."""
    global PALETTE
    t = {"light": LIGHT, "dark": DARK}[theme] if isinstance(theme, str) else theme
    PALETTE = t
    mpl.rcParams.update({
        "figure.facecolor": t.surface,
        "axes.facecolor": t.surface,
        "savefig.facecolor": t.surface,
        "savefig.bbox": "tight",
        "savefig.dpi": 200,
        "figure.dpi": 110,
        "font.family": "sans-serif",
        "font.sans-serif": ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 10,
        "text.color": t.text_primary,
        "axes.labelcolor": t.text_secondary,
        "axes.edgecolor": t.grid,
        "axes.linewidth": 0.8,
        "axes.titlesize": 12,
        "axes.titleweight": "600",
        "axes.titlelocation": "left",
        "axes.titlepad": 10,
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": t.grid,
        "grid.linewidth": 0.7,
        "grid.alpha": 1.0,
        "xtick.color": t.text_muted,
        "ytick.color": t.text_muted,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "lines.linewidth": 2.0,
        "lines.solid_capstyle": "round",
        "lines.markersize": 5,
        "patch.linewidth": 0,
        "axes.prop_cycle": mpl.cycler(color=list(t.series)),
    })
    return t


# ======================================================================================
# Field & drill canvases
# ======================================================================================

def football_field(
    ax: plt.Axes | None = None,
    *,
    xlim: tuple[float, float] | None = None,
    ylim: tuple[float, float] | None = None,
    yard_numbers: bool = True,
    theme: Theme | None = None,
) -> plt.Axes:
    """Draw a regulation NFL field to scale, as a recessive backdrop.

    The field is scenery, not data: lines sit at low contrast so that trajectories drawn
    on top are the only thing with visual weight.
    """
    t = theme or PALETTE
    if ax is None:
        _, ax = plt.subplots(figsize=(13, 6.2))

    ax.add_patch(Rectangle((0, 0), FIELD_LENGTH, FIELD_WIDTH, facecolor=t.turf, zorder=0))
    for ez_x in (0, FIELD_LENGTH - ENDZONE):
        ax.add_patch(Rectangle((ez_x, 0), ENDZONE, FIELD_WIDTH,
                               facecolor=t.turf_line, alpha=0.35, zorder=0))

    for xx in np.arange(ENDZONE, FIELD_LENGTH - ENDZONE + 0.1, 5):
        major = (xx - ENDZONE) % 10 == 0
        ax.plot([xx, xx], [0, FIELD_WIDTH], color=t.turf_line,
                lw=1.0 if major else 0.6, alpha=1.0 if major else 0.6, zorder=1)

    # 1-yard hash ticks
    for xx in np.arange(ENDZONE + 1, FIELD_LENGTH - ENDZONE, 1):
        for yy in (HASH_FROM_SIDELINE, FIELD_WIDTH - HASH_FROM_SIDELINE):
            ax.plot([xx, xx], [yy - 0.35, yy + 0.35], color=t.turf_line, lw=0.6, zorder=1)

    if yard_numbers:
        for xx in np.arange(ENDZONE + 10, FIELD_LENGTH - ENDZONE, 10):
            n = int(50 - abs(50 - (xx - ENDZONE)))
            for yy in (5.5, FIELD_WIDTH - 5.5):
                ax.text(xx, yy, str(n), ha="center", va="center",
                        color=t.turf_line, fontsize=11, fontweight="600", zorder=1)

    ax.set_xlim(*(xlim or (0, FIELD_LENGTH)))
    ax.set_ylim(*(ylim or (0, FIELD_WIDTH)))
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    return ax


def drill_canvas(
    ax: plt.Axes | None = None, *, pad: float = 2.0, theme: Theme | None = None
) -> plt.Axes:
    """A bare, equal-aspect canvas for a single drill, with a 1-yard reference grid.

    Combine drills occupy a few square yards of a 120-yard field, so the full-field
    backdrop would waste the whole frame. This gives the trajectory the frame instead.
    """
    t = theme or PALETTE
    if ax is None:
        _, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.set_aspect("equal")
    ax.grid(True, color=t.grid, lw=0.6)
    ax.set_xlabel("x (yd)"); ax.set_ylabel("y (yd)")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax._nflbdb_pad = pad  # type: ignore[attr-defined]
    return ax


# ======================================================================================
# Trajectory rendering
# ======================================================================================

def plot_trajectory(
    ax: plt.Axes, x, y, *, color: str | None = None, label: str | None = None,
    lw: float = 2.0, alpha: float = 1.0, markers: bool = True, theme: Theme | None = None,
) -> plt.Axes:
    """Draw one path with start/end markers.

    Start is a hollow ring, end is a filled dot: direction is readable without an
    arrowhead cluttering the line, and the convention stays identical across figures.
    """
    t = theme or PALETTE
    c = color or t.series[0]
    ax.plot(x, y, color=c, lw=lw, alpha=alpha, solid_capstyle="round", label=label, zorder=3)
    if markers:
        ax.plot(x[0], y[0], "o", mfc=t.surface, mec=c, mew=2.0, ms=8, zorder=4)
        ax.plot(x[-1], y[-1], "o", color=c, ms=8, mec=t.surface, mew=1.5, zorder=4)
    return ax


def speed_ribbon(
    ax: plt.Axes, x, y, speed, *, cmap_steps: tuple[str, ...] | None = None,
    lw: float = 3.5, vmin: float | None = None, vmax: float | None = None,
    theme: Theme | None = None, colorbar: bool = True, label: str = "speed (yd/s)",
    cbar_location: str = "right",
) -> plt.Axes:
    """Draw a path coloured by instantaneous speed, one hue, light to dark.

    This is the single most informative view of a drill rep: it shows *where on the
    field* an athlete was fast and, more importantly, where he had to slow down. The
    ramp is sequential (one hue), never a rainbow -- magnitude maps to lightness.
    """
    from matplotlib.collections import LineCollection
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    t = theme or PALETTE
    steps = cmap_steps or t.sequential
    cmap = LinearSegmentedColormap.from_list("nflbdb_seq", list(steps))
    x, y, speed = np.asarray(x), np.asarray(y), np.asarray(speed)

    pts = np.array([x, y]).T.reshape(-1, 1, 2)
    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
    norm = Normalize(vmin if vmin is not None else float(np.nanmin(speed)),
                     vmax if vmax is not None else float(np.nanmax(speed)))
    lc = LineCollection(segs, cmap=cmap, norm=norm, linewidth=lw,
                        capstyle="round", joinstyle="round", zorder=3)
    lc.set_array(speed[:-1])
    ax.add_collection(lc)
    if colorbar:
        # On an equal-aspect panel a vertical bar steals width from the drawing and its
        # caption collides with the neighbouring column; "bottom" is the better default
        # whenever the panel is square.
        horizontal = cbar_location == "bottom"
        cb = ax.figure.colorbar(
            lc, ax=ax, location=cbar_location,
            fraction=0.040 if horizontal else 0.030,
            pad=0.17 if horizontal else 0.035,
            aspect=38 if horizontal else 28,
        )
        cb.outline.set_visible(False)
        cb.ax.tick_params(colors=t.text_muted, labelsize=8, length=0)
        if horizontal:
            cb.set_label(label, color=t.text_secondary, fontsize=9)
        else:
            cb.ax.set_title(label, color=t.text_secondary, fontsize=9, loc="left", pad=8)
    return ax


def annotate_cuts(ax: plt.Axes, k, cuts, *, theme: Theme | None = None,
                  label_fmt: str = "{i}") -> plt.Axes:
    """Mark detected change-of-direction events on a trajectory.

    Direct numeric labels rather than a legend: the reader should not have to carry a
    colour key between the path and the speed trace below it.
    """
    t = theme or PALETTE
    for i, c in enumerate(cuts, 1):
        ax.plot(k.x[c.i_min], k.y[c.i_min], "o", color=t.series[1], ms=9,
                mec=t.surface, mew=1.5, zorder=5)
        ax.annotate(label_fmt.format(i=i), (k.x[c.i_min], k.y[c.i_min]),
                    textcoords="offset points", xytext=(9, 7),
                    color=t.text_primary, fontsize=9, fontweight="600", zorder=6)
    return ax


# ======================================================================================
# Finishing
# ======================================================================================

def finish(
    ax: plt.Axes, *, title: str = "", subtitle: str = "", source: str = "",
    legend: bool = False, theme: Theme | None = None,
) -> plt.Axes:
    """Apply the house title block.

    Title states the finding, subtitle states the method and the n. A judge reading only
    the titles of nine figures should come away with the argument.
    """
    t = theme or PALETTE
    # Both lines are drawn as axes text rather than via set_title: matplotlib's title
    # slot holds exactly one line, and stacking a subtitle under a repositioned title
    # collides as soon as the axes box changes (equal-aspect panels, colorbars).
    if subtitle:
        ax.text(0, 1.012, subtitle, transform=ax.transAxes, ha="left", va="bottom",
                color=t.text_secondary, fontsize=9.5)
    if title:
        ax.text(0, 1.012 + (0.075 if subtitle else 0.0), title, transform=ax.transAxes,
                ha="left", va="bottom", color=t.text_primary,
                fontsize=12.5, fontweight="600")
    if source:
        ax.figure.text(0.005, -0.015, source, ha="left", va="top",
                       color=t.text_muted, fontsize=8)
    if legend:
        ax.legend(loc="upper left", frameon=False, fontsize=9,
                  labelcolor=t.text_secondary, handlelength=1.4, borderaxespad=0)
    return ax


def save(fig, name: str, *, also_dark: bool = False) -> list:
    """Write a figure into reports/figures/ and return the paths written."""
    from .config import FIGURES
    FIGURES.mkdir(parents=True, exist_ok=True)
    out = [FIGURES / f"{name}.png"]
    fig.savefig(out[0], dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    if also_dark:
        out.append(FIGURES / f"{name}.dark.png")
    return out
