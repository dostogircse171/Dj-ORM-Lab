from django.contrib import admin
from .models import Category, Product, Customer, Order, OrderItem, Review, Tag

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "stock", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name",)

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "city", "joined_at")
    search_fields = ("name", "email")

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "status", "total_amount", "created_at")
    list_filter = ("status",)

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product", "quantity", "unit_price")

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "customer", "rating", "created_at")
    list_filter = ("rating",)

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name",)
