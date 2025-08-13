from django.contrib import admin
from .models import IntegrationInbound

@admin.register(IntegrationInbound)
class IntegrationInboundAdmin(admin.ModelAdmin):
    list_display = ("message_id", "subject", "received_at", "processed_at")
    search_fields = ("message_id", "subject")
