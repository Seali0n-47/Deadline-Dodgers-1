"""
app.py — TrustFlow  |  Manufacturing Expense Intelligence Dashboard
===================================================================
Compatible with Flet 0.23.2

Reads combined_expenses.csv produced by main.py and shows:
  - KPI cards   — total spend, top category, avg severity, high-risk count
  - Bar chart   — expense amount by category
  - Severity    — horizontal priority-ranked bar chart
  - Table       — full expense breakdown sorted by severity
  - Upload      — pick files and trigger main.py pipeline

Run:
    python app.py
"""

import flet as ft
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import csv
import os
import subprocess
import sys
from collections import defaultdict
from flet.matplotlib_chart import MatplotlibChart

# ── File paths (must match main.py constants) ────────────────────────────────
COMBINED_CSV  = "combined_expenses.csv"

# ── Palette ───────────────────────────────────────────────────────────────────
BG_DARK  = "#0D1117"
BG_CARD  = "#161B22"
BG_CARD2 = "#1C2128"
ACCENT   = "#F78166"    # coral-red
ACCENT2  = "#79C0FF"    # sky-blue
ACCENT3  = "#56D364"    # green
ACCENT4  = "#E3B341"    # amber
TEXT_PRI = "#E6EDF3"
TEXT_SEC = "#8B949E"
BORDER   = "#30363D"

CATEGORY_COLORS = [
    "#F78166", "#79C0FF", "#56D364", "#E3B341",
    "#D2A8FF", "#FF7B72", "#58A6FF", "#3FB950",
]

# ── Data helpers ──────────────────────────────────────────────────────────────

def load_combined():
    rows = []
    if not os.path.exists(COMBINED_CSV):
        return rows
    with open(COMBINED_CSV, newline="") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "name":   row["Expense Name"].strip(),
                    "amount": float(row["Expense Amount"]),
                    "sev":    float(row["sevLev"]),
                })
            except (ValueError, KeyError):
                pass
    return rows


def aggregate(rows):
    amounts  = defaultdict(float)
    severity = {}
    for r in rows:
        amounts[r["name"]]  += r["amount"]
        severity[r["name"]]  = r["sev"]
    return dict(amounts), severity


# ── Chart builders ────────────────────────────────────────────────────────────

