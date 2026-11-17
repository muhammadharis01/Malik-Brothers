from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext as _


def user_has_any_role(user, role_names):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    user_groups = set(user.groups.values_list('name', flat=True))
    return bool(user_groups.intersection(set(role_names)))


def role_required(allowed_roles):
    """
    Decorator for views to enforce Django Group membership.
    If the user lacks required role, raises PermissionDenied (403).
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            if request.user.is_superuser or 'Admin' in allowed_roles and request.user.groups.filter(name='Admin').exists():
                return view_func(request, *args, **kwargs)

            user_groups = set(request.user.groups.values_list('name', flat=True))
            if any(role in user_groups for role in allowed_roles):
                return view_func(request, *args, **kwargs)

            raise PermissionDenied(_("You do not have permission to access this screen."))
        return _wrapped_view
    return decorator

