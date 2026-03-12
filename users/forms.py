from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, Order, Supplier, Warehouse, Product

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'role')

class CustomUserUpdateForm(forms.ModelForm):
    new_password = forms.CharField(widget=forms.PasswordInput(), required=False, label="New Password", help_text="Leave blank if you don't want to change the password.")
    confirm_password = forms.CharField(widget=forms.PasswordInput(), required=False, label="Confirm New Password")

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'location']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            self.fields['role'] = forms.CharField(initial=instance.role, widget=forms.TextInput(attrs={'readonly': 'readonly'}))

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password or confirm_password:
            if not new_password or not confirm_password:
                raise forms.ValidationError("Both new password and confirmation are required if changing password.")
            if new_password != confirm_password:
                raise forms.ValidationError("The two password fields didn't match.")
            if len(new_password) < 8:
                raise forms.ValidationError("Password must be at least 8 characters long.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get("new_password")
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
        return user

class OrderForm(forms.ModelForm):
    supplier = forms.ModelChoiceField(queryset=CustomUser.objects.filter(role='supplier'))
    product = forms.ModelChoiceField(queryset=Product.objects.none(), required=True, label="Product")
    quantity = forms.IntegerField(min_value=1, required=True)
    destination = forms.CharField(max_length=255, label="Delivery Destination", required=True)

    class Meta:
        model = Order
        fields = ['supplier', 'product', 'quantity', 'destination']

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)  
        super().__init__(*args, **kwargs)
        self.fields['supplier'].queryset = CustomUser.objects.filter(role='supplier')
        
        if 'supplier' in self.data:
            try:
                supplier_id = int(self.data.get('supplier'))
                supplier = CustomUser.objects.get(id=supplier_id, role='supplier')
                
                self.fields['product'].queryset = Product.objects.filter(
                    supplier=supplier,
                    warehouse_stocks__stock_level__gt=0
                ).distinct()
            except (ValueError, TypeError, CustomUser.DoesNotExist):
                self.fields['product'].queryset = Product.objects.none()
        else:
            self.fields['product'].queryset = Product.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        quantity = cleaned_data.get('quantity')
        supplier = cleaned_data.get('supplier')

        if product and quantity and supplier:
            
            try:
                warehouse = Warehouse.objects.get(product=product, product__supplier=supplier)
                if warehouse.stock_level < quantity:
                    # If requested quantity exceeds stock, raise a validation error with available quantity
                    raise forms.ValidationError(
                        f"Insufficient stock for {product.name}. Available quantity: {warehouse.stock_level}."
                    )
            except Warehouse.DoesNotExist:
                raise forms.ValidationError(
                    f"The product {product.name} is not available in {supplier.username}'s warehouse."
                )

        return cleaned_data

class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'contact_info', 'rating', 'location']

class SupplierRatingForm(forms.Form):
    order_id = forms.IntegerField(label="Order ID", widget=forms.Select(choices=[]))
    rating = forms.IntegerField(label="Rating", min_value=1, max_value=5)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['order_id'].widget.choices = [(order.id, f"{order.id} - {order.supplier.username}") for order in Order.objects.filter(status='delivered')]

class ReceiptConfirmationForm(forms.Form):
    confirm = forms.BooleanField(label="Confirm Receipt", required=True, initial=False, widget=forms.CheckboxInput())
    
class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['product', 'location', 'stock_level']