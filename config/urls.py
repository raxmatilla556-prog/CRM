from django.contrib import admin
from django.urls import include, path

from core import views as core

urlpatterns = [
    path('', core.home, name='home'),
    path('login/', core.login_view, name='login'),
    path('logout/', core.logout_view, name='logout'),
    path('lang/', core.set_language, name='set_language'),
    path('parol/', core.password_change, name='password_change'),
    path('xodimlar/', core.user_list, name='user_list'),
    path('xodimlar/yangi/', core.user_edit, name='user_create'),
    path('xodimlar/<int:pk>/', core.user_edit, name='user_edit'),
    path('harakatlar/', core.action_log, name='action_log'),
    path('zaxira/', core.backup_view, name='backup'),
    path('zaxira/<str:name>/', core.backup_download, name='backup_download'),
    path('telegram/ulash/', core.telegram_link, name='telegram_link'),
    path('telegram/uzish/', core.telegram_unlink, name='telegram_unlink'),
    path('ombor/', include('inventory.urls')),
    path('savdo/', include('sales.urls')),
    path('hisobot/', include('reports.urls')),
    path('admin/', admin.site.urls),
]
