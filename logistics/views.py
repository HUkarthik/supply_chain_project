from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from users.models import Order, Warehouse
from .models import Logistics
import googlemaps
import datetime
import logging

logger = logging.getLogger(__name__)

gmaps = googlemaps.Client(key='AIzaSyAaY9EE4VQTi9eykGzX3R3a6bSHtiNpa2I')

@login_required
def optimize_route(request, order_id):
    order = get_object_or_404(Order, id=order_id, supplier=request.user)
    
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        destination = request.POST.get('destination')
        if destination:
            
            warehouse = Warehouse.objects.filter(
                product__name=order.product_name,
                product__supplier=order.supplier,
                stock_level__gt=0
            ).first()

            if not warehouse:
                message = 'No available warehouse found for the ordered product.'
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': message}, status=400)
                return render(request, 'users/supplier-dashboard.html', {'message': message})

            start_location = warehouse.location
            try:
                result = gmaps.distance_matrix(start_location, destination, mode="driving", departure_time="now")
                if result['rows'][0]['elements'][0]['status'] == 'OK':
                    distance = result['rows'][0]['elements'][0]['distance']['text']
                    duration = result['rows'][0]['elements'][0]['duration']['text']
                    optimized_route = f"Optimized route from {start_location} to {destination}"
                else:
                    distance = "N/A"
                    duration = "N/A"
                    optimized_route = f"Optimized route from {start_location} to {destination}: [Route calculation failed - Status: {result['rows'][0]['elements'][0]['status']}]"
                    logger.warning(f"Distance Matrix API returned status: {result['rows'][0]['elements'][0]['status']}")
            except googlemaps.exceptions.ApiError as e:
                distance = "N/A"
                duration = "N/A"
                optimized_route = f"Optimized route from {start_location} to {destination}: [API Error: {str(e)}]"
                logger.error(f"Google Maps API Error: {str(e)}")
            except Exception as e:
                distance = "N/A"
                duration = "N/A"
                optimized_route = f"Optimized route from {start_location} to {destination}: [Unexpected Error: {str(e)}]"
                logger.error(f"Unexpected Error in optimize_route: {str(e)}")

            try:
                if duration != "N/A":
                    duration_parts = duration.split()
                    total_seconds = sum(int(duration_parts[i]) * {"hours": 3600, "mins": 60, "seconds": 1}.get(duration_parts[i+1].rstrip('s'), 0) for i in range(0, len(duration_parts)-1, 2))
                    estimated_time = datetime.timedelta(seconds=total_seconds)
                else:
                    estimated_time = datetime.timedelta(hours=2, minutes=30)  
            except Exception as e:
                estimated_time = datetime.timedelta(hours=2, minutes=30)  
                logger.error(f"Error converting duration to timedelta: {str(e)}")

            logistics, created = Logistics.objects.update_or_create(
                order_id=order,
                defaults={
                    'warehouse': warehouse,
                    'destination': destination,
                    'optimized_route': optimized_route,
                    'estimated_time': estimated_time,
                    'distance': distance,
                }
            )

            if is_ajax:
                return JsonResponse({
                    'status': 'success',
                    'message': optimized_route,
                    'start_location': logistics.start_location,
                    'destination': logistics.destination,
                    'estimated_time': str(logistics.estimated_time),
                    'distance': logistics.distance,
                })
            return render(request, 'logistics/optimize_route.html', {
                'order': order,
                'logistics': logistics,
            })
        else:
            message = 'Destination is required.'
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message}, status=400)
            return render(request, 'users/supplier-dashboard.html', {'message': message})
    else:
        
        try:
            logistics = Logistics.objects.get(order_id=order)
            return render(request, 'logistics/optimize_route.html', {
                'order': order,
                'logistics': logistics,
            })
        except Logistics.DoesNotExist:
        
            return render(request, 'users/supplier-dashboard.html', {
                'message': 'No optimized route found for this order. Please optimize the route first.'
            })