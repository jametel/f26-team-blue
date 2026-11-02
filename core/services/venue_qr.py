from io import BytesIO
from urllib.parse import urlsplit

import qrcode
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import URLValidator
from django.urls import reverse


def venue_public_url(venue):
    origin = settings.PUBLIC_BASE_URL.strip().rstrip('/')
    try:
        parts = urlsplit(origin)
        URLValidator(schemes=['http', 'https'])(origin)
        if parts.username or parts.password or parts.path or parts.query or parts.fragment:
            raise ValueError('The public URL must be an origin.')
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise ValueError('Invalid port.')
    except (ValueError, ValidationError):
        raise ImproperlyConfigured('Set PUBLIC_BASE_URL to a valid HTTP or HTTPS origin.') from None
    return origin + reverse('select_venue', args=[venue.slug])


def venue_qr_png(venue):
    image = qrcode.make(venue_public_url(venue))
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()
