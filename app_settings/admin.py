from django.contrib import admin

from .models import EstablishmentSettings, FinancialSettings, NotificationSettings


admin.site.register(NotificationSettings)
admin.site.register(FinancialSettings)
admin.site.register(EstablishmentSettings)
