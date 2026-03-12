from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import transaction
import logging
from .forms import CustomUserCreationForm, CustomUserUpdateForm, SupplierForm, SupplierRatingForm, ReceiptConfirmationForm
from .models import CustomUser, Order, Supplier, ProductRating, Warehouse, Product, Notification, DemandForecast, AdminRequest
from logistics.views import optimize_route
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from django.db.models import Sum
from datetime import timedelta
from django.utils.timezone import now
import decimal  

logger = logging.getLogger(__name__)

def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            if user.role == 'admin':
                user.is_active = False  # Deactivate until approved
                user.save()
                AdminRequest.objects.create(user=user)
                messages.success(request, 'Your request to register as an admin has been submitted. Please wait for approval.')
                logger.info(f"Admin registration request created for user {user.username}")
            else:
                user.save()
                login(request, user)
                messages.success(request, f'Account created for {user.username}! You are now logged in.')
                logger.info(f"User {user.username} registered successfully with role {user.role}")
                return redirect('users:dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomUserCreationForm()
    return render(request, 'registration/register.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        logger.info(f"User {request.user.username} is already authenticated, redirecting based on role: {request.user.role}")
        if request.user.role == 'admin':
            return redirect('users:dashboard')
        elif request.user.role == 'supplier':
            return redirect('users:supplier_dashboard')
        else: 
            return redirect('users:customer_dashboard')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                if not user.is_active:
                    messages.error(request, 'Your account is pending admin approval.')
                    logger.info(f"User {username} attempted to log in but account is inactive (pending admin approval).")
                    return render(request, 'registration/login.html', {'form': form})
                login(request, user)
                messages.success(request, f'Welcome, {username}!')
                logger.info(f"User {username} logged in successfully, role: {user.role}")
                if user.role == 'admin':
                    return redirect('users:dashboard')
                elif user.role == 'supplier':
                    return redirect('users:supplier_dashboard')
                else:  
                    return redirect('users:customer_dashboard')
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(request, 'Invalid form submission.')
    else:
        form = AuthenticationForm()
    return render(request, 'registration/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('users:login')

@login_required
def edit_profile(request):
    if request.method == 'POST':
        form = CustomUserUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('users:dashboard')
        else:
            messages.error(request, 'Error updating profile.')
    else:
        form = CustomUserUpdateForm(instance=request.user)
    return render(request, 'edit_profile.html', {'form': form})

@login_required
def create_order(request):
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        supplier_id = request.POST.get('supplier')
        product_id = request.POST.get('product')
        quantity = request.POST.get('quantity')
        destination = request.POST.get('destination')

        if not all([supplier_id, product_id, quantity, destination]):
            message = "All fields are required: Supplier, Product, Quantity, and Delivery Destination."
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
            return redirect('users:customer_dashboard')

        try:
            quantity = int(quantity)
            if quantity < 1:
                raise ValueError("Quantity must be at least 1.")

            supplier = CustomUser.objects.get(id=supplier_id, role='supplier')
            product = Product.objects.get(id=product_id, supplier=supplier)
            if not product:
                raise ValueError("Product does not exist.")
            warehouse = Warehouse.objects.get(product=product, stock_level__gte=quantity)

            with transaction.atomic():
                order = Order.objects.create(
                    customer=request.user,
                    supplier=supplier,
                    product=product,  
                    product_name=product.name,
                    quantity=quantity,
                    status='pending',
                    destination=destination
                )
                warehouse.stock_level -= quantity
                warehouse.last_updated = timezone.now()
                warehouse.save()
                total_stock = sum(w.stock_level for w in product.warehouse_stocks.all())
                product.stock = total_stock
                product.save()

                Notification.objects.create(
                    user=supplier,
                    message=f"New order received: {quantity} units of {product.name} from {request.user.username}.",
                    notification_type='order_update'
                )

            message = f"Order for {quantity} units of {product.name} placed successfully!"
            if is_ajax:
                return JsonResponse({'status': 'success', 'message': message})
            messages.success(request, message)
        except ValueError as ve:
            message = f"Invalid input: {str(ve)}"
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
        except CustomUser.DoesNotExist:
            message = "Selected supplier does not exist."
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
        except Product.DoesNotExist:
            message = "Selected product does not belong to the chosen supplier."
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
        except Warehouse.DoesNotExist:
            message = "Insufficient stock or product not available in the supplier's warehouse."
            if is_ajax:
                return JsonResponse({'status': 'error', "message": message})
            messages.error(request, message)
        except Exception as e:
            message = f"Error placing order: {str(e)}"
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)

        return redirect('users:customer_dashboard')

    return redirect('users:customer_dashboard')

@login_required
def confirm_receipt(request):
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        order_id = request.POST.get('order_id')
        confirm = request.POST.get('confirm')
        logger.info(f"Confirm receipt request for order_id: {order_id}, confirm: {confirm}")
        if order_id and confirm == 'on':
            try:
                order = get_object_or_404(Order, id=order_id, customer=request.user, status='shipped')
                order.status = 'delivered'
                order.updated_at = timezone.now()
                order.save()
                Notification.objects.create(
                    user=order.supplier,
                    message=f"Order #{order_id} receipt confirmed by {request.user.username}",
                    notification_type='order_update'
                )
                logger.info(f"Order {order_id} marked as delivered")

                receipt_buffer = generate_receipt(order)
                response = HttpResponse(receipt_buffer, content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="receipt_order_{order_id}.pdf"'
                return response
            except Exception as e:
                logger.error(f"Error confirming receipt: {str(e)}")
                return JsonResponse({'status': 'error', 'message': 'Error processing receipt confirmation.'}, status=400)
        return JsonResponse({'status': 'error', 'message': 'Invalid submission or order not found.'}, status=400)
    return redirect('users:customer_dashboard')

@login_required
def download_receipt(request, order_id):
    order = get_object_or_404(Order, id=order_id, customer=request.user, status='delivered')
    try:
        receipt_buffer = generate_receipt(order)
        response = HttpResponse(receipt_buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="receipt_order_{order_id}.pdf"'
        return response
    except Exception as e:
        logger.error(f"Error downloading receipt for order {order_id}: {str(e)}")
        return JsonResponse({'status': 'error', 'message': 'Error downloading receipt.'}, status=500)

def generate_receipt(order):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        name='TitleStyle',
        fontSize=18,
        leading=22,
        alignment=1,
        spaceAfter=12,
        textColor=colors.navy,
        fontName='Helvetica-Bold'
    )

    company_style = ParagraphStyle(
        name='CompanyStyle',
        fontSize=12,
        leading=14,
        alignment=2,
        spaceAfter=12,
        textColor=colors.darkgreen,
        fontName='Helvetica-Bold'
    )

    normal_style = styles['Normal']
    normal_style.fontSize = 10
    normal_style.leading = 12
    normal_style.fontName = 'Helvetica'

    signature_style = ParagraphStyle(
        name='SignatureStyle',
        fontSize=10,
        leading=12,
        spaceBefore=6,
        fontName='Helvetica'
    )

    elements.append(Paragraph(order.supplier.username, company_style))
    elements.append(Paragraph("Order Receipt", title_style))
    elements.append(Spacer(1, 0.2*inch))

    product = order.product

    quantity = decimal.Decimal(str(order.quantity))
    price = product.price  
    subtotal = quantity * price
    gst_rate = decimal.Decimal('0.18')
    gst_amount = subtotal * gst_rate
    total_with_gst = subtotal + gst_amount

    order_date = order.order_date.strftime("%Y-%m-%d %H:%M:%S")
    receipt_confirmed_date = (order.updated_at or timezone.now()).strftime("%Y-%m-%d %H:%M:%S")

    data = [
        ["Field", "Details"],
        ["Order ID", str(order.id)],
        ["Customer", order.customer.username],
        ["Supplier", order.supplier.username],
        ["Product", order.product_name],
        ["Quantity", str(order.quantity)],
        ["Price per Unit", f"INR {product.price:.2f}"],
        ["Subtotal", f"INR {subtotal:.2f}"],
        ["GST (18%)", f"INR {gst_amount:.2f}"],
        ["Total with GST", f"INR {total_with_gst:.2f}"],
        ["Address", order.destination],
        ["Status", order.status],
        ["Order Date", order_date],
        ["Receipt Confirmed", receipt_confirmed_date],
    ]

    table = Table(data, colWidths=[2*inch, 4*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.2*inch))

    footer_style = ParagraphStyle(
        name='FooterStyle',
        fontSize=9,
        leading=11,
        alignment=1,
        textColor=colors.grey,
        fontName='Helvetica-Oblique'
    )
    elements.append(Paragraph("Thank you for your business!", footer_style))
    elements.append(Spacer(1, 0.5*inch))  

    signature_data = [
        [Paragraph("Customer Signature: ____________________", signature_style), Paragraph("Supplier Signature: ____________________", signature_style)]
    ]
    signature_table = Table(signature_data, colWidths=[3*inch, 3*inch])
    signature_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(signature_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

@login_required
def rate_supplier(request, order_id=None):
    order = get_object_or_404(Order, id=order_id, customer=request.user, status='delivered')
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        rating = request.POST.get('rating')
        logger.info(f"Rating request for order {order_id}: {rating}")
        if rating and 1 <= int(rating) <= 5:
            try:
                ProductRating.objects.create(order=order, rating=int(rating))
                Notification.objects.create(
                    user=order.supplier,
                    message=f"New rating received for Order #{order.id} - {rating}/5",
                    notification_type='rating'
                )
                logger.info(f"Rating {rating} submitted for order {order_id}")
                return JsonResponse({'status': 'success', 'message': 'Rating submitted successfully.'})
            except Exception as e:
                logger.error(f"Error submitting rating: {str(e)}")
                return JsonResponse({'status': 'error', 'message': 'Error processing rating.'}, status=400)
        return JsonResponse({'status': 'error', 'message': 'Invalid rating value.'}, status=400)
    else:
        form = SupplierRatingForm(initial={'order_id': order.id})
        return render(request, 'rate_supplier.html', {'form': form, 'order': order})

@login_required
def dashboard(request):
    logger.info(f"Accessing dashboard for user {request.user.username}, role: {request.user.role}")
    if request.user.role == 'admin':
        customers = CustomUser.objects.filter(role='customer')
        suppliers = CustomUser.objects.filter(role='supplier')
        orders = Order.objects.all()
        ratings = ProductRating.objects.all()
        warehouses = Warehouse.objects.all()
        admin_requests = AdminRequest.objects.filter(status='pending')

        if request.method == 'POST':
            action = request.POST.get('action')
            if action in ['approve_admin', 'deny_admin']:
                request_id = request.POST.get('request_id')
                admin_request = get_object_or_404(AdminRequest, id=request_id, status='pending')
                try:
                    if action == 'approve_admin':
                        admin_request.user.is_active = True
                        admin_request.user.save()
                        admin_request.status = 'approved'
                        admin_request.reviewed_by = request.user
                        admin_request.reviewed_at = timezone.now()
                        admin_request.save()
                        messages.success(request, f'Admin request for {admin_request.user.username} approved.')
                        logger.info(f"Admin request for {admin_request.user.username} approved by {request.user.username}")
                    elif action == 'deny_admin':
                        admin_request.status = 'denied'
                        admin_request.reviewed_by = request.user
                        admin_request.reviewed_at = timezone.now()
                        admin_request.save()
                        admin_request.user.delete()  # Delete the user if denied
                        messages.success(request, f'Admin request for {admin_request.user.username} denied and user deleted.')
                        logger.info(f"Admin request for {admin_request.user.username} denied by {request.user.username}")
                except Exception as e:
                    messages.error(request, f'Error processing admin request: {str(e)}')
                    logger.error(f"Error processing admin request {request_id}: {str(e)}")
            elif action == 'delete':
                user_id = request.POST.get('user_id')
                try:
                    user = get_object_or_404(CustomUser, id=user_id)
                    user.delete()  # This will cascade delete related records
                    messages.success(request, f'User {user.username} and all associated records deleted successfully.')
                    logger.info(f"User {user.username} (ID: {user_id}) deleted by admin {request.user.username}")
                except Exception as e:
                    messages.error(request, f'Error deleting user: {str(e)}')
                    logger.error(f"Error deleting user {user_id}: {str(e)}")

        return render(request, 'dashboards/admin_dashboard.html', {
            'customers': customers,
            'suppliers': suppliers,
            'orders': orders,
            'ratings': ratings,
            'warehouses': warehouses,
            'admin_requests': admin_requests,
        })
    elif request.user.role == 'supplier':
        logger.info("Supplier user, rendering supplier dashboard directly")
        return supplier_dashboard(request)
    else:
        orders = Order.objects.filter(customer=request.user)
        shipped_orders = orders.filter(status='shipped')
        delivered_orders = orders.filter(status='delivered')
        notifications = Notification.objects.filter(user=request.user, is_read=False).order_by('-created_at')
        suppliers = CustomUser.objects.filter(role='supplier')

        logger.info(f"Rendering customer dashboard with {orders.count()} orders, {shipped_orders.count()} shipped, {delivered_orders.count()} delivered")
        if not orders.exists():
            messages.info(request, 'No orders found. Create an order to get started.')
        return render(request, 'dashboards/customer_dashboard.html', {
            'orders': orders,
            'shipped_orders': shipped_orders,
            'delivered_orders': delivered_orders,
            'receipt_form': ReceiptConfirmationForm(),
            'notifications': notifications,
            'suppliers': suppliers,
        })

@login_required
def supplier_dashboard(request):
    logger.info(f"Accessing supplier_dashboard for user {request.user.username}, role: {request.user.role}")
    if request.user.role != 'supplier':
        logger.warning(f"User {request.user.username} with role {request.user.role} attempted to access supplier_dashboard, redirecting to dashboard")
        return redirect('users:dashboard')

    orders = Order.objects.filter(supplier=request.user)
    order = None
    status_choices = Order.status.field.choices
    
    supplier = Supplier.objects.filter(user=request.user).first()
    avg_rating = supplier.average_rating() if supplier else 0
    
    notifications = Notification.objects.filter(user=request.user, is_read=False).order_by('-created_at')
    
    warehouses = Warehouse.objects.filter(product__supplier=request.user)
    
    delivered_orders = orders.filter(status='delivered')
    total_sales = decimal.Decimal('0.0')  
    for order in delivered_orders:
        if order.product is not None:
            
            quantity = decimal.Decimal(str(order.quantity))
            price = order.product.price  
            total_sales += quantity * price
        else:
            logger.warning(f"Order {order.id} has no associated product. Skipping in sales calculation.")

    gst_rate = decimal.Decimal('0.18')
    total_sales_with_gst = total_sales * (1 + gst_rate)
   
    cost_percentage = decimal.Decimal('0.70')
    total_cost = total_sales * cost_percentage
    total_profit = total_sales - total_cost

    end_date = now()
    start_date = end_date - timedelta(days=30)
    sales_data = []
    for i in range(30):
        day = start_date + timedelta(days=i)
        day_orders = delivered_orders.filter(order_date__date=day.date())
        day_sales = decimal.Decimal('0.0')  
        for order in day_orders:
            if order.product is not None:
               
                quantity = decimal.Decimal(str(order.quantity))
                price = order.product.price
                day_sales += quantity * price
            else:
                logger.warning(f"Order {order.id} on {day.date()} has no associated product. Skipping in daily sales.")
        sales_data.append(float(day_sales)) 

    
    forecast_demand(request.user)

    forecasts = DemandForecast.objects.filter(supplier=request.user).order_by('-forecast_date')[:10]

    order_id = request.GET.get('order_id') or request.POST.get('order_id')
    if order_id:
        order = get_object_or_404(Order, id=order_id, supplier=request.user)

    logger.info(f"Rendering supplier_dashboard for {request.user.username}")
    return render(request, 'dashboards/supplier_dashboard.html', {
        'orders': orders,
        'order': order,
        'status_choices': status_choices,
        'avg_rating': avg_rating,
        'notifications': notifications,
        'warehouses': warehouses,
        'total_sales': float(total_sales_with_gst),  
        'total_profit': float(total_profit),  
        'sales_data': sales_data,
        'forecasts': forecasts,
    })

@login_required
def edit_supplier(request, user_id):
    supplier_user = get_object_or_404(CustomUser, id=user_id, role='supplier')
    logger.info(f"Attempting to edit supplier for user_id: {user_id}, username: {supplier_user.username}, role: {supplier_user.role}")
    
    supplier, created = Supplier.objects.get_or_create(user=supplier_user)
    if created:
        logger.info(f"Created new Supplier object for user_id: {user_id}, username: {supplier_user.username}")
        messages.info(request, f"Created a new supplier profile for {supplier_user.username}. Please fill in the details.")
    
    logger.info(f"Supplier object found: {supplier}, created: {created}")
    
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, f'Supplier {supplier_user.username} updated successfully.')
            return redirect('users:dashboard')
        else:
            messages.error(request, 'Error updating supplier.')
            for error in form.errors.values():
                logger.error(f"Form error: {error}")
    else:
        form = SupplierForm(instance=supplier)
    
    return render(request, 'dashboards/edit_supplier.html', {
        'form': form,
        'supplier_user': supplier_user,
        'user_id': user_id
    })

@login_required
def edit_customer(request, user_id):
    customer_user = get_object_or_404(CustomUser, id=user_id, role='customer')
    if request.method == 'POST':
        form = CustomUserUpdateForm(request.POST, instance=customer_user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Customer {customer_user.username} updated successfully.')
            return redirect('users:dashboard')
        else:
            messages.error(request, 'Error updating customer.')
    else:
        form = CustomUserUpdateForm(instance=customer_user)
    return render(request, 'dashboards/edit_customer.html', {'form': form, 'user_id': user_id})

@login_required
def manage_warehouse(request):
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        action = request.POST.get('form_action')
        if action == 'add_product':
            product_name = request.POST.get('product_name')
            location = request.POST.get('location')
            stock_level = request.POST.get('stock_level')
            price = request.POST.get('price')

            if not all([product_name, location, stock_level, price]):
                message = "All fields are required: Product Name, Location, Initial Stock Level, and Price."
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': message})
                messages.error(request, message)
                return redirect('users:supplier_dashboard')

            try:
                stock_level = int(stock_level)
                price = float(price)
                if stock_level < 0:
                    raise ValueError("Stock level cannot be negative.")
                if price < 0:
                    raise ValueError("Price cannot be negative.")

                with transaction.atomic():
                    product = Product.objects.create(
                        name=product_name,
                        description="Default description",
                        price=price,
                        stock=stock_level,
                        supplier=request.user
                    )
                    warehouse = Warehouse.objects.create(
                        product=product,
                        location=location,
                        stock_level=stock_level,
                        last_updated=timezone.now()
                    )
                    product.stock = stock_level
                    product.save()

                message = f"Product '{product_name}' added successfully to warehouse at {location} with price ₹{price:.2f}!"
                if is_ajax:
                    return JsonResponse({'status': 'success', 'message': message})
                messages.success(request, message)
            except ValueError as ve:
                message = f"Invalid input: {str(ve)}"
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': message})
                messages.error(request, message)
            except Exception as e:
                message = f"Error adding product: {str(e)}"
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': message})
                messages.error(request, message)

        else:
            warehouse_id = request.POST.get('warehouse_id')
            refill_amount = request.POST.get('refill_amount')

            if not all([warehouse_id, refill_amount]):
                message = "Warehouse ID and refill amount are required."
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': message})
                messages.error(request, message)
                return redirect('users:supplier_dashboard')

            try:
                refill_amount = int(refill_amount)
                if refill_amount < 1:
                    raise ValueError("Refill amount must be at least 1.")
                
                with transaction.atomic():
                    warehouse = Warehouse.objects.get(id=warehouse_id, product__supplier=request.user)
                    warehouse.stock_level += refill_amount
                    warehouse.last_updated = timezone.now()
                    warehouse.save()
                    product = warehouse.product
                    total_stock = sum(w.stock_level for w in product.warehouse_stocks.all())
                    product.stock = total_stock
                    product.save()

                message = f"Stock refilled successfully for {warehouse.product.name} at {warehouse.location}!"
                if is_ajax:
                    return JsonResponse({'status': 'success', 'message': message})
                messages.success(request, message)
            except ValueError as ve:
                message = f"Invalid input: {str(ve)}"
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': message})
                messages.error(request, message)
            except Warehouse.DoesNotExist:
                message = "Warehouse not found or you don't have permission to modify it."
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': message})
                messages.error(request, message)
            except Exception as e:
                message = f"Error refilling stock: {str(e)}"
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': message})
                messages.error(request, message)

        return redirect('users:supplier_dashboard')

    return redirect('users:supplier_dashboard')

@login_required
def get_supplier_products(request, supplier_id):
    try:
        supplier = CustomUser.objects.get(id=supplier_id, role='supplier')
        warehouses = Warehouse.objects.filter(product__supplier=supplier, stock_level__gt=0)
        products = [
            {'id': warehouse.product.id, 'name': warehouse.product.name, 'stock': warehouse.stock_level}
            for warehouse in warehouses
        ]
        return JsonResponse({'products': products})
    except CustomUser.DoesNotExist:
        return JsonResponse({'products': []}, status=404)
    except Exception as e:
        return JsonResponse({'products': [], 'error': str(e)}, status=500)

@login_required
def track_orders(request):
    orders = Order.objects.filter(customer=request.user)
    return render(request, 'track_orders.html', {'orders': orders})

@login_required
def update_order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id, supplier=request.user)
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        new_status = request.POST.get('status')
        if new_status in dict(Order.status.field.choices):
            order.status = new_status
            order.save()
            Notification.objects.create(
                user=order.customer,
                message=f"Your order #{order.id} status updated to {new_status}.",
                notification_type='order_update'
            )
            message = f'Order {order_id} status updated to {new_status}.'
            if is_ajax:
                return JsonResponse({'status': 'success', 'message': message})
            messages.success(request, message)
        else:
            message = 'Invalid status.'
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message}, status=400)
            messages.error(request, message)
    return redirect('users:supplier_dashboard')

@login_required
def admin_activity(request):
    activity = []
    return render(request, 'admin_activity.html', {'activity': activity})

@login_required
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        notification.is_read = True
        notification.save()
        message = 'Notification marked as read.'
        if is_ajax:
            return JsonResponse({'status': 'success', 'message': message})
        messages.success(request, message)
    return redirect('users:supplier_dashboard')

def forecast_demand(supplier):
    """Generate demand forecasts for the supplier's products using a simple moving average."""
    end_date = now()
    start_date = end_date - timedelta(days=30)
    products = Product.objects.filter(supplier=supplier)

    for product in products:
    
        orders = Order.objects.filter(
            supplier=supplier,
            product=product,
            order_date__range=(start_date, end_date),
            status='delivered'
        )
        total_quantity = orders.aggregate(Sum('quantity'))['quantity__sum'] or 0
        # Simple moving average: total quantity / number of days
        if total_quantity > 0:
            daily_avg = total_quantity / 30
            forecasted_quantity = int(daily_avg * 30)  
        else:
            forecasted_quantity = 0

        DemandForecast.objects.create(
            product=product,
            supplier=supplier,
            forecasted_quantity=forecasted_quantity,
            period_days=30
        )