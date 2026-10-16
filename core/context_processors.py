from core.roles import get_role


def role(request):
    """Expose the current user's role to every template (drives the menu)."""
    return {"user_role": get_role(request.user)}
