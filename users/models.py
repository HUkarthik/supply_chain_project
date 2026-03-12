from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('supplier', 'Supplier'),
        ('customer', 'Customer'),
    )
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='customer')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)  # Added for admin request approval

    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_groups',
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        if self.pk:  # Check if the instance already exists (update case)
            original = CustomUser.objects.get(pk=self.pk)
            if original.email != self.email and CustomUser.objects.filter(email=self.email).exclude(pk=self.pk).exists():
                raise ValueError("This email is already in use by another user.")
        super().save(*args, **kwargs)

class AdminRequest(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='admin_requests')
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=(
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
    ), default='pending')
    reviewed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_requests', limit_choices_to={'role': 'admin'})
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Admin request for {self.user.username} - {self.status}"

class Product(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    stock = models.IntegerField(default=0)
    supplier = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'supplier'}, related_name='products')

    def __str__(self):
        return self.name

    def update_stock(self):
        """Update the stock field based on the total stock in related warehouses."""
        total_stock = sum(warehouse.stock_level for warehouse in self.warehouse_stocks.all())
        self.stock = total_stock
        self.save()

class Order(models.Model):
    id = models.AutoField(primary_key=True)
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='orders', limit_choices_to={'role': 'customer'})
    supplier = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='supplied_orders', limit_choices_to={'role': 'supplier'})
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=255)
    quantity = models.IntegerField()
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('processing', 'Processing'), ('shipped', 'Shipped'), ('delivered', 'Delivered')], default='pending')
    order_date = models.DateTimeField(auto_now_add=True)
    destination = models.CharField(max_length=255, blank=True, null=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Order {self.id} by {self.customer.username} for {self.product_name}"

class Supplier(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'supplier'}, null=True, blank=True)
    name = models.CharField(max_length=255)
    contact_info = models.CharField(max_length=100)
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)], null=True, blank=True)
    location = models.CharField(max_length=255)

    def __str__(self):
        return self.name

    def average_rating(self):
        ratings = ProductRating.objects.filter(order__supplier=self.user)
        if ratings.exists():
            return round(sum(rating.rating for rating in ratings) / ratings.count(), 1)
        return 0

class ProductRating(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='ratings')
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    rated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rating {self.rating} for Order {self.order.id}"

class Warehouse(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='warehouse_stocks')
    location = models.CharField(max_length=255)
    stock_level = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    LOW_STOCK_THRESHOLD = 100
    CRITICAL_STOCK_THRESHOLD = 20

    def __str__(self):
        return f"Warehouse {self.id} - {self.product.name} at {self.location}"

    def check_stock_levels(self):
        """Check stock levels and create notifications for low stock, critical stock, or empty stock."""
        if self.product and self.product.supplier:
            if self.stock_level == 0:
                Notification.objects.get_or_create(
                    user=self.product.supplier,
                    message=f"Empty stock alert: {self.product.name} at {self.location} is out of stock. Please restock immediately.",
                    notification_type='empty_stock',
                    defaults={'is_read': False}
                )
            elif self.stock_level <= self.CRITICAL_STOCK_THRESHOLD:
                Notification.objects.get_or_create(
                    user=self.product.supplier,
                    message=f"Critical stock alert: {self.product.name} at {self.location} has {self.stock_level} units remaining. Stock is below critical threshold of {self.CRITICAL_STOCK_THRESHOLD}.",
                    notification_type='critical_stock',
                    defaults={'is_read': False}
                )
            elif self.stock_level <= self.LOW_STOCK_THRESHOLD:
                Notification.objects.get_or_create(
                    user=self.product.supplier,
                    message=f"Low stock alert: {self.product.name} at {self.location} has {self.stock_level} units remaining. Please restock.",
                    notification_type='low_stock',
                    defaults={'is_read': False}
                )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.check_stock_levels()
        if self.product:
            self.product.update_stock()

class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('low_stock', 'Low Stock Alert'),
        ('critical_stock', 'Critical Stock Alert'),
        ('empty_stock', 'Empty Stock Alert'),
        ('order_update', 'Order Update'),
    )
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='notifications')  # Removed limit_choices_to to allow admin notifications if needed
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='low_stock')
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"Notification for {self.user.username}: {self.message}"

class DemandForecast(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='forecasts')
    supplier = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'supplier'})
    forecasted_quantity = models.IntegerField()
    forecast_date = models.DateTimeField(auto_now_add=True)
    period_days = models.IntegerField(default=30)  

    def __str__(self):
        return f"Forecast for {self.product.name}: {self.forecasted_quantity} units"