"""Tiny SVG chart helpers for the write-up card (theme tokens, no dependencies)."""

from __future__ import annotations

import math
from html import escape

W = 750
LABEL_W = 178
RIGHT_W = 96
ROW_H = 26
TOP = 30
BOTTOM = 34


def _x_log(v: float, lo: float, hi: float) -> float:
    span = W - LABEL_W - RIGHT_W
    return LABEL_W + span * (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))


def _x_lin(v: float, hi: float) -> float:
    return LABEL_W + (W - LABEL_W - RIGHT_W) * v / hi


def fmt_s(s: float) -> str:
    if s < 0.001:
        return f"{s * 1e6:.0f} µs"
    if s < 1:
        return f"{s * 1000:.0f} ms" if s >= 0.0095 else f"{s * 1000:.1f} ms"
    return f"{s:.1f} s" if s < 10 else f"{s:.0f} s"


def fmt_x(r: float) -> str:
    return f"{r:.1f}×" if r < 10 else f"{r:.0f}×"


def _frame(h: int, aria: str, body: list[str]) -> str:
    return (
        f'<figure aria-label="{escape(aria)}" style="margin:0">'
        f'<svg viewBox="0 0 {W} {h}" width="100%" role="img" style="display:block;font-family:inherit">'
        + "".join(body)
        + "</svg></figure>"
    )


def legend(items: list[tuple[str, str]], y: int = 14) -> list[str]:
    """items: (svg-marker-kind:color, label)."""
    out, x = [], LABEL_W
    for kind, label in items:
        shape, color = kind.split(":", 1)
        if shape == "dot":
            out.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{color}"/>')
        elif shape == "ring":
            out.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="4.2" fill="none" stroke="{color}" stroke-width="1.8"/>')
        else:
            out.append(f'<rect x="{x}" y="{y - 9}" width="12" height="10" rx="2" fill="{color}"/>')
        out.append(f'<text x="{x + 17}" y="{y}" fill="var(--fg-2)">{escape(label)}</text>')
        x += 17 + 6.7 * len(label) + 20
    return out


def log_dot_plot(
    rows: list[dict],
    series: list[dict],
    lo: float,
    hi: float,
    ticks: list[tuple[float, str]],
    aria: str,
    right_title: str = "",
    ref_line: tuple[float, str] | None = None,
    connect: bool = True,
) -> str:
    """rows: {label, values: {series_key: v}, spread: {series_key: (min, max)}, right: str, right_strong: bool}
    series: {key, color, shape ('dot' | 'ring'), label}"""
    h = TOP + ROW_H * len(rows) + BOTTOM
    body = legend([(f"{s['shape']}:{s['color']}", s["label"]) for s in series])
    plot_bottom = TOP + ROW_H * len(rows)
    for v, t in ticks:
        x = _x_log(v, lo, hi)
        body.append(f'<line x1="{x:.0f}" x2="{x:.0f}" y1="{TOP - 4}" y2="{plot_bottom}" stroke="var(--line-1)" stroke-width="1"/>')
        body.append(
            f'<text x="{x:.0f}" y="{plot_bottom + 16}" text-anchor="middle" font-size="11" '
            f'font-family="var(--font-mono)" fill="var(--fg-3)">{escape(t)}</text>'
        )
    if ref_line:
        x = _x_log(ref_line[0], lo, hi)
        body.append(f'<line x1="{x:.0f}" x2="{x:.0f}" y1="{TOP - 4}" y2="{plot_bottom}" stroke="var(--fg-3)" stroke-width="1.5"/>')
        body.append(
            f'<text x="{x:.0f}" y="{plot_bottom + 30}" text-anchor="middle" font-size="11" '
            f'font-family="var(--font-mono)" fill="var(--fg-2)">{escape(ref_line[1])}</text>'
        )
    two = any(r.get("right2") for r in rows)
    titles = right_title.split("|") if right_title else []
    for j, title in enumerate(titles):
        tx = W - 4 - (46 if two and j == 0 else 0)
        body.append(
            f'<text x="{tx}" y="14" text-anchor="end" font-size="11" font-family="var(--font-mono)" '
            f'fill="var(--fg-3)">{escape(title)}</text>'
        )
    for i, r in enumerate(rows):
        y = TOP + ROW_H * i + ROW_H / 2
        body.append(f'<text x="{LABEL_W - 12}" y="{y + 4:.0f}" text-anchor="end" fill="var(--fg-1)">{escape(r["label"])}</text>')
        xs = [_x_log(r["values"][s["key"]], lo, hi) for s in series if s["key"] in r["values"]]
        if connect and len(xs) > 1:
            body.append(
                f'<line x1="{min(xs):.0f}" x2="{max(xs):.0f}" y1="{y:.0f}" y2="{y:.0f}" stroke="var(--line-2)" stroke-width="2"/>'
            )
        for s in series:
            if s["key"] not in r["values"]:
                continue
            v = r["values"][s["key"]]
            x = _x_log(v, lo, hi)
            sp = r.get("spread", {}).get(s["key"])
            if sp:
                x0, x1 = _x_log(sp[0], lo, hi), _x_log(sp[1], lo, hi)
                if x1 - x0 > 3:
                    body.append(
                        f'<line x1="{x0:.0f}" x2="{x1:.0f}" y1="{y:.0f}" y2="{y:.0f}" stroke="{s["color"]}" stroke-width="2" opacity="0.55"/>'
                    )
            tip = ""
            if s["shape"] == "ring":
                body.append(
                    f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="var(--bg-1)" stroke="{s["color"]}" stroke-width="2">{tip}</circle>'
                )
            else:
                body.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5.5" fill="{s["color"]}" stroke="var(--bg-1)" stroke-width="2">{tip}</circle>')
        if r.get("right"):
            weight = ' font-weight="600"' if r.get("right_strong") else ""
            color = "var(--fg-1)" if r.get("right_strong") else "var(--fg-2)"
            rx = W - 4 - (46 if two else 0)
            body.append(f'<text x="{rx}" y="{y + 4:.0f}" text-anchor="end" fill="{color}"{weight}>{escape(r["right"])}</text>')
        if r.get("right2"):
            body.append(f'<text x="{W - 4}" y="{y + 4:.0f}" text-anchor="end" fill="var(--fg-2)">{escape(r["right2"])}</text>')
    return _frame(h, aria, body)


def bar_plot(
    rows: list[dict],
    series: list[dict],
    hi: float,
    ticks: list[tuple[float, str]],
    aria: str,
    bar_h: int = 9,
    gap: int = 2,
    group_pad: int = 12,
    value_fmt=fmt_s,
) -> str:
    """Grouped horizontal bars on a linear scale.
    rows: {label, values: {series_key: v}}; series: {key, color, label}"""
    n = len(series)
    group_h = n * bar_h + (n - 1) * gap + group_pad
    h = TOP + group_h * len(rows) + BOTTOM - group_pad + 6
    body = legend([(f"bar:{s['color']}", s["label"]) for s in series])
    plot_bottom = TOP + group_h * len(rows) - group_pad + 6
    for v, t in ticks:
        x = _x_lin(v, hi)
        body.append(f'<line x1="{x:.0f}" x2="{x:.0f}" y1="{TOP - 4}" y2="{plot_bottom}" stroke="var(--line-1)" stroke-width="1"/>')
        body.append(
            f'<text x="{x:.0f}" y="{plot_bottom + 16}" text-anchor="middle" font-size="11" '
            f'font-family="var(--font-mono)" fill="var(--fg-3)">{escape(t)}</text>'
        )
    for i, r in enumerate(rows):
        y0 = TOP + group_h * i + 3
        mid = y0 + (n * bar_h + (n - 1) * gap) / 2
        body.append(f'<text x="{LABEL_W - 12}" y="{mid + 4:.0f}" text-anchor="end" fill="var(--fg-1)">{escape(r["label"])}</text>')
        for j, s in enumerate(series):
            if s["key"] not in r["values"]:
                continue
            v = r["values"][s["key"]]
            y = y0 + j * (bar_h + gap)
            w = max(2.0, _x_lin(v, hi) - LABEL_W)
            tip = ""
            body.append(f'<rect x="{LABEL_W}" y="{y}" width="{w:.0f}" height="{bar_h}" rx="2" fill="{s["color"]}">{tip}</rect>')
            body.append(
                f'<text x="{LABEL_W + w + 6:.0f}" y="{y + bar_h - 1}" font-size="11" font-family="var(--font-mono)" '
                f'fill="var(--fg-2)">{escape(value_fmt(v))}</text>'
            )
    return _frame(h, aria, body)
