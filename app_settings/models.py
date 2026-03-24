from django.db import models


class NotificationSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    stock_low_alert = models.BooleanField(default=True)
    checkout_reminder = models.BooleanField(default=True)
    missing_cash_close = models.BooleanField(default=True)
    daily_auto_summary = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class FinancialSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    currency = models.CharField(max_length=16, default="BIF")
    tax_rate = models.FloatField(default=18)
    fiscal_year_start = models.CharField(max_length=2, default="01")
    updated_at = models.DateTimeField(auto_now=True)


class EstablishmentSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    establishment_name = models.CharField(max_length=191, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=64, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    city = models.CharField(max_length=128, default="Bujumbura")
    country = models.CharField(max_length=128, default="Burundi")
    logo_url = models.URLField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
