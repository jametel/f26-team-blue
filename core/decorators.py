from functools import wraps
from django.shortcuts import redirect
from django.http import HttpResponseForbidden

from core.roles import get_role


def role_required(allowed_roles):
    """
    Restricts a page to users whose role is one of the allowed roles.

    A user's role is the highest of Owner > Staff > Customer (superusers count
    as Owner), so Owner is always allowed wherever Staff is.

    Example:
        @role_required(["Staff", "Owner"])
        def staff_dashboard(request):
            ...
    """

    def decorator(view_function):

        @wraps(view_function)
        def wrapper(request, *args, **kwargs):

            # User must be logged in
            if not request.user.is_authenticated:
                return redirect(f"{redirect_login_url()}?next={request.path}")

            if get_role(request.user) not in allowed_roles:
                return HttpResponseForbidden(
                    "You do not have permission to access this page."
                )

            return view_function(request, *args, **kwargs)

        return wrapper

    return decorator


def redirect_login_url():
    from django.urls import reverse
    return reverse("login")
