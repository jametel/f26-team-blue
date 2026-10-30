"""Role helpers. Roles are Django Groups created by migration 0002."""

CUSTOMER = "Customer"
STAFF = "Staff"
OWNER = "Owner"
ROLES = [CUSTOMER, STAFF, OWNER]


def get_role(user):
    """Return the user's highest role (Owner > Staff > Customer), or None."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return OWNER
    names = set(user.groups.values_list("name", flat=True))
    for role in (OWNER, STAFF, CUSTOMER):
        if role in names:
            return role
    return None


def set_role(user, role):
    """Make `role` the user's only role group."""
    from django.contrib.auth.models import Group

    user.groups.remove(*Group.objects.filter(name__in=ROLES))
    user.groups.add(Group.objects.get(name=role))


def can_manage_venue(user, venue):
    if not user.is_authenticated:
        return False
    if user.is_superuser or venue.owner_id == user.pk:
        return True
    return get_role(user) in (STAFF, OWNER) and venue.staff.filter(pk=user.pk).exists()
