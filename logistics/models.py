from django.db import models
from users.models import Order, Warehouse

class Logistics(models.Model):
    order_id = models.OneToOneField(Order, on_delete=models.CASCADE, primary_key=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='logistics', null=True, blank=True)
    
    destination = models.CharField(max_length=255)
    optimized_route = models.TextField()
    estimated_time = models.DurationField()
    distance = models.CharField(max_length=50, blank=True, null=True)  

    def __str__(self):
        return f"Logistics for Order {self.order_id.id}"

    @property
    def start_location(self):
        """Derive start_location from the associated warehouse's location."""
        return self.warehouse.location if self.warehouse else "Unknown Location"