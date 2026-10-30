from django.contrib import admin

from core.models import Song, SongRequest, UserProfile, Venue

admin.site.register(Song)
admin.site.register(SongRequest)
admin.site.register(UserProfile)
admin.site.register(Venue)
