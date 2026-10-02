from functools import wraps
from django.shortcuts import redirect
from django.http import HttpResponseForbidden


def role_required(allowed_roles):
    """
    Restricts a page to users who belong to one of the allowed Django Groups.

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
                return redirect("login")

            # Check whether the user belongs to an allowed group
            user_roles = request.user.groups.values_list("name", flat=True)

            if not any(role in allowed_roles for role in user_roles):
                return HttpResponseForbidden(
                    "You do not have permission to access this page."
                )

            return view_function(request, *args, **kwargs)

        return wrapper

    return decorator