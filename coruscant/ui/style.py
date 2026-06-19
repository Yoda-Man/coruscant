"""
coruscant.ui.style
~~~~~~~~~~~~~~~~~~~
Central design system for Coruscant's custom-styled surfaces.

This module is the single source of truth for the dark "navy" palette used by
the application's dialogs, the Script Manager, and the Schema Browser header.
Instead of hand-typing hex codes and spacing values across a dozen widgets,
every styled component pulls colours, spacing, and ready-made stylesheets from
here. Change a token once and it propagates everywhere.

Contents
--------
- **Colour tokens**   — semantic names (``BG_BASE``, ``TEXT``, ``ACCENT`` …).
- **Spacing/radius**  — a small numeric scale (``SPACE_SM`` … ``SPACE_LG``).
- **Stylesheet builders** — functions that assemble Qt stylesheet strings from
  the tokens (``dialog_stylesheet``, ``header_button_style``,
  ``script_manager_stylesheet``).

This module is pure Python (no Qt imports) so it stays trivially testable and
importable from anywhere without side effects.

Author: Marwa Trust Mutemasango
"""

from __future__ import annotations

# ════════════════════════════════════════════════════════════════════════ #
#  Colour tokens                                                             #
# ════════════════════════════════════════════════════════════════════════ #

# Backgrounds — from deepest to most-raised surface.
BG_BASE        = "#0e0e1a"   # dialog / window background
BG_HEADER      = "#0d0d1a"   # accent header bars (slightly deeper than base)
BG_SURFACE     = "#1a1a2e"   # raised cards, header containers, panels
BG_PANEL       = "#12121e"   # text browsers, tables, code panes
BG_ROW_ALT     = "#1a1a2a"   # alternating table rows
BG_INPUT       = "#1e1e2e"   # line edits, header sections, buttons (resting)
BG_INPUT_FOCUS = "#20203a"   # input background while focused
BG_ROW_HOVER   = "#1e2a3a"   # table row hover

# Borders.
BORDER         = "#2e2e4e"
BORDER_SUBTLE  = "#2a2a3e"   # table gridlines
BORDER_LIGHT   = "#3c3c52"
BORDER_HOVER   = "#555570"
BORDER_STRONG  = "#7070a0"

# Text.
TEXT           = "#cdd6f4"
TEXT_MUTED     = "#a6adc8"
TEXT_DIM       = "#8888aa"
TEXT_FAINT     = "#6c7086"
TEXT_BUTTON    = "#dddddd"
TEXT_DISABLED  = "#444444"
WHITE          = "#ffffff"

# Accent / brand.
ACCENT         = "#4361ee"   # primary accent (focus, pressed, progress)
ACCENT_BLUE    = "#89b4fa"   # headings
ACCENT_BLUE_LT = "#90CAF9"   # links, accent button text
SELECTION      = "#094771"   # selected-row background

# Neutral dialog button gradient stops.
BTN_TOP        = "#3c3c52"
BTN_BOT        = "#2e2e42"
BTN_HOVER_TOP  = "#4a4a62"
BTN_HOVER_BOT  = "#3c3c52"
BTN_DISABLED   = "#1c1c2e"
BTN_DIS_BORDER = "#333333"

# Semantic action colours (Script Manager upload / clear).
BLUE           = "#1976D2"
BLUE_DARK      = "#1565C0"
BLUE_LIGHT     = "#1E88E5"
RED            = "#B71C1C"
RED_DARK       = "#7F0000"
RED_DARKER     = "#6A0000"

# ════════════════════════════════════════════════════════════════════════ #
#  Spacing & radius scale                                                    #
# ════════════════════════════════════════════════════════════════════════ #

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16

RADIUS_SM = 3
RADIUS    = 4
RADIUS_MD = 5
RADIUS_LG = 6
RADIUS_XL = 8

# Standard control heights.
HEIGHT_HEADER_BTN = 22   # compact buttons in panel headers


# ════════════════════════════════════════════════════════════════════════ #
#  Internal helpers                                                          #
# ════════════════════════════════════════════════════════════════════════ #

def _neutral_button_css(padding: str) -> str:
    """The shared neutral (grey-blue gradient) push-button look.

    *padding* is the CSS padding value, e.g. ``"7px 28px"`` — the only thing
    that varies between the dialog footer buttons and the Script Manager
    buttons.
    """
    return (
        f"QPushButton {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"      stop:0 {BTN_TOP}, stop:1 {BTN_BOT});"
        f"  border: 1px solid {BORDER_HOVER};"
        f"  border-radius: {RADIUS_MD}px;"
        f"  padding: {padding};"
        f"  color: {TEXT_BUTTON};"
        f"  font-size: 12px; font-weight: 600; min-width: 80px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"      stop:0 {BTN_HOVER_TOP}, stop:1 {BTN_HOVER_BOT});"
        f"  border-color: {BORDER_STRONG}; color: {WHITE};"
        f"}}"
        f"QPushButton:pressed {{ background: {ACCENT}; border-color: {ACCENT}; }}"
    )


# ════════════════════════════════════════════════════════════════════════ #
#  Stylesheet builders                                                       #
# ════════════════════════════════════════════════════════════════════════ #

def dialog_stylesheet() -> str:
    """Shared stylesheet for the simple content dialogs (Guide, About).

    Provides a styled ``QDialog`` background, a ``QTextBrowser`` content area,
    neutral footer buttons, and the ``#title_label`` / ``#subtitle_label``
    header label styles used by both dialogs' logo headers.
    """
    return (
        f"QDialog {{ background: {BG_BASE}; }}"
        f"QTextBrowser {{"
        f"  background: {BG_PANEL}; color: {TEXT};"
        f"  border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px;"
        f"  padding: {SPACE_MD}px; font-size: 12px;"
        f"}}"
        + _neutral_button_css("7px 28px")
        + f"QLabel#title_label {{ color: {TEXT}; font-size: 18px; font-weight: bold; }}"
        f"QLabel#subtitle_label {{ color: {TEXT_DIM}; font-size: 11px; }}"
    )


def header_button_style() -> str:
    """Compact geometry for the panel-header buttons.

    Applied to every Schema Browser header button (Refresh, Scripts,
    Settings, Guide, About) so they read as one coherent control group.

    Only sizing is specified here — colours and the hover / pressed / checked
    / disabled states are inherited from the active application theme (see
    ``coruscant.utils.themes``). This keeps the buttons correct in BOTH light
    and dark mode and lets them update automatically on a runtime theme
    switch, instead of baking in a single palette.
    """
    return f"QPushButton {{ font-size: 10px; padding: 0 {SPACE_SM}px; }}"


def script_manager_stylesheet() -> str:
    """Full stylesheet for the Support Script Manager dialog.

    Rebuilt from the shared tokens so the Script Manager stays visually in
    lock-step with the rest of the dark theme.
    """
    return (
        f"QDialog {{ background: {BG_BASE}; }}"
        f"QLabel {{ color: {TEXT}; font-size: 12px; }}"
        f"QLabel#stats  {{ color: {TEXT_MUTED}; font-size: 11px; }}"
        f"QLabel#header {{ color: {ACCENT_BLUE}; font-size: 14px; font-weight: bold; }}"
        f"QLineEdit {{"
        f"  background: {BG_INPUT}; border: 1px solid {BORDER_LIGHT};"
        f"  border-radius: {RADIUS}px; padding: 6px 10px; color: {TEXT};"
        f"  font-size: 12px; selection-background-color: {ACCENT};"
        f"}}"
        f"QLineEdit:focus {{ border-color: {ACCENT}; background: {BG_INPUT_FOCUS}; }}"
        f"QLineEdit:hover {{ border-color: {BORDER_HOVER}; }}"
        f"QTableWidget {{"
        f"  background: {BG_PANEL}; alternate-background-color: {BG_ROW_ALT};"
        f"  border: 1px solid {BORDER}; gridline-color: {BORDER_SUBTLE};"
        f"  color: {TEXT}; selection-background-color: {SELECTION};"
        f"  selection-color: {WHITE}; font-size: 12px; outline: 0;"
        f"}}"
        f"QTableWidget::item {{ padding: 5px 8px; }}"
        f"QTableWidget::item:hover {{ background: {BG_ROW_HOVER}; }}"
        f"QHeaderView::section {{"
        f"  background: {BG_INPUT}; color: {TEXT_MUTED};"
        f"  border: 1px solid {BORDER}; padding: 6px 8px;"
        f"  font-size: 11px; font-weight: 700;"
        f"}}"
        + _neutral_button_css("7px 18px")
        + f"QPushButton:disabled {{"
        f"  background: {BTN_DISABLED}; color: {TEXT_DISABLED}; border-color: {BTN_DIS_BORDER};"
        f"}}"
        f"QPushButton#upload_btn {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"      stop:0 {BLUE}, stop:1 {BLUE_DARK});"
        f"  border-color: {BLUE_LIGHT}; font-weight: 700;"
        f"}}"
        f"QPushButton#upload_btn:hover {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"      stop:0 {BLUE_LIGHT}, stop:1 {BLUE});"
        f"}}"
        f"QPushButton#clear_btn {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"      stop:0 {RED_DARK}, stop:1 {RED_DARKER});"
        f"  border-color: {RED};"
        f"}}"
        f"QPushButton#clear_btn:hover {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"      stop:0 {RED}, stop:1 {RED_DARK});"
        f"}}"
        f"QProgressBar {{"
        f"  background: {BG_INPUT}; border: 1px solid {BORDER_LIGHT};"
        f"  border-radius: {RADIUS}px; text-align: center;"
        f"  color: {TEXT}; font-size: 11px;"
        f"}}"
        f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: {RADIUS_SM}px; }}"
        f"QPlainTextEdit {{"
        f"  background: {BG_PANEL}; color: {TEXT};"
        f"  border: 1px solid {BORDER}; border-radius: {RADIUS}px;"
        f"  font-family: Courier New, monospace; font-size: 11px; padding: 6px;"
        f"}}"
        f"QFrame#divider {{ background: {BORDER}; }}"
    )
