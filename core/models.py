from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Ega'
        SELLER = 'seller', 'Sotuvchi'
        WAREHOUSE = 'warehouse', 'Omborchi'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SELLER)
    phone = models.CharField(max_length=20, blank=True)
    language = models.CharField(max_length=2, choices=[('uz', "O'zbek"), ('ru', 'Русский')], default='uz')
    telegram_chat_id = models.CharField(max_length=32, blank=True)
    telegram_link_code = models.CharField(max_length=32, blank=True, db_index=True)
    must_change_password = models.BooleanField(default=False)

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER or self.is_superuser

    @property
    def is_seller(self):
        return self.role == self.Role.SELLER

    @property
    def is_warehouse(self):
        return self.role == self.Role.WAREHOUSE

    def __str__(self):
        return self.get_full_name() or self.username


class ActionLog(models.Model):
    """Xodimlar harakatlari tarixi (ega ko'radi)."""

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='actions')
    action = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user}: {self.action}'


def log_action(user, action):
    ActionLog.objects.create(user=user if user and user.is_authenticated else None, action=action[:255])


class JobRun(models.Model):
    """Avtomatik vazifa (kunlik hisobot, eslatma, zaxira) qaysi kuni bajarilgani - takror ishlamasligi uchun."""

    name = models.CharField(max_length=50)
    run_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['name', 'run_date'], name='unique_job_per_day')]