def _style_axes(ax):
    ax.set_facecolor(BG_CARD)
    ax.tick_params(colors=TEXT_SEC, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(BORDER)


def build_bar_chart(amounts):
    fig, ax = plt.subplots(figsize=(6, 3.2))
    fig.patch.set_facecolor(BG_CARD)
    _style_axes(ax)

    cats   = list(amounts.keys())
    values = [amounts[c] for c in cats]
    colors = [CATEGORY_COLORS[i % len(CATEGORY_COLORS)] for i in range(len(cats))]

    bars = ax.bar(cats, values, color=colors, width=0.55, zorder=3)
    ax.set_ylabel("Amount (Rs)", color=TEXT_SEC, fontsize=8)
    ax.set_title("Expense by Category", color=TEXT_PRI, fontsize=10, pad=10)
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels(
        [c if len(c) <= 12 else c[:11] + "..." for c in cats],
        rotation=30, ha="right", color=TEXT_SEC, fontsize=7,
    )
    ax.yaxis.grid(True, color=BORDER, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() * 1.01,
            f"Rs{val:,.0f}",
            ha="center", va="bottom", color=TEXT_PRI, fontsize=7,
        )
    fig.tight_layout()
    return MatplotlibChart(fig, expand=True)


def build_severity_chart(severity):
    sorted_sev = sorted(severity.items(), key=lambda x: x[1], reverse=True)
    cats   = [s[0] for s in sorted_sev]
    scores = [s[1] for s in sorted_sev]

    fig, ax = plt.subplots(figsize=(6, 3.2))
    fig.patch.set_facecolor(BG_CARD)
    _style_axes(ax)

    colors = [ACCENT if s >= 7 else ACCENT4 if s >= 5 else ACCENT3 for s in scores]
    bars = ax.barh(cats, scores, color=colors, height=0.55, zorder=3)
    ax.set_xlabel("Severity Score (0-10)", color=TEXT_SEC, fontsize=8)
    ax.set_title("Category Priority (Severity)", color=TEXT_PRI, fontsize=10, pad=10)
    ax.set_xlim(0, 10.5)
    ax.tick_params(axis="y", colors=TEXT_SEC, labelsize=8)
    ax.xaxis.grid(True, color=BORDER, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.invert_yaxis()
    for bar, val in zip(bars, scores):
        ax.text(val + 0.1, bar.get_y() + bar.get_height() / 2,
                f"{val}", va="center", color=TEXT_PRI, fontsize=8)

    legend_patches = [
        mpatches.Patch(color=ACCENT,  label="High  (>=7)"),
        mpatches.Patch(color=ACCENT4, label="Medium (5-7)"),
        mpatches.Patch(color=ACCENT3, label="Low  (<5)"),
    ]
    ax.legend(handles=legend_patches, loc="lower right",
              facecolor=BG_CARD2, edgecolor=BORDER,
              labelcolor=TEXT_SEC, fontsize=7)
    fig.tight_layout()
    return MatplotlibChart(fig, expand=True)


# ── UI component helpers ──────────────────────────────────────────────────────

def kpi_card(title, value, subtitle="", color=ACCENT2):
    # ── FIX: letter_spacing only valid inside TextStyle, not ft.Text directly
    return ft.Container(
        content=ft.Column(
            [
                ft.Text(title,    color=TEXT_SEC, size=11,
                        style=ft.TextStyle(weight=ft.FontWeight.W_500)),
                ft.Text(value,    color=color,    size=24,
                        weight=ft.FontWeight.BOLD),
                ft.Text(subtitle, color=TEXT_SEC, size=10)
                    if subtitle else ft.Container(height=0),
            ],
            spacing=4,
        ),
        bgcolor=BG_CARD,
        border=ft.border.all(1, BORDER),
        border_radius=12,
        padding=ft.padding.symmetric(horizontal=20, vertical=16),
        expand=True,
    )


def section_label(text):
    # ── FIX: letter_spacing moved into TextStyle
    return ft.Text(
        text,
        color=TEXT_SEC,
        size=11,
        style=ft.TextStyle(
            weight=ft.FontWeight.W_600,
            letter_spacing=1.5,
        ),
    )


def chart_shell(title, chart_widget):
    return ft.Container(
        content=ft.Column([section_label(title), chart_widget], spacing=8),
        bgcolor=BG_CARD,
        border=ft.border.all(1, BORDER),
        border_radius=12,
        padding=16,
        expand=True,
    )


def sev_color(s):
    if s >= 7:   return ACCENT
    if s >= 5:   return ACCENT4
    return ACCENT3


def build_table(rows):
    sorted_rows = sorted(rows, key=lambda r: r["sev"], reverse=True)

    return ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Category",   color=TEXT_SEC, size=11)),
            ft.DataColumn(ft.Text("Amount (Rs)", color=TEXT_SEC, size=11), numeric=True),
            ft.DataColumn(ft.Text("Severity",    color=TEXT_SEC, size=11), numeric=True),
            ft.DataColumn(ft.Text("Priority",    color=TEXT_SEC, size=11)),
        ],
        rows=[
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(r["name"],             color=TEXT_PRI, size=12)),
                ft.DataCell(ft.Text(f"Rs{r['amount']:,.2f}", color=TEXT_PRI, size=12)),
                ft.DataCell(ft.Text(str(r["sev"]),         color=sev_color(r["sev"]),
                                    size=12, weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Container(
                    content=ft.Text(
                        "HIGH" if r["sev"] >= 7 else "MED" if r["sev"] >= 5 else "LOW",
                        color=sev_color(r["sev"]),
                        size=10,
                        weight=ft.FontWeight.BOLD,
                    ),
                    bgcolor=sev_color(r["sev"]) + "22",
                    border_radius=6,
                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                )),
            ])
            for r in sorted_rows
        ],
        # ── FIX: border / border_radius / heading_row_color / data_row_color
        #         all work in 0.23.2 with these exact arg forms
        border=ft.border.all(1, BORDER),
        border_radius=12,
        heading_row_color=BG_CARD2,
        # ── FIX: data_row_color key must be lowercase string, not ControlState enum
        data_row_color={"hovered": BG_CARD2},
        column_spacing=24,
    )


