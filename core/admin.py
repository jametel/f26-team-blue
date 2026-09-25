from django.contrib import admin
from django.contrib.auth.models import Group, Permission

# Register your models here.
owner, created = Group.objects.get_or_create(name='Owner')
staff, created = Group.objects.get_or_create(name='Staff')
customer, created = Group.objects.get_or_create(name='Customer')

full_permissions = Permission.objects.all()
owner.permissions.set(full_permissions)

