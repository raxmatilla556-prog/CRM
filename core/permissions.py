from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(*roles):
    """Faqat berilgan rollarga ruxsat beradi. Ega hamma joyga kira oladi."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if user.is_owner or user.role in roles:
                return view(request, *args, **kwargs)
            messages.error(request, "Bu sahifaga ruxsatingiz yo'q")
            return redirect('home')

        return wrapper

    return decorator


owner_required = role_required('owner')
seller_required = role_required('seller')
warehouse_required = role_required('warehouse')
