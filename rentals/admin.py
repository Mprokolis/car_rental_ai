from django.contrib import admin, messages
from .models import Car, Company, Booking

@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    exclude = ('price_per_day', 'extra_insurance')
    list_display = ('brand', 'model', 'category', 'fuel_type', 'company', 'is_rented')
    list_filter = ('company', 'category', 'fuel_type', 'is_rented')
    search_fields = ('brand', 'model', 'license_plate')

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'last_trained')
    search_fields = ('name', 'email')

@admin.action(description="Convert to RentalRequest (και σημαίνει Active)")
def convert_bookings_to_rental_requests(modeladmin, request, queryset):
    converted = 0
    skipped = 0
    for booking in queryset.order_by('id'):
        if booking.status != "imported":
            skipped += 1
            continue
        rr, dec = booking.to_rental_request()
        # προαιρετικά: αλλάζουμε status σε active ώστε να μπει στο workflow
        booking.status = "active"
        booking.save(update_fields=["status"])
        converted += 1
    if converted:
        messages.success(request, f"✅ Δημιουργήθηκαν {converted} RentalRequest(s).")
    if skipped:
        messages.warning(request, f"⚠️ Παραλείφθηκαν {skipped} (status ≠ imported).")

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'booking_code',
        'company',
        'customer_name',
        'start_at',
        'end_at',
        'status',
        'requested_category',
        'extra_insurance',
        'total_price',
    )
    list_filter = (
        'company',
        'status',
        'requested_category',
        'extra_insurance',
        'start_at',
    )
    search_fields = (
        'booking_code',
        'customer_name',
        'customer_email',
        'customer_phone',
        'source_email_uid',
        'gm_msgid',
    )
    actions = [convert_bookings_to_rental_requests]