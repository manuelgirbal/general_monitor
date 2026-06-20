from shiny import App, ui

from pages.bitcoin import bitcoin_server, bitcoin_ui
from pages.macro_ar import macro_ar_server, macro_ar_ui
from plots import page_head

app_ui = ui.page_navbar(
    bitcoin_ui("bitcoin"),
    macro_ar_ui("macro_ar"),
    title="Monitor",
    id="vertical",
    header=ui.head_content(*page_head()),
)


def server(input, output, session):
    bitcoin_server("bitcoin")
    macro_ar_server("macro_ar")


app = App(app_ui, server)
