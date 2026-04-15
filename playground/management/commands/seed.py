from django.core.management.base import BaseCommand
from django.db import transaction
from playground.models import Category, Product, Customer, Order, OrderItem, Review, Tag
import datetime
import decimal


class Command(BaseCommand):
    help = "Seed the database with dummy data"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Clearing existing data...")
        Tag.objects.all().delete()
        Review.objects.all().delete()
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()
        Customer.objects.all().delete()

        self.stdout.write("Seeding categories...")
        categories = [
            Category.objects.create(name="Electronics", description="Gadgets and devices"),
            Category.objects.create(name="Books", description="Fiction and non-fiction"),
            Category.objects.create(name="Clothing", description="Apparel and accessories"),
            Category.objects.create(name="Home & Kitchen", description="Furniture and appliances"),
            Category.objects.create(name="Sports", description="Sporting goods and equipment"),
        ]

        self.stdout.write("Seeding products...")
        products_data = [
            ("Laptop Pro 15", categories[0], "1299.99", 20),
            ("Wireless Earbuds", categories[0], "89.99", 150),
            ("Smartphone X12", categories[0], "799.00", 60),
            ("USB-C Hub", categories[0], "39.99", 200),
            ("4K Monitor", categories[0], "549.00", 30),
            ("The Art of War", categories[1], "9.99", 500),
            ("Clean Code", categories[1], "34.99", 80),
            ("Dune", categories[1], "14.99", 300),
            ("Atomic Habits", categories[1], "16.99", 250),
            ("Python Crash Course", categories[1], "29.99", 120),
            ("Running Shoes", categories[4], "119.99", 90),
            ("Yoga Mat", categories[4], "29.99", 180),
            ("Dumbbell Set", categories[4], "74.99", 40),
            ("T-Shirt Classic", categories[2], "19.99", 400),
            ("Denim Jacket", categories[2], "59.99", 70),
            ("Coffee Maker", categories[3], "49.99", 55),
            ("Air Fryer", categories[3], "79.99", 35),
            ("Blender Pro", categories[3], "99.99", 25),
        ]
        products = []
        for name, cat, price, stock in products_data:
            products.append(Product.objects.create(
                name=name,
                category=cat,
                price=decimal.Decimal(price),
                stock=stock,
                is_active=True,
            ))
        # Make one inactive
        products[-1].is_active = False
        products[-1].save()

        self.stdout.write("Seeding tags...")
        tags_data = {
            "bestseller": [products[0], products[6], products[8]],
            "new-arrival": [products[2], products[4], products[14]],
            "sale": [products[1], products[3], products[11], products[13]],
            "featured": [products[0], products[2], products[8], products[10]],
            "eco-friendly": [products[11], products[13]],
        }
        for tag_name, tag_products in tags_data.items():
            tag = Tag.objects.create(name=tag_name)
            tag.products.set(tag_products)

        self.stdout.write("Seeding customers...")
        customers_data = [
            ("Alice Johnson", "alice@example.com", "New York", "2023-01-15"),
            ("Bob Smith", "bob@example.com", "Los Angeles", "2023-03-22"),
            ("Carol White", "carol@example.com", "Chicago", "2023-06-01"),
            ("David Brown", "david@example.com", "Houston", "2023-07-10"),
            ("Eva Martinez", "eva@example.com", "Phoenix", "2023-08-05"),
            ("Frank Lee", "frank@example.com", "San Antonio", "2023-09-18"),
            ("Grace Kim", "grace@example.com", "San Diego", "2023-11-02"),
            ("Henry Wilson", "henry@example.com", "Dallas", "2024-01-20"),
            ("Iris Chen", "iris@example.com", "San Jose", "2024-02-14"),
            ("Jack Taylor", "jack@example.com", "Austin", "2024-03-30"),
        ]
        customers = []
        for name, email, city, joined in customers_data:
            customers.append(Customer.objects.create(
                name=name,
                email=email,
                city=city,
                joined_at=datetime.date.fromisoformat(joined),
            ))

        self.stdout.write("Seeding orders and order items...")
        orders_data = [
            (customers[0], "delivered", [
                (products[0], 1, "1299.99"),
                (products[1], 2, "89.99"),
            ]),
            (customers[0], "delivered", [
                (products[6], 1, "34.99"),
                (products[8], 1, "16.99"),
            ]),
            (customers[1], "shipped", [
                (products[2], 1, "799.00"),
            ]),
            (customers[1], "confirmed", [
                (products[4], 1, "549.00"),
                (products[3], 1, "39.99"),
            ]),
            (customers[2], "pending", [
                (products[11], 2, "29.99"),
                (products[13], 3, "19.99"),
            ]),
            (customers[3], "delivered", [
                (products[9], 1, "29.99"),
                (products[7], 1, "14.99"),
            ]),
            (customers[4], "delivered", [
                (products[10], 1, "119.99"),
                (products[12], 1, "74.99"),
            ]),
            (customers[5], "cancelled", [
                (products[15], 1, "49.99"),
            ]),
            (customers[6], "shipped", [
                (products[16], 1, "79.99"),
                (products[5], 2, "9.99"),
            ]),
            (customers[7], "confirmed", [
                (products[14], 2, "59.99"),
            ]),
            (customers[8], "pending", [
                (products[2], 1, "799.00"),
                (products[1], 1, "89.99"),
            ]),
            (customers[9], "delivered", [
                (products[0], 1, "1299.99"),
            ]),
        ]
        for customer, status, items in orders_data:
            total = sum(decimal.Decimal(price) * qty for _, qty, price in items)
            order = Order.objects.create(
                customer=customer,
                status=status,
                total_amount=total,
            )
            for product, qty, price in items:
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=qty,
                    unit_price=decimal.Decimal(price),
                )

        self.stdout.write("Seeding reviews...")
        reviews_data = [
            (products[0], customers[0], 5, "Absolutely love this laptop!"),
            (products[0], customers[9], 4, "Great performance, a bit pricey."),
            (products[1], customers[0], 5, "Best earbuds I've ever owned."),
            (products[2], customers[1], 3, "Decent phone but overpriced."),
            (products[6], customers[0], 5, "A must-read for every developer."),
            (products[8], customers[0], 5, "Changed my life."),
            (products[8], customers[3], 4, "Very practical advice."),
            (products[7], customers[3], 5, "Sci-fi masterpiece!"),
            (products[10], customers[4], 5, "Super comfortable for long runs."),
            (products[12], customers[4], 4, "Good quality, ships fast."),
            (products[11], customers[2], 5, "Thick and non-slip, love it."),
            (products[13], customers[2], 3, "Average quality for the price."),
            (products[15], customers[5], 2, "Stopped working after 2 weeks."),
            (products[16], customers[6], 4, "Cooks food fast and evenly."),
            (products[14], customers[7], 4, "Stylish and warm."),
            (products[9], customers[3], 5, "Very clear explanations."),
        ]
        for product, customer, rating, comment in reviews_data:
            Review.objects.create(
                product=product,
                customer=customer,
                rating=rating,
                comment=comment,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done! Seeded: {Category.objects.count()} categories, "
            f"{Product.objects.count()} products, "
            f"{Customer.objects.count()} customers, "
            f"{Order.objects.count()} orders, "
            f"{Review.objects.count()} reviews, "
            f"{Tag.objects.count()} tags."
        ))
