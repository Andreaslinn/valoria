"""Shared visual primitives for the Streamlit UI."""
from __future__ import annotations

from html import escape

import streamlit as st

VALID_TONES = {"neutral", "positive", "negative", "warning", "premium"}
DEFAULT_TONE = "neutral"
THEME_KEY = "avm_color_mode"
LIGHT_MODE = "light"
DARK_MODE = "dark"
LAB_DEMO_MODE_KEY = "product_lab_feature_demo_mode"


def normalize_tone(tone: str | None) -> str:
    """Return a supported visual tone."""
    if tone in VALID_TONES:
        return tone
    return DEFAULT_TONE


def tone_class(prefix: str, tone: str | None) -> str:
    """Build a stable CSS class for a component tone."""
    return f"{prefix}--{normalize_tone(tone)}"


def html_escape(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def get_color_mode() -> str:
    mode = st.session_state.get(THEME_KEY, DARK_MODE)
    return DARK_MODE if mode == DARK_MODE else LIGHT_MODE


def set_color_mode(mode: str) -> None:
    st.session_state[THEME_KEY] = DARK_MODE if mode == DARK_MODE else LIGHT_MODE


def theme_toggle() -> str:
    set_color_mode(DARK_MODE)
    st.toggle("Modo oscuro", value=True, disabled=True)
    st.caption("Tema oficial AVM Chile activo.")
    return DARK_MODE


def _lab_dark_theme_css() -> str:
    """Return Lab-only dark mode refinements."""
    return """
        :root {
            --avm-bg: #05070d;
            --avm-surface: rgba(13, 18, 31, 0.92);
            --avm-surface-alt: rgba(9, 13, 24, 0.9);
            --avm-surface-muted: rgba(16, 23, 38, 0.74);
            --avm-surface-elevated: rgba(21, 29, 47, 0.88);
            --avm-surface-focus: rgba(30, 41, 73, 0.92);
            --avm-border: rgba(148, 163, 184, 0.14);
            --avm-border-strong: rgba(148, 163, 184, 0.24);
            --avm-text: #f8fafc;
            --avm-muted: #9ba8bd;
            --avm-shadow: 0 18px 60px rgba(0, 0, 0, 0.46), inset 0 1px 0 rgba(255, 255, 255, 0.04);
            --avm-glow: 0 0 0 1px rgba(99, 102, 241, 0.18), 0 24px 70px rgba(37, 99, 235, 0.12);
            --avm-neutral: #b7c0cf;
            --avm-positive: #52f2a8;
            --avm-negative: #ff7b8a;
            --avm-warning: #ffd166;
            --avm-premium: #9aa7ff;
            --avm-accent: #57c7ff;
            --avm-neutral-bg: rgba(148, 163, 184, 0.1);
            --avm-positive-bg: rgba(34, 197, 94, 0.13);
            --avm-negative-bg: rgba(244, 63, 94, 0.13);
            --avm-warning-bg: rgba(245, 158, 11, 0.14);
            --avm-premium-bg: rgba(99, 102, 241, 0.18);
            --avm-hero-bg: linear-gradient(135deg, rgba(12, 18, 33, 0.94) 0%, rgba(18, 24, 45, 0.9) 48%, rgba(35, 28, 66, 0.86) 100%);
            --avm-chip-bg: rgba(15, 23, 42, 0.68);
        }

        html,
        body,
        .stApp,
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 18% -8%, rgba(59, 130, 246, 0.17), transparent 31%),
                radial-gradient(circle at 82% 0%, rgba(139, 92, 246, 0.13), transparent 29%),
                linear-gradient(180deg, #05070d 0%, #070a12 48%, #090d16 100%);
        }

        [data-testid="stAppViewContainer"] > .main {
            background: transparent;
        }

        [data-testid="stHeader"] {
            background: linear-gradient(180deg, rgba(5, 7, 13, 0.88), rgba(5, 7, 13, 0));
        }

        section[data-testid="stSidebar"] {
            background:
                linear-gradient(180deg, rgba(9, 13, 24, 0.97), rgba(12, 17, 30, 0.96)),
                radial-gradient(circle at 30% 0%, rgba(87, 199, 255, 0.12), transparent 35%);
            border-right: 1px solid rgba(148, 163, 184, 0.12);
            box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.03);
        }

        div[data-testid="stVerticalBlock"] {
            gap: 0.72rem;
        }

        .avm-app-shell {
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-radius: 12px;
            background: linear-gradient(135deg, rgba(13, 18, 31, 0.82), rgba(9, 13, 24, 0.58));
            box-shadow: 0 14px 44px rgba(0, 0, 0, 0.28);
            padding: 0.78rem 0.9rem 0.88rem;
            backdrop-filter: blur(18px);
        }

        .avm-user-pill {
            background: rgba(15, 23, 42, 0.62);
            border-color: rgba(148, 163, 184, 0.14);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
        }

        .avm-card {
            border: 1px solid rgba(148, 163, 184, 0.13);
            background: linear-gradient(180deg, rgba(17, 24, 39, 0.86), rgba(10, 15, 26, 0.92));
            box-shadow: var(--avm-shadow);
            backdrop-filter: blur(18px);
        }

        .avm-card:hover {
            border-color: rgba(154, 167, 255, 0.22);
            box-shadow: var(--avm-glow);
        }

        .avm-metric-card {
            background: linear-gradient(180deg, rgba(22, 31, 49, 0.72), rgba(12, 18, 31, 0.88));
        }

        .avm-premium-card {
            border-left: 1px solid rgba(154, 167, 255, 0.54);
            box-shadow: 0 18px 56px rgba(34, 44, 85, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.04);
        }

        .avm-home-hero {
            border-color: rgba(154, 167, 255, 0.18);
            box-shadow: 0 28px 90px rgba(0, 0, 0, 0.42), inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }

        .avm-badge {
            border-color: rgba(255, 255, 255, 0.07);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
        }

        .avm-empty-state {
            border-color: rgba(148, 163, 184, 0.16);
            background: rgba(10, 15, 26, 0.62);
        }

        div[data-testid="stExpander"] details {
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 10px;
            background: linear-gradient(180deg, rgba(15, 23, 42, 0.72), rgba(8, 13, 23, 0.84));
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.24);
            overflow: hidden;
        }

        div[data-testid="stExpander"] summary {
            color: var(--avm-text);
            font-weight: 700;
        }

        .stButton button {
            border-radius: 999px;
            border: 1px solid rgba(154, 167, 255, 0.2);
            background: linear-gradient(180deg, rgba(38, 52, 84, 0.92), rgba(18, 27, 48, 0.96));
            color: var(--avm-text);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 10px 24px rgba(0, 0, 0, 0.2);
        }

        .stButton button:hover {
            border-color: rgba(87, 199, 255, 0.38);
            color: #ffffff;
            box-shadow: 0 0 0 3px rgba(87, 199, 255, 0.08), 0 14px 34px rgba(0, 0, 0, 0.24);
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-baseweb="select"] > div,
        textarea {
            background: rgba(7, 11, 20, 0.72);
            border-color: rgba(148, 163, 184, 0.14);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 14px 40px rgba(0, 0, 0, 0.24);
        }
    """


def _lab_motion_css() -> str:
    """Return lightweight Product Lab motion and microinteraction styles."""
    return """
        :root {
            --avm-motion-fast: 140ms;
            --avm-motion-base: 220ms;
            --avm-motion-slow: 420ms;
            --avm-ease-out: cubic-bezier(0.22, 1, 0.36, 1);
            --avm-ease-soft: cubic-bezier(0.16, 1, 0.3, 1);
        }

        @keyframes avm-lab-fade-up {
            from {
                opacity: 0;
                transform: translateY(8px);
                filter: blur(2px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
                filter: blur(0);
            }
        }

        @keyframes avm-lab-pulse-in {
            0% {
                transform: scale(0.985);
                opacity: 0.78;
            }
            100% {
                transform: scale(1);
                opacity: 1;
            }
        }

        @keyframes avm-lab-shimmer {
            0% {
                transform: translateX(-120%);
            }
            100% {
                transform: translateX(120%);
            }
        }

        @keyframes avm-lab-highlight {
            0% {
                box-shadow: 0 0 0 0 rgba(79, 70, 229, 0.22);
            }
            100% {
                box-shadow: 0 0 0 8px rgba(79, 70, 229, 0);
            }
        }

        .avm-section-header,
        .avm-lab-nav-panel,
        .avm-lab-home-hero,
        .avm-lab-home-context,
        .avm-property-hero,
        .avm-property-actions,
        .avm-property-grid,
        .avm-card,
        .avm-lab-feed-card,
        .avm-lab-portfolio-pulse,
        .avm-lab-market-row,
        .avm-property-panel,
        .avm-property-alert,
        .avm-property-comparable,
        div[data-testid="stExpander"] details {
            animation: avm-lab-fade-up var(--avm-motion-slow) var(--avm-ease-soft) both;
        }

        .avm-lab-home-context,
        .avm-property-hero__facts,
        .avm-property-comparables,
        .avm-property-price-list {
            animation-delay: 55ms;
        }

        .avm-card,
        .avm-lab-feed-card,
        .avm-lab-context-tile,
        .avm-lab-portfolio-pulse,
        .avm-lab-market-row,
        .avm-property-fact,
        .avm-property-panel,
        .avm-property-alert,
        .avm-property-comparable,
        div[data-testid="stExpander"] details {
            transition:
                transform var(--avm-motion-base) var(--avm-ease-out),
                border-color var(--avm-motion-base) var(--avm-ease-out),
                box-shadow var(--avm-motion-base) var(--avm-ease-out),
                background-color var(--avm-motion-base) var(--avm-ease-out);
            will-change: transform;
        }

        .avm-card:hover,
        .avm-lab-feed-card:hover,
        .avm-lab-context-tile:hover,
        .avm-lab-portfolio-pulse:hover,
        .avm-lab-market-row:hover,
        .avm-property-fact:hover,
        .avm-property-panel:hover,
        .avm-property-alert:hover,
        .avm-property-comparable:hover {
            transform: translateY(-2px);
        }

        .avm-badge,
        .avm-user-pill,
        .avm-lab-nav-badge,
        .avm-lab-current-indicator {
            transition:
                transform var(--avm-motion-fast) var(--avm-ease-out),
                border-color var(--avm-motion-base) var(--avm-ease-out),
                box-shadow var(--avm-motion-base) var(--avm-ease-out);
        }

        .avm-badge:hover,
        .avm-user-pill:hover,
        .avm-lab-nav-badge:hover {
            transform: translateY(-1px);
        }

        .stButton button,
        div[data-baseweb="select"] > div,
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        textarea {
            transition:
                transform var(--avm-motion-fast) var(--avm-ease-out),
                box-shadow var(--avm-motion-base) var(--avm-ease-out),
                border-color var(--avm-motion-base) var(--avm-ease-out),
                background var(--avm-motion-base) var(--avm-ease-out);
        }

        .stButton button:active {
            transform: translateY(1px) scale(0.99);
        }

        .avm-metric-card__value,
        .avm-lab-home-side strong,
        .avm-lab-pulse-pill strong,
        .avm-property-hero__price strong,
        .avm-property-fact strong {
            animation: avm-lab-pulse-in var(--avm-motion-slow) var(--avm-ease-soft) both;
        }

        .avm-lab-shimmer,
        .avm-lab-skeleton {
            position: relative;
            overflow: hidden;
            isolation: isolate;
        }

        .avm-lab-shimmer::after,
        .avm-lab-skeleton::after {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(
                90deg,
                transparent 0%,
                rgba(255, 255, 255, 0.16) 48%,
                transparent 100%
            );
            transform: translateX(-120%);
            animation: avm-lab-shimmer 2.4s ease-in-out infinite;
            pointer-events: none;
        }

        .avm-lab-skeleton {
            min-height: 0.7rem;
            border-radius: 999px;
            background: var(--avm-neutral-bg);
        }

        .avm-lab-live-dot {
            display: inline-block;
            width: 0.42rem;
            height: 0.42rem;
            border-radius: 999px;
            background: var(--avm-positive);
            box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.28);
            animation: avm-lab-highlight 1.8s ease-out infinite;
            margin-right: 0.38rem;
            vertical-align: 0.08rem;
        }

        @media (prefers-reduced-motion: reduce) {
            *,
            *::before,
            *::after {
                animation-duration: 1ms !important;
                animation-iteration-count: 1 !important;
                scroll-behavior: auto !important;
                transition-duration: 1ms !important;
            }
        }
    """


def _lab_density_css() -> str:
    """Return Product Lab density rules for calmer insight presentation."""
    return """
        :root {
            --avm-density-pad: 0.72rem;
            --avm-density-gap: 0.48rem;
            --avm-quiet-border: rgba(148, 163, 184, 0.1);
        }

        .avm-card {
            padding: var(--avm-density-pad);
            margin: 0.28rem 0 0.55rem;
        }

        .avm-metric-card {
            box-shadow: none;
        }

        .avm-metric-card__label,
        .avm-premium-card__status {
            font-size: 0.7rem;
            opacity: 0.9;
        }

        .avm-metric-card__value {
            font-size: 1.12rem;
            line-height: 1.12;
        }

        .avm-metric-card__caption,
        .avm-empty-state__body,
        .avm-premium-card__description {
            font-size: 0.82rem;
        }

        .avm-badge {
            padding: 0.18rem 0.48rem;
            font-size: 0.72rem;
        }

        .avm-lab-primary-insight {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            background: linear-gradient(180deg, var(--avm-surface), var(--avm-surface-alt));
            box-shadow: var(--avm-shadow);
            padding: 0.9rem;
            margin: 0.42rem 0 0.7rem;
        }

        .avm-lab-primary-insight__label,
        .avm-lab-quiet-label {
            color: var(--avm-muted);
            font-size: 0.72rem;
            font-weight: 760;
            text-transform: uppercase;
        }

        .avm-lab-primary-insight__title {
            color: var(--avm-text);
            font-size: 1.08rem;
            font-weight: 820;
            line-height: 1.2;
            margin-top: 0.2rem;
        }

        .avm-lab-primary-insight__body {
            color: var(--avm-muted);
            font-size: 0.9rem;
            margin-top: 0.3rem;
        }

        .avm-lab-stat-cluster {
            display: flex;
            flex-wrap: wrap;
            gap: 0.42rem;
            margin: 0.35rem 0 0.72rem;
        }

        .avm-lab-stat {
            border: 1px solid var(--avm-quiet-border);
            border-radius: 999px;
            background: var(--avm-chip-bg);
            color: var(--avm-muted);
            display: inline-flex;
            gap: 0.35rem;
            align-items: center;
            padding: 0.26rem 0.58rem;
            font-size: 0.8rem;
            white-space: nowrap;
        }

        .avm-lab-stat strong {
            color: var(--avm-text);
            font-weight: 780;
        }

        .avm-lab-insight-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.75rem;
            align-items: start;
            border-top: 1px solid var(--avm-quiet-border);
            padding: 0.55rem 0;
        }

        .avm-lab-insight-row:first-child {
            border-top: 0;
        }

        .avm-lab-insight-row strong {
            color: var(--avm-text);
            font-size: 0.92rem;
        }

        .avm-lab-insight-row p {
            color: var(--avm-muted);
            font-size: 0.84rem;
            margin: 0.14rem 0 0;
        }

        .avm-lab-evidence-group {
            border: 1px solid var(--avm-quiet-border);
            border-radius: 10px;
            background: rgba(148, 163, 184, 0.045);
            padding: 0.3rem 0.75rem;
            margin: 0.4rem 0 0.7rem;
        }

        .avm-lab-quiet-list {
            color: var(--avm-muted);
            display: flex;
            flex-wrap: wrap;
            gap: 0.32rem 0.65rem;
            font-size: 0.84rem;
            margin-top: 0.34rem;
        }

        .avm-lab-quiet-list span::before {
            content: "";
            display: inline-block;
            width: 0.32rem;
            height: 0.32rem;
            border-radius: 50%;
            background: var(--avm-premium);
            margin-right: 0.34rem;
            vertical-align: 0.08rem;
        }

        div[data-testid="stExpander"] details {
            box-shadow: none;
        }

        div[data-testid="stExpander"] summary {
            font-size: 0.92rem;
        }

        .avm-property-panel,
        .avm-property-alert,
        .avm-property-comparable,
        .avm-lab-feed-card,
        .avm-lab-market-row,
        .avm-lab-portfolio-pulse {
            box-shadow: none;
        }

        div[data-testid="stRadio"] {
            border: 1px solid var(--avm-quiet-border);
            border-radius: 999px;
            background: var(--avm-chip-bg);
            padding: 0.18rem;
        }

        div[data-testid="stRadio"] label {
            font-size: 0.82rem;
        }

        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"],
        div[data-testid="stNumberInput"],
        div[data-testid="stTextInput"],
        div[data-testid="stTextArea"],
        div[data-testid="stSlider"],
        div[data-testid="stCheckbox"] {
            margin-bottom: 0.28rem;
        }

        div[data-baseweb="select"] > div,
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        textarea {
            border-radius: 10px;
            min-height: 2.35rem;
        }

        div[data-testid="stCheckbox"] label {
            border: 1px solid var(--avm-quiet-border);
            border-radius: 999px;
            background: var(--avm-chip-bg);
            padding: 0.24rem 0.62rem;
        }

        div[data-testid="stSlider"] [data-baseweb="slider"] {
            padding-top: 0.2rem;
            padding-bottom: 0.2rem;
        }

        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            box-shadow: none;
        }

        .avm-lab-control-shell {
            border: 1px solid var(--avm-quiet-border);
            border-radius: 10px;
            background: rgba(148, 163, 184, 0.045);
            padding: 0.68rem;
            margin: 0.42rem 0 0.65rem;
        }

        .avm-lab-control-shell__title {
            color: var(--avm-text);
            font-size: 0.9rem;
            font-weight: 760;
            margin-bottom: 0.35rem;
        }

        .avm-evidence-row,
        .avm-evidence-timeline-item {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.72rem;
            align-items: start;
            border-top: 1px solid var(--avm-quiet-border);
            padding: 0.58rem 0;
        }

        .avm-evidence-row:first-child,
        .avm-evidence-timeline-item:first-child {
            border-top: 0;
        }

        .avm-evidence-row--high {
            border: 1px solid var(--avm-quiet-border);
            border-radius: 10px;
            background: rgba(148, 163, 184, 0.045);
            padding: 0.75rem;
            margin: 0.35rem 0 0.55rem;
        }

        .avm-evidence-row strong,
        .avm-evidence-timeline-item strong {
            color: var(--avm-text);
            font-size: 0.92rem;
            font-weight: 780;
        }

        .avm-evidence-row p,
        .avm-evidence-timeline-item p,
        .avm-evidence-row small,
        .avm-evidence-timeline-item small {
            color: var(--avm-muted);
            font-size: 0.83rem;
            margin: 0.14rem 0 0;
        }

        .avm-evidence-timeline-item {
            grid-template-columns: 5.8rem minmax(0, 1fr) auto;
        }

        .avm-evidence-timeline-item time {
            color: var(--avm-muted);
            font-size: 0.78rem;
            font-weight: 650;
        }

        .avm-evidence-chip,
        .avm-evidence-stat {
            border: 1px solid var(--avm-quiet-border);
            border-radius: 999px;
            background: var(--avm-chip-bg);
        }

        .avm-evidence-chip {
            color: var(--avm-neutral);
            display: inline-flex;
            align-items: center;
            padding: 0.16rem 0.46rem;
            font-size: 0.72rem;
            font-weight: 680;
            white-space: nowrap;
        }

        .avm-evidence-chip--positive { color: var(--avm-positive); background: var(--avm-positive-bg); }
        .avm-evidence-chip--negative { color: var(--avm-negative); background: var(--avm-negative-bg); }
        .avm-evidence-chip--warning { color: var(--avm-warning); background: var(--avm-warning-bg); }
        .avm-evidence-chip--premium { color: var(--avm-premium); background: var(--avm-premium-bg); }

        .avm-evidence-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.28rem;
            margin-top: 0.34rem;
        }

        .avm-evidence-stat-cluster {
            display: flex;
            flex-wrap: wrap;
            gap: 0.42rem;
            margin: 0.35rem 0 0.65rem;
        }

        .avm-evidence-stat {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.26rem 0.4rem 0.26rem 0.58rem;
        }

        .avm-evidence-stat span {
            color: var(--avm-muted);
            font-size: 0.76rem;
        }

        .avm-evidence-stat strong {
            color: var(--avm-text);
            font-size: 0.86rem;
            font-weight: 780;
        }

        .avm-evidence-metadata {
            color: var(--avm-muted);
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem 0.75rem;
            font-size: 0.8rem;
            padding: 0.35rem 0;
        }

        .avm-evidence-metadata strong {
            color: var(--avm-text);
            font-weight: 720;
        }
    """


def _lab_hierarchy_css() -> str:
    """Return Product Lab visual hierarchy rules."""
    return """
        :root {
            --avm-focus-ring: rgba(87, 199, 255, 0.16);
            --avm-primary-surface: linear-gradient(135deg, var(--avm-surface) 0%, var(--avm-surface-alt) 100%);
            --avm-secondary-surface: rgba(148, 163, 184, 0.045);
            --avm-tertiary-surface: transparent;
        }

        .avm-section-header {
            margin: 0.2rem 0 0.75rem;
        }

        .avm-section-header h1 {
            font-size: 1.42rem;
            line-height: 1.12;
            font-weight: 820;
        }

        .avm-section-header p {
            max-width: 760px;
            font-size: 0.9rem;
        }

        h2,
        .stMarkdown h2 {
            font-size: 1.05rem;
            font-weight: 760;
            margin-top: 0.8rem;
        }

        h3,
        .stMarkdown h3 {
            font-size: 0.96rem;
            font-weight: 740;
        }

        .avm-lab-home-hero,
        .avm-property-hero,
        .avm-lab-primary-insight {
            border-color: var(--avm-border-strong, var(--avm-border));
            background: var(--avm-primary-surface);
            box-shadow: var(--avm-shadow);
        }

        .avm-lab-home-hero h1,
        .avm-property-hero h1,
        .avm-lab-primary-insight__title {
            letter-spacing: 0;
            color: var(--avm-text);
        }

        .avm-lab-home-hero h1 {
            font-size: 1.72rem;
            max-width: 820px;
        }

        .avm-property-hero h1 {
            font-size: 1.82rem;
            max-width: 920px;
        }

        .avm-lab-primary-insight__title {
            font-size: 1.18rem;
        }

        .avm-lab-home-side,
        .avm-property-hero__price {
            border-color: rgba(154, 167, 255, 0.22);
            background: rgba(154, 167, 255, 0.08);
        }

        .avm-lab-feed-card,
        .avm-property-panel,
        .avm-property-comparable,
        .avm-property-alert,
        .avm-evidence-row--high,
        .avm-lab-evidence-group,
        .avm-decision-compact-card {
            background: var(--avm-secondary-surface);
            border-color: var(--avm-quiet-border);
        }

        .avm-card:not(.avm-metric-card):not(.avm-premium-card),
        .avm-lab-feed-card,
        .avm-property-panel,
        .avm-property-comparable,
        .avm-property-alert,
        .avm-decision-compact-card {
            box-shadow: none;
        }

        .avm-lab-section-label {
            margin: 1.05rem 0 0.34rem;
            padding-top: 0.15rem;
        }

        .avm-lab-section-label h2 {
            font-size: 0.96rem;
            font-weight: 760;
            color: var(--avm-text);
        }

        .avm-lab-section-label p,
        .avm-evidence-metadata,
        .avm-property-mini-stack span,
        .avm-property-price-row span,
        .avm-lab-insight-row p,
        .avm-evidence-row p,
        .avm-evidence-timeline-item p {
            color: var(--avm-muted);
        }

        .avm-lab-feed-title,
        .avm-property-panel h3,
        .avm-evidence-row strong,
        .avm-lab-insight-row strong,
        .avm-decision-compact-card strong {
            font-weight: 740;
        }

        .avm-lab-feed-card--compact,
        .avm-evidence-row,
        .avm-lab-insight-row {
            padding-top: 0.44rem;
            padding-bottom: 0.44rem;
        }

        .avm-evidence-row:not(.avm-evidence-row--high),
        .avm-lab-insight-row {
            background: var(--avm-tertiary-surface);
        }

        .avm-badge,
        .avm-evidence-chip {
            opacity: 0.92;
        }

        .avm-badge--premium,
        .avm-evidence-chip--premium,
        .avm-badge--positive,
        .avm-evidence-chip--positive {
            opacity: 1;
        }

        .stButton button {
            font-weight: 690;
            min-height: 2.15rem;
        }

        .stButton button[kind="primary"],
        button[kind="primary"] {
            background: linear-gradient(180deg, rgba(87, 199, 255, 0.92), rgba(79, 70, 229, 0.88));
            border-color: rgba(87, 199, 255, 0.34);
            color: #ffffff;
            box-shadow: 0 12px 28px rgba(37, 99, 235, 0.2);
        }

        .stButton button:not([kind="primary"]) {
            background: var(--avm-chip-bg);
            box-shadow: none;
        }

        div[data-testid="stExpander"] details {
            background: var(--avm-secondary-surface);
            border-color: var(--avm-quiet-border);
        }

        div[data-testid="stExpander"] summary {
            color: var(--avm-muted);
            font-weight: 680;
        }

        .avm-metric-card {
            background: var(--avm-tertiary-surface);
            border-color: var(--avm-quiet-border);
        }

        .avm-metric-card__value {
            font-weight: 760;
        }

        .avm-metric-card__label {
            color: var(--avm-muted);
        }

        .avm-property-actions,
        .avm-lab-control-shell {
            background: var(--avm-secondary-surface);
            border-color: var(--avm-quiet-border);
            box-shadow: none;
        }

        .avm-property-fact {
            background: rgba(148, 163, 184, 0.04);
            border-color: var(--avm-quiet-border);
            box-shadow: none;
        }

        .avm-property-fact strong {
            font-size: 0.98rem;
        }

        .avm-property-hero__badges .avm-badge:nth-child(n+4),
        .avm-lab-home-badges .avm-badge:nth-child(n+3) {
            opacity: 0.72;
        }

        .avm-evidence-stat-cluster {
            margin-top: 0.18rem;
        }

        .avm-evidence-stat {
            background: rgba(148, 163, 184, 0.045);
        }
    """


def _dark_mode_widget_css() -> str:
    """Return dark-mode fixes for native Streamlit widgets."""
    return """
        [data-testid="stSidebar"] {
            background: var(--avm-surface-alt);
        }

        [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
        [data-testid="stSidebar"] .stCaptionContainer,
        [data-testid="stCaptionContainer"],
        [data-testid="stMarkdownContainer"] small {
            color: var(--avm-muted);
        }

        div[data-testid="stForm"] {
            border-color: var(--avm-border);
            background: rgba(15, 23, 42, 0.28);
            border-radius: 10px;
        }

        div[data-testid="stExpander"] details {
            border-color: var(--avm-border);
            background: var(--avm-surface);
        }

        div[data-testid="stExpander"] summary,
        div[data-testid="stExpander"] summary p {
            color: var(--avm-text);
        }

        .stButton button,
        .stDownloadButton button,
        a[data-testid="stLinkButton"] {
            border: 1px solid var(--avm-border);
            background: var(--avm-chip-bg);
            color: var(--avm-text);
        }

        .stButton button:hover,
        .stDownloadButton button:hover,
        a[data-testid="stLinkButton"]:hover {
            border-color: var(--avm-accent);
            color: #ffffff;
            background: var(--avm-surface-elevated);
        }

        .stButton button:disabled,
        .stDownloadButton button:disabled,
        button:disabled {
            color: var(--avm-muted);
            background: var(--avm-surface-alt);
            border-color: var(--avm-border);
            opacity: 0.72;
        }

        .stButton button[kind="primary"],
        .stDownloadButton button[kind="primary"],
        button[kind="primary"] {
            color: #ffffff;
            border-color: rgba(56, 189, 248, 0.48);
            background: linear-gradient(180deg, #2563eb, #1d4ed8);
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-baseweb="select"] > div {
            background: var(--avm-input-bg);
            color: var(--avm-text);
            border-color: var(--avm-border);
            caret-color: var(--avm-accent);
        }

        div[data-testid="stTextInput"] input::placeholder,
        div[data-testid="stNumberInput"] input::placeholder,
        div[data-testid="stTextArea"] textarea::placeholder {
            color: var(--avm-muted);
            opacity: 0.82;
        }

        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        div[data-testid="stTextArea"] textarea:focus,
        div[data-baseweb="select"] > div:focus-within {
            border-color: var(--avm-accent);
            box-shadow: 0 0 0 3px var(--avm-focus-ring);
        }

        div[data-baseweb="select"] span,
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] svg {
            color: var(--avm-text);
            fill: var(--avm-muted);
        }

        div[data-baseweb="popover"] ul,
        div[data-baseweb="popover"] div[role="listbox"],
        ul[role="listbox"],
        div[role="listbox"] {
            background: var(--avm-surface);
            border: 1px solid var(--avm-border);
            color: var(--avm-text);
        }

        div[role="option"],
        li[role="option"] {
            color: var(--avm-text);
            background: var(--avm-surface);
        }

        div[role="option"]:hover,
        li[role="option"]:hover,
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"] {
            color: #ffffff;
            background: var(--avm-surface-focus);
        }

        div[data-testid="stAlert"] {
            border: 1px solid var(--avm-border);
            background: var(--avm-surface-alt);
            color: var(--avm-text);
        }

        div[data-testid="stAlert"] p,
        div[data-testid="stAlert"] span {
            color: var(--avm-text);
        }

        div[data-testid="stMetric"] {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            background: var(--avm-surface);
            padding: 0.72rem 0.78rem;
            min-width: 0;
        }

        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] [data-testid="stMetricLabel"],
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
            color: var(--avm-muted);
        }

        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--avm-text);
        }

        div[data-testid="stTabs"] [role="tablist"] {
            border-bottom: 1px solid var(--avm-border);
        }

        div[data-testid="stTabs"] [role="tab"] {
            color: var(--avm-muted);
        }

        div[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
            color: var(--avm-text);
        }

        div[data-testid="stRadio"],
        div[data-testid="stSegmentedControl"] {
            color: var(--avm-text);
        }

        div[data-testid="stRadio"] label,
        div[data-testid="stSegmentedControl"] label,
        div[data-testid="stCheckbox"] label {
            color: var(--avm-text);
        }

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            border: 1px solid var(--avm-border);
            border-radius: 10px;
            background: var(--avm-surface);
            color: var(--avm-text);
        }

        div[data-testid="stTable"] table {
            color: var(--avm-text);
        }

        div[data-testid="stTable"] thead th {
            background: var(--avm-surface-alt);
            color: var(--avm-text);
            border-color: var(--avm-border);
        }

        div[data-testid="stTable"] tbody td {
            background: var(--avm-surface);
            color: var(--avm-text);
            border-color: var(--avm-border);
        }
    """


def _resilient_layout_css() -> str:
    """Return theme-safe spacing and wrapping fixes for compact UI areas."""
    return """
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stSidebar"],
        div[data-testid="column"] {
            min-width: 0;
        }

        [data-testid="stSidebar"],
        [data-testid="stAppViewContainer"] {
            overflow-x: hidden;
        }

        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stCaptionContainer"],
        h1, h2, h3, h4, h5, h6, p, label {
            overflow-wrap: anywhere;
            word-break: normal;
        }

        .avm-card,
        .avm-empty-state,
        .avm-home-hero,
        .avm-app-shell,
        .avm-lab-nav-panel,
        .avm-lab-primary-insight,
        .avm-property-hero,
        .avm-property-panel,
        .avm-property-alert,
        .avm-property-comparable,
        .avm-valuation-quality,
        .avm-valuation-band,
        .avm-valuation-confidence,
        .avm-comparable-row,
        div[data-testid="stMetric"] {
            min-width: 0;
            overflow-wrap: anywhere;
        }

        .avm-app-shell,
        .avm-lab-nav-row,
        .avm-valuation-band__header,
        .avm-valuation-band__labels,
        .avm-comparable-row,
        .avm-property-mini-stack div,
        .avm-property-price-row {
            flex-wrap: wrap;
        }

        .avm-user-pill,
        .avm-badge,
        .avm-lab-nav-badge,
        .avm-lab-current-indicator,
        .avm-hero-benefits span,
        .avm-focus-bar__badge,
        .avm-lab-stat,
        .avm-evidence-chip,
        .avm-evidence-stat {
            max-width: 100%;
            min-width: 0;
            line-height: 1.2;
            white-space: normal;
            overflow-wrap: anywhere;
        }

        .avm-user-pill {
            text-align: right;
        }

        .avm-focus-bar__title {
            overflow: visible;
            text-overflow: clip;
            white-space: normal;
        }

        .stButton,
        .stDownloadButton,
        div[data-testid="stLinkButton"] {
            min-width: 0;
        }

        .stButton button,
        .stDownloadButton button,
        a[data-testid="stLinkButton"] {
            width: 100%;
            min-width: 0;
            max-width: 100%;
            justify-content: center;
            line-height: 1.18;
            padding-left: 0.72rem;
            padding-right: 0.72rem;
            text-align: center;
            white-space: normal;
            overflow-wrap: anywhere;
        }

        div[data-testid="stRadio"] [role="radiogroup"],
        div[data-testid="stSegmentedControl"] [role="radiogroup"],
        div[data-testid="stSegmentedControl"] > div {
            flex-wrap: wrap;
            gap: 0.35rem;
        }

        div[data-testid="stRadio"] label,
        div[data-testid="stSegmentedControl"] button,
        div[data-testid="stCheckbox"] label {
            min-width: 0;
            white-space: normal;
            overflow-wrap: anywhere;
        }

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            max-width: 100%;
            overflow-x: auto;
        }

        div[data-testid="stTable"] table {
            min-width: 100%;
        }

        .avm-admin-user-row {
            border: 1px solid var(--avm-border);
            border-radius: 8px;
            background: var(--avm-surface);
            padding: 0.6rem 0.65rem;
            margin: 0.45rem 0 0.35rem;
        }

        .avm-admin-user-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.45rem;
            flex-wrap: wrap;
        }

        .avm-admin-user-email {
            min-width: 0;
            color: var(--avm-text);
            font-size: 0.86rem;
            font-weight: 720;
            line-height: 1.2;
            overflow-wrap: anywhere;
        }

        .avm-admin-user-meta {
            color: var(--avm-muted);
            font-size: 0.76rem;
            margin-top: 0.28rem;
        }

        .avm-admin-user-status {
            border: 1px solid var(--avm-border);
            border-radius: 999px;
            padding: 0.12rem 0.42rem;
            font-size: 0.68rem;
            font-weight: 720;
            line-height: 1.15;
        }

        .avm-admin-user-status--active {
            color: var(--avm-positive);
            background: var(--avm-positive-bg);
            border-color: color-mix(in srgb, var(--avm-positive) 32%, var(--avm-border));
        }

        .avm-admin-user-status--inactive {
            color: var(--avm-muted);
            background: var(--avm-neutral-bg);
        }

        @media (max-width: 820px) {
            .avm-app-shell {
                align-items: flex-start;
            }

            .avm-user-pill {
                text-align: left;
            }

            .avm-lab-insight-row,
            .avm-evidence-row,
            .avm-evidence-timeline-item {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 640px) {
            div[data-testid="stRadio"],
            div[data-testid="stCheckbox"] label,
            .avm-lab-stat,
            .avm-evidence-chip,
            .avm-evidence-stat {
                border-radius: 8px;
            }
        }
    """


def inject_theme() -> None:
    """Inject AVM visual tokens and component styles for the selected theme."""
    mode = get_color_mode()
    lab_mode = st.session_state.get(LAB_DEMO_MODE_KEY, False)
    dark_mode_widget_css = _dark_mode_widget_css() if mode == DARK_MODE else ""
    lab_dark_css = (
        _lab_dark_theme_css()
        if mode == DARK_MODE and lab_mode
        else ""
    )
    lab_motion_css = _lab_motion_css() if lab_mode else ""
    lab_density_css = _lab_density_css() if lab_mode else ""
    lab_hierarchy_css = _lab_hierarchy_css() if lab_mode else ""
    resilient_layout_css = _resilient_layout_css()
    st.markdown(
        f"""
        <style>
        :root {{
            color-scheme: {mode};
            --avm-bg: {"#0f172a" if mode == DARK_MODE else "#f7f8fa"};
            --avm-surface: {"#111827" if mode == DARK_MODE else "#ffffff"};
            --avm-surface-alt: {"#1f2937" if mode == DARK_MODE else "#fbfcfd"};
            --avm-surface-muted: {"#182233" if mode == DARK_MODE else "#f2f4f7"};
            --avm-surface-elevated: {"#162033" if mode == DARK_MODE else "#ffffff"};
            --avm-surface-focus: {"#26354f" if mode == DARK_MODE else "#eff6ff"};
            --avm-border: {"#334155" if mode == DARK_MODE else "#e6e9ef"};
            --avm-text: {"#f8fafc" if mode == DARK_MODE else "#111827"};
            --avm-muted: {"#cbd5e1" if mode == DARK_MODE else "#667085"};
            --avm-shadow: {"0 10px 28px rgba(0, 0, 0, 0.32)" if mode == DARK_MODE else "0 8px 24px rgba(15, 23, 42, 0.06)"};
            --avm-neutral: {"#d1d5db" if mode == DARK_MODE else "#475467"};
            --avm-positive: {"#4ade80" if mode == DARK_MODE else "#067647"};
            --avm-negative: {"#f87171" if mode == DARK_MODE else "#b42318"};
            --avm-warning: {"#fbbf24" if mode == DARK_MODE else "#b54708"};
            --avm-premium: {"#a5b4fc" if mode == DARK_MODE else "#4f46e5"};
            --avm-accent: {"#38bdf8" if mode == DARK_MODE else "#2563eb"};
            --avm-neutral-bg: {"#1f2937" if mode == DARK_MODE else "#f2f4f7"};
            --avm-positive-bg: {"#052e1a" if mode == DARK_MODE else "#ecfdf3"};
            --avm-negative-bg: {"#3b0a0a" if mode == DARK_MODE else "#fef3f2"};
            --avm-warning-bg: {"#3b2a06" if mode == DARK_MODE else "#fffaeb"};
            --avm-premium-bg: {"#25224a" if mode == DARK_MODE else "#eef2ff"};
            --avm-hero-bg: {"linear-gradient(135deg, #111827 0%, #172033 58%, #25224a 100%)" if mode == DARK_MODE else "linear-gradient(135deg, #ffffff 0%, #f8fafc 58%, #eef2ff 100%)"};
            --avm-chip-bg: {"rgba(31, 41, 55, 0.86)" if mode == DARK_MODE else "rgba(255, 255, 255, 0.82)"};
            --avm-input-bg: {"#0f172a" if mode == DARK_MODE else "#ffffff"};
            --avm-focus-ring: {"rgba(56, 189, 248, 0.16)" if mode == DARK_MODE else "rgba(37, 99, 235, 0.14)"};
        }}

        html, body, [data-testid="stAppViewContainer"] {{
            background: var(--avm-bg);
            color: var(--avm-text);
        }}

        [data-testid="stHeader"] {{
            background: transparent;
        }}

        .stApp {{
            background: var(--avm-bg);
            color: var(--avm-text);
        }}

        h1, h2, h3, h4, h5, h6, p, label, span {{
            letter-spacing: 0;
        }}

        section[data-testid="stSidebar"] {{
            background: var(--avm-surface-alt);
            border-right: 1px solid var(--avm-border);
        }}

        [data-testid="stSidebar"] * {{
            color: var(--avm-text);
        }}

        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-baseweb="select"] > div,
        textarea {{
            background: var(--avm-surface);
            color: var(--avm-text);
            border-color: var(--avm-border);
        }}

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {{
            color: var(--avm-text);
        }}

        .avm-section-header {{
            margin: 0.25rem 0 1.25rem 0;
        }}

        .avm-section-header h1,
        .avm-section-header h2 {{
            margin: 0;
            letter-spacing: 0;
            color: var(--avm-text);
        }}

        .avm-section-header p {{
            margin: 0.35rem 0 0 0;
            color: var(--avm-muted);
            font-size: 0.98rem;
        }}

        .avm-card {{
            border: 1px solid var(--avm-border);
            border-radius: 8px;
            background: var(--avm-surface);
            box-shadow: var(--avm-shadow);
            padding: 1rem;
            margin: 0.4rem 0 0.85rem 0;
        }}

        .avm-metric-card__label,
        .avm-premium-card__status {{
            color: var(--avm-muted);
            font-size: 0.78rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0;
        }}

        .avm-metric-card__value {{
            color: var(--avm-text);
            font-size: 1.45rem;
            font-weight: 750;
            margin-top: 0.25rem;
        }}

        .avm-metric-card__caption,
        .avm-empty-state__body,
        .avm-premium-card__description {{
            color: var(--avm-muted);
            font-size: 0.92rem;
            margin-top: 0.35rem;
        }}

        .avm-metric-card__delta {{
            display: inline-block;
            margin-top: 0.45rem;
            font-size: 0.85rem;
            font-weight: 650;
        }}

        .avm-badge {{
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.22rem 0.58rem;
            font-size: 0.78rem;
            font-weight: 650;
            border: 1px solid transparent;
        }}

        .avm-badge--neutral,
        .avm-metric-card--neutral .avm-metric-card__delta {{
            color: var(--avm-neutral);
        }}

        .avm-badge--positive,
        .avm-metric-card--positive .avm-metric-card__delta {{
            color: var(--avm-positive);
        }}

        .avm-badge--negative,
        .avm-metric-card--negative .avm-metric-card__delta {{
            color: var(--avm-negative);
        }}

        .avm-badge--warning,
        .avm-metric-card--warning .avm-metric-card__delta {{
            color: var(--avm-warning);
        }}

        .avm-badge--premium,
        .avm-metric-card--premium .avm-metric-card__delta {{
            color: var(--avm-premium);
        }}

        .avm-badge--neutral {{ background: var(--avm-neutral-bg); }}
        .avm-badge--positive {{ background: var(--avm-positive-bg); }}
        .avm-badge--negative {{ background: var(--avm-negative-bg); }}
        .avm-badge--warning {{ background: var(--avm-warning-bg); }}
        .avm-badge--premium {{ background: var(--avm-premium-bg); }}

        .avm-empty-state {{
            border: 1px dashed var(--avm-border);
            border-radius: 8px;
            background: var(--avm-surface-alt);
            padding: 1.15rem;
            margin: 0.8rem 0;
        }}

        .avm-empty-state__title,
        .avm-premium-card__title {{
            color: var(--avm-text);
            font-weight: 750;
            font-size: 1rem;
        }}

        .avm-premium-card {{
            border-left: 4px solid var(--avm-premium);
        }}

        .avm-home-hero {{
            border: 1px solid var(--avm-border);
            border-radius: 8px;
            background: var(--avm-hero-bg);
            box-shadow: var(--avm-shadow);
            padding: 1.35rem;
            margin: 0.55rem 0 1rem 0;
        }}

        .avm-hero-kicker {{
            color: var(--avm-premium);
            font-size: 0.78rem;
            font-weight: 750;
            text-transform: uppercase;
            letter-spacing: 0;
        }}

        .avm-hero-title {{
            color: var(--avm-text);
            font-size: 1.75rem;
            font-weight: 850;
            letter-spacing: 0;
            line-height: 1.15;
            max-width: 820px;
            margin-top: 0.35rem;
        }}

        .avm-hero-copy {{
            color: var(--avm-muted);
            font-size: 1rem;
            max-width: 740px;
            margin-top: 0.55rem;
        }}

        .avm-hero-benefits {{
            display: flex;
            gap: 0.45rem;
            flex-wrap: wrap;
            margin-top: 0.9rem;
        }}

        .avm-hero-benefits span {{
            border: 1px solid var(--avm-border);
            border-radius: 999px;
            background: var(--avm-chip-bg);
            color: var(--avm-neutral);
            font-size: 0.82rem;
            font-weight: 650;
            padding: 0.32rem 0.68rem;
        }}

        .avm-quick-card {{
            min-height: 112px;
        }}

        {dark_mode_widget_css}
        {lab_dark_css}
        {lab_motion_css}
        {lab_density_css}
        {lab_hierarchy_css}
        {resilient_layout_css}
        </style>
        """,
        unsafe_allow_html=True,
    )
