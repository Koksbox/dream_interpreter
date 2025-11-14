# dreambot/models.py
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager

class UserManager(BaseUserManager):
    def create_user(self, phone_number, name=None, birth_date=None, password=None):
        if not phone_number:
            raise ValueError("Номер телефона обязателен")
        user = self.model(phone_number=phone_number, name=name, birth_date=birth_date)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, name=None, birth_date=None, password=None):
        user = self.create_user(phone_number, name, birth_date, password)
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user

    def get_by_natural_key(self, phone_number):
        return self.get(phone_number=phone_number)

class User(AbstractBaseUser):
    phone_number = models.CharField(max_length=15, unique=True)
    name = models.CharField(max_length=100, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    objects = UserManager()
    USERNAME_FIELD = 'phone_number'

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser

class DreamSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

class Message(models.Model):
    session = models.ForeignKey(DreamSession, on_delete=models.CASCADE)
    is_user = models.BooleanField()
    content = models.TextField()
    audio_file = models.FileField(upload_to='audio/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)