from starlette.applications import Starlette
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route

from db import init_schema
from pages.admin import app as admin_app
from pages.bitcoin import app as public_app

init_schema()


async def _admin_redirect(request):
    return RedirectResponse(url="/admin/")


app = Starlette(
    routes=[
        Route("/admin", _admin_redirect),
        Mount("/admin", app=admin_app),
        Mount("/", app=public_app),
    ]
)
