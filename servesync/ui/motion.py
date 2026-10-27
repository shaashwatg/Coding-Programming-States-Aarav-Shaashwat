"""
Motion tokens and spring-based animation, always optional.

Motion here only ever *explains a change* — the navigation marker slides to
the page you chose, a confirmation rises into view, chart bars grow once when
a report opens. Nothing moves on its own, loops, or flashes (WCAG 2.3).

When the person turns on **Reduce motion** (Settings), every helper below
jumps straight to the end state instead of animating (WCAG 2.3.3, AAA).

Spring easing
-------------
CSS-style cubic-béziers can't overshoot naturally; physical springs can. The
curve is the closed-form solution of a damped harmonic oscillator,

    x(t) = 1 - e^(-ζωt) · (cos(ω_d t) + (ζω / ω_d) · sin(ω_d t)),   ω_d = ω·√(1-ζ²)

with damping ratio ζ = 0.82 (about a 1% overshoot: lively, never bouncy) and
ω chosen so the motion settles inside the duration. It is normalized so
x(1) = 1 exactly, then handed to Qt as a custom ``QEasingCurve``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractAnimation, QByteArray, QEasingCurve, QObject, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from servesync.ui.theme import motion_allowed

#: Durations (ms). Short enough to never slow anyone down (< 400 ms).
DURATION_FAST = 140
DURATION_BASE = 240
DURATION_SLOW = 380

#: Equivalent cubic-bézier for documentation/CSS parity: "standard ease-out".
EASE_OUT_BEZIER = (0.22, 1.0, 0.36, 1.0)


def spring_progress(t: float, damping: float = 0.82, omega: float = 9.0) -> float:
    """Position of a damped spring released at 0 heading for 1, at normalized time ``t``."""
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0

    def raw(x: float) -> float:
        damped = omega * math.sqrt(1 - damping**2)
        envelope = math.exp(-damping * omega * x)
        return 1 - envelope * (math.cos(damped * x) + (damping * omega / damped) * math.sin(damped * x))

    return raw(t) / raw(1.0)


_SPRING: list[QEasingCurve] = []


def spring_curve() -> QEasingCurve:
    """
    The shared spring curve. Created once and kept for the life of the app:
    PySide ties a custom curve's Python function to the curve object that set
    it, so a temporary curve would leave running animations pointing at
    freed memory.
    """
    if not _SPRING:
        curve = QEasingCurve()
        curve.setCustomType(spring_progress)
        _SPRING.append(curve)
    return _SPRING[0]


def animate(
    target: QObject,
    prop: str,
    end: object,
    *,
    start: object | None = None,
    duration: int = DURATION_BASE,
    curve: QEasingCurve | None = None,
) -> QPropertyAnimation | None:
    """
    Animate ``target.prop`` to ``end`` with a spring, or set it instantly when
    motion is reduced. Returns the running animation (or None).
    """
    name = QByteArray(prop.encode("ascii"))
    if not motion_allowed():
        target.setProperty(prop, end)
        return None
    animation = QPropertyAnimation(target, name, target)
    animation.setDuration(duration)
    animation.setEasingCurve(curve or spring_curve())
    if start is not None:
        animation.setStartValue(start)
    animation.setEndValue(end)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def fade_in(widget: QWidget, duration: int = DURATION_BASE) -> None:
    """Fade a widget in (instant with reduced motion). The effect is removed afterwards."""
    if not motion_allowed():
        widget.setGraphicsEffect(None)  # type: ignore[arg-type]  # Qt accepts None to clear
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = animate(
        effect, "opacity", 1.0, start=0.0, duration=duration, curve=QEasingCurve(QEasingCurve.Type.OutCubic)
    )
    if animation is not None:
        animation.finished.connect(lambda: widget.setGraphicsEffect(None))  # type: ignore[arg-type]
