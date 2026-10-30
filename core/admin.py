from django.contrib import admin

from core.models import (
    Song, SongFeatures, SongRequest, UserProfile, Venue, VenueConfig, VenueSongBlacklist,
    venueGenreFilter,
)


class VenueConfigInline(admin.StackedInline):
    model = VenueConfig
    max_num = 1


class VenueGenreInline(admin.TabularInline):
    model = venueGenreFilter
    extra = 0


class VenueBlacklistInline(admin.TabularInline):
    model = VenueSongBlacklist
    extra = 0


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner")
    filter_horizontal = ("staff",)
    inlines = (VenueConfigInline, VenueGenreInline, VenueBlacklistInline)

admin.site.register(Song)
admin.site.register(SongFeatures)
admin.site.register(SongRequest)
admin.site.register(UserProfile)
