import secrets

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.backup import list_backups, make_backup
from core.forms import UserForm
from core.i18n import tr
from core.jobs import schedule_info
from core.models import ActionLog, User, log_action
from core.notify import bot_username
from core.permissions import owner_required


def _safe_next(request, url):
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
        return url
    return 'home'


MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 10 * 60


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        key = f'login_fail:{username.lower()}'
        if cache.get(key, 0) >= MAX_LOGIN_ATTEMPTS:
            error = "Juda ko'p noto'g'ri urinish. 10 daqiqadan keyin qayta urinib ko'ring"
        else:
            user = authenticate(request, username=username, password=request.POST.get('password', ''))
            if user:
                cache.delete(key)
                login(request, user)
                log_action(user, 'Tizimga kirdi')
                return redirect(_safe_next(request, request.GET.get('next')))
            cache.set(key, cache.get(key, 0) + 1, LOCKOUT_SECONDS)
            error = "Login yoki parol noto'g'ri"
    return render(request, 'core/login.html', {'error': error})


@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    for field in form.fields.values():
        field.widget.attrs['class'] = 'form-control'
    form.fields['old_password'].label = tr('Joriy parol')
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=['must_change_password'])
        update_session_auth_hash(request, user)
        log_action(user, "Parolni o'zgartirdi")
        messages.success(request, 'Saqlandi')
        return redirect('home')
    return render(request, 'core/password_change.html', {'form': form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def home(request):
    user = request.user
    if user.is_owner:
        return redirect('reports:dashboard')
    if user.is_warehouse:
        return redirect('inventory:stock')
    return redirect('sales:pos')


@require_POST
def set_language(request):
    lang = request.POST.get('lang', 'uz')
    if lang not in ('uz', 'ru'):
        lang = 'uz'
    request.session['lang'] = lang
    if request.user.is_authenticated:
        request.user.language = lang
        request.user.save(update_fields=['language'])
    return redirect(_safe_next(request, request.POST.get('next')))


@owner_required
def user_list(request):
    return render(request, 'core/user_list.html', {'users': User.objects.order_by('role', 'username')})


@owner_required
def user_edit(request, pk=None):
    instance = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        if user.pk == request.user.pk:
            # Ega o'z parolini almashtirsa: majburlash shart emas va sessiya saqlanadi
            if user.must_change_password:
                user.must_change_password = False
                user.save(update_fields=['must_change_password'])
            update_session_auth_hash(request, user)
        log_action(request.user, f"Xodim {'tahrirlandi' if instance else 'qo‘shildi'}: {user.username}")
        messages.success(request, 'Saqlandi')
        return redirect('user_list')
    return render(request, 'core/user_form.html', {'form': form, 'instance': instance})


@owner_required
def telegram_link(request):
    """Egani Telegram botga bog'lash: bir martalik kod bilan botni ochadi."""
    username = bot_username()
    if not username:
        messages.error(request, 'Telegram sozlanmagan')
        return redirect('reports:dashboard')
    request.user.telegram_link_code = secrets.token_urlsafe(16)
    request.user.save(update_fields=['telegram_link_code'])
    return redirect(f'https://t.me/{username}?start={request.user.telegram_link_code}')


@owner_required
@require_POST
def telegram_unlink(request):
    request.user.telegram_chat_id = ''
    request.user.save(update_fields=['telegram_chat_id'])
    messages.success(request, 'Saqlandi')
    return redirect('reports:dashboard')


@owner_required
def backup_view(request):
    if request.method == 'POST':
        path = make_backup()
        log_action(request.user, f'Zaxira nusxa yaratildi: {path.name}')
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name)
    return render(request, 'core/backup.html', {
        'backups': [{'name': p.name, 'size': p.stat().st_size} for p in list_backups()],
        'jobs': schedule_info(),
    })


@owner_required
def backup_download(request, name):
    path = next((p for p in list_backups() if p.name == name), None)
    if not path:
        raise Http404
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name)


@owner_required
def action_log(request):
    logs = ActionLog.objects.select_related('user')
    user_id = request.GET.get('user')
    if user_id:
        logs = logs.filter(user_id=user_id)
    page = Paginator(logs, 50).get_page(request.GET.get('page'))
    return render(request, 'core/action_log.html', {
        'page': page, 'users': User.objects.all(), 'selected_user': user_id,
    })
