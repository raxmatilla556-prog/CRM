from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from core.models import ActionLog, User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_active')
    fieldsets = UserAdmin.fieldsets + (("Do'kon", {'fields': ('role', 'phone', 'language')}),)


admin.site.register(ActionLog)