# ── Main app ──────────────────────────────────────────────────────────────────

def main(page: ft.Page):
    page.title   = "TrustFlow"
    page.bgcolor = BG_DARK
    page.padding = 0
    page.scroll  = ft.ScrollMode.AUTO
    # ── FIX: page.fonts removed — custom font loading changed after 0.23;
    #         just omit it; system fonts work fine

    status_text = ft.Text("", color=TEXT_SEC, size=12)
    content_col = ft.Column(spacing=20)

    # ── Dashboard refresh ─────────────────────────────────────────────────────
    def refresh_dashboard():
        rows = load_combined()
        content_col.controls.clear()

        if not rows:
            content_col.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            # ── FIX: ft.icons.* (lowercase) for 0.23.2
                            ft.Icon(ft.icons.UPLOAD_FILE, color=TEXT_SEC, size=48),
                            ft.Text("No data yet.", color=TEXT_SEC, size=16),
                            ft.Text(
                                "Run the pipeline first, or upload files below.",
                                color=TEXT_SEC, size=12,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                    ),
                    alignment=ft.alignment.center,
                    expand=True,
                    padding=60,
                )
            )
            page.update()
            return

        amounts, severity = aggregate(rows)

        # KPI row
        total_spend   = sum(amounts.values())
        top_cat       = max(amounts, key=amounts.get)
        avg_sev       = round(sum(severity.values()) / len(severity), 2) if severity else 0
        high_risk_cnt = sum(1 for s in severity.values() if s >= 7)

        kpi_row = ft.Row(
            [
                kpi_card("TOTAL SPEND",    f"Rs{total_spend:,.0f}", "All categories",          ACCENT2),
                kpi_card("TOP CATEGORY",   top_cat,                  f"Rs{amounts[top_cat]:,.0f}", ACCENT),
                kpi_card("AVG SEVERITY",   str(avg_sev),             "Across all categories",   ACCENT4),
                kpi_card("HIGH-RISK CATS", str(high_risk_cnt),       "Severity >= 7",           ACCENT),
            ],
            spacing=12,
        )

        # Charts
        charts_row = ft.Row(
            [
                chart_shell("EXPENSE BREAKDOWN", build_bar_chart(amounts)),
                chart_shell("PRIORITY SCORING",  build_severity_chart(severity)),
            ],
            spacing=12,
            expand=True,
        )

        # Table
        agg_rows = [
            {"name": cat, "amount": amounts[cat], "sev": severity.get(cat, 0)}
            for cat in amounts
        ]
        table_shell = ft.Container(
            content=ft.Column(
                [
                    section_label("FULL BREAKDOWN"),
                    ft.Container(
                        content=build_table(agg_rows),
                        border_radius=12,
                        # ── FIX: ClipBehavior string form for 0.23.2
                        clip_behavior="antiAlias",
                    ),
                ],
                spacing=12,
            ),
            bgcolor=BG_CARD,
            border=ft.border.all(1, BORDER),
            border_radius=12,
            padding=16,
        )

        content_col.controls.extend([kpi_row, charts_row, table_shell])
        page.update()

    # ── File picker & pipeline ────────────────────────────────────────────────
    selected_files  = []
    selected_label  = ft.Text("No files selected", color=TEXT_SEC, size=12)
    upload_progress = ft.ProgressBar(visible=False, color=ACCENT,
                                      # ── FIX: bgcolor works in 0.23.2
                                      bgcolor=BORDER)

    def on_file_result(e):
        nonlocal selected_files
        if e.files:
            selected_files = [f.path for f in e.files if f.path]
            selected_label.value = "Selected: " + ", ".join(f.name for f in e.files)
        else:
            selected_files = []
            selected_label.value = "No files selected"
        page.update()

    file_picker = ft.FilePicker(on_result=on_file_result)
    page.overlay.append(file_picker)

    def run_pipeline(e):
        if not selected_files:
            status_text.value = "Please select at least one file first."
            page.update()
            return

        upload_progress.visible = True
        status_text.value = "Running pipeline..."
        page.update()

        try:
            result = subprocess.run(
                [sys.executable, "main.py"] + selected_files,
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                status_text.value = "Pipeline complete. Dashboard refreshed."
                refresh_dashboard()
            else:
                status_text.value = "Pipeline error - check terminal.\n" + result.stderr[-300:]
        except FileNotFoundError:
            status_text.value = "main.py not found in current directory."
        except subprocess.TimeoutExpired:
            status_text.value = "Pipeline timed out (>5 min)."
        except Exception as ex:
            status_text.value = str(ex)
        finally:
            upload_progress.visible = False
            page.update()

    def pick_files(extensions):
        file_picker.pick_files(allowed_extensions=extensions, allow_multiple=True)

    upload_panel = ft.Container(
        content=ft.Column(
            [
                section_label("DATA UPLOAD"),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            "PDF Invoices",
                            # ── FIX: ft.icons.* lowercase for 0.23.2
                            icon=ft.icons.PICTURE_AS_PDF,
                            on_click=lambda _: pick_files(["pdf"]),
                            style=ft.ButtonStyle(
                                bgcolor=BG_CARD2,
                                color=TEXT_PRI,
                                side=ft.BorderSide(1, BORDER),
                            ),
                        ),
                        ft.ElevatedButton(
                            "CSV Expenses",
                            icon=ft.icons.TABLE_CHART,
                            on_click=lambda _: pick_files(["csv"]),
                            style=ft.ButtonStyle(
                                bgcolor=BG_CARD2,
                                color=TEXT_PRI,
                                side=ft.BorderSide(1, BORDER),
                            ),
                        ),
                        ft.ElevatedButton(
                            "Images / Bills",
                            icon=ft.icons.IMAGE,
                            on_click=lambda _: pick_files(["png", "jpg", "jpeg"]),
                            style=ft.ButtonStyle(
                                bgcolor=BG_CARD2,
                                color=TEXT_PRI,
                                side=ft.BorderSide(1, BORDER),
                            ),
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                selected_label,
                ft.ElevatedButton(
                    "Run Analysis Pipeline",
                    on_click=run_pipeline,
                    style=ft.ButtonStyle(
                        bgcolor=ACCENT,
                        color="#FFFFFF",
                        shape=ft.RoundedRectangleBorder(radius=8),
                        padding=ft.padding.symmetric(horizontal=24, vertical=14),
                    ),
                ),
                upload_progress,
                status_text,
            ],
            spacing=12,
        ),
        bgcolor=BG_CARD,
        border=ft.border.all(1, BORDER),
        border_radius=12,
        padding=20,
    )

    # ── Header ────────────────────────────────────────────────────────────────
    header = ft.Container(
        content=ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("TrustFlow", size=28, color=TEXT_PRI,
                                weight=ft.FontWeight.BOLD),
                        ft.Text("Manufacturing Expense Intelligence",
                                size=12, color=TEXT_SEC),
                    ],
                    spacing=2,
                ),
                ft.ElevatedButton(
                    "Refresh",
                    on_click=lambda _: refresh_dashboard(),
                    style=ft.ButtonStyle(
                        bgcolor=BG_CARD2,
                        color=TEXT_PRI,
                        side=ft.BorderSide(1, BORDER),
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        bgcolor=BG_CARD,
        border=ft.border.only(bottom=ft.BorderSide(1, BORDER)),
        padding=ft.padding.symmetric(horizontal=32, vertical=18),
    )

    # ── Page layout ───────────────────────────────────────────────────────────
    page.add(
        ft.Column(
            [
                header,
                ft.Container(
                    content=ft.Column(
                        [content_col, upload_panel],
                        spacing=20,
                    ),
                    padding=ft.padding.symmetric(horizontal=32, vertical=24),
                ),
            ],
            spacing=0,
            expand=True,
        )
    )

    refresh_dashboard()


ft.app(target=main)