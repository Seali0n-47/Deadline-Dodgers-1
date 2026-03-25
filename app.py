import flet as ft
import matplotlib
matplotlib.use("Agg")  # prevent GUI thread warning

import matplotlib.pyplot as plt
import random
from flet.matplotlib_chart import MatplotlibChart


def main(page: ft.Page):
    page.title = "TrustFlow"
    page.bgcolor = "#e6e6e6"
    page.padding = 20

    text_style = ft.TextStyle(color="black")

    # -------- INITIAL DATA --------
    def generate_loss():
        current = 1.5
        loss = []
        for _ in range(20):
            current -= random.uniform(0.05, 0.15)
            current += random.uniform(-0.03, 0.03)
            loss.append(max(current, 0.1))
        return loss

    # -------- MATPLOTLIB FIGURE --------
    fig, ax = plt.subplots()
    loss = generate_loss()
    line, = ax.plot(loss)
    ax.set_title("Training Loss")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Loss")

    chart = MatplotlibChart(fig, expand=True)

    # -------- RELOAD BUTTON --------
    def reload_graph(e):
        new_loss = generate_loss()
        line.set_ydata(new_loss)
        line.set_xdata(range(len(new_loss)))
        ax.relim()
        ax.autoscale_view()
        chart.update()

    stats_panel = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Statistics", size=22, style=text_style),
                ft.ElevatedButton("Reload", on_click=reload_graph),
            ], alignment="spaceBetween"),
            chart
        ]),
        bgcolor="#cfc9c9",
        border_radius=20,
        padding=15,
        expand=True
    )

    # -------- TABLE --------
    table_panel = ft.Container(
        content=ft.Column([
            ft.Text("Initiative   Trust   Cost   Risk   Score", style=text_style),
            ft.Text("Steel Expansion   0.82   200   0.3   0.75", style=text_style),
            ft.Text("New Plant         0.61   500   0.5   0.55", style=text_style),
        ]),
        bgcolor="#cfc9c9",
        border_radius=20,
        padding=15,
        expand=True
    )

    # -------- FILE PICKER --------
    selected_file = ft.Text("No file selected", style=text_style)

    def file_result(e):
        if e.files:
            selected_file.value = f"Selected: {e.files[0].name}"
            page.update()

    file_picker = ft.FilePicker(on_result=file_result)
    page.overlay.append(file_picker)

    upload_panel = ft.Container(
        content=ft.Column([
            ft.Text("Data Upload", size=22, style=text_style),
            ft.ElevatedButton(
                "Upload PDF Invoice",
                on_click=lambda _: file_picker.pick_files(
                    allowed_extensions=["pdf"]
                )
            ),
            ft.ElevatedButton(
                "Upload CSV Expense File",
                on_click=lambda _: file_picker.pick_files(
                    allowed_extensions=["csv"]
                )
            ),
            ft.ElevatedButton(
                "Upload Handwritten Bills",
                on_click=lambda _: file_picker.pick_files(
                    allowed_extensions=["png", "jpg", "jpeg"]
                )
            ),
            selected_file
        ]),
        bgcolor="#cfc9c9",
        border_radius=20,
        padding=15,
        width=420
    )

    # -------- LAYOUT --------
    page.add(
        ft.Text("TrustFlow", size=34, style=text_style),
        ft.Row([stats_panel, table_panel], expand=True),
        upload_panel
    )


ft.app(target=main)