"""HTML page routes (Jinja2 server-rendered UI).

API endpoints live under /api/v1. These routes serve the browser-facing pages.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.core.deps import get_current_user_from_cookie

router = APIRouter(include_in_schema=False)


def _user_to_dict(user) -> dict | None:
    """Convert an AppUser model to a JSON-serialisable dict."""
    if user is None:
        return None
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "dept_id": user.dept_id,
        "dept_name": user.department.dept_name if user.department else None,
        "usn": user.usn,
    }


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        request=request, name="auth/login.html", context={"active_page": "login"}
    )


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        request=request, name="auth/register.html", context={"active_page": "register"}
    )


@router.get("/complaints", response_class=HTMLResponse)
def complaints_page(request: Request, user=Depends(get_current_user_from_cookie)):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="complaints/list.html",
        context={"active_page": "complaints", "user": _user_to_dict(user)},
    )


@router.get("/complaints/new", response_class=HTMLResponse)
def new_complaint_page(request: Request, user=Depends(get_current_user_from_cookie)):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="complaints/new.html",
        context={"active_page": "new_complaint", "user": _user_to_dict(user)},
    )


@router.get("/complaints/{complaint_id}", response_class=HTMLResponse)
def complaint_detail_page(request: Request, complaint_id: int, user=Depends(get_current_user_from_cookie)):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="complaints/detail.html",
        context={"active_page": "complaints", "complaint_id": complaint_id, "user": _user_to_dict(user)},
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, user=Depends(get_current_user_from_cookie)):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={"active_page": "dashboard", "user": _user_to_dict(user)},
    )


@router.get("/admin/rules", response_class=HTMLResponse)
def admin_rules_page(request: Request, user=Depends(get_current_user_from_cookie)):
    """Triage rule editor.

    Exists so "configurable rules" is demonstrable through the browser and not
    only through curl on the JSON API.
    """
    return request.app.state.templates.TemplateResponse(
        request=request, name="admin/rules.html", context={"active_page": "admin_rules", "user": _user_to_dict(user)}
    )


@router.get("/admin/models", response_class=HTMLResponse)
def admin_models_page(request: Request, user=Depends(get_current_user_from_cookie)):
    """Model registry showing the metrics actually measured at training time."""
    return request.app.state.templates.TemplateResponse(
        request=request, name="admin/models.html", context={"active_page": "admin_models", "user": _user_to_dict(user)}
    )
