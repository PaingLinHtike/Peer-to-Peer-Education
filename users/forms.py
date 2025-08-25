from django import forms
from django.contrib.auth.hashers import make_password, check_password
import pymongo
from bson.objectid import ObjectId
import datetime
import os
import bcrypt
import re
from django.conf import settings # Import settings to get MEDIA_ROOT

def validate_password_strength(password, username=None, email=None):
    """
    Validate password strength based on security requirements.
    Returns a tuple (is_valid, error_message)
    """
    if not password:
        return False, "Password is required."
    
    # Check minimum length
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    
    # Check maximum length
    if len(password) > 128:
        return False, "Password must not exceed 128 characters."
    
    # Check for at least one uppercase letter
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter."
    
    # Check for at least one lowercase letter
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter."
    
    # Check for at least one digit
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number."
    
    # Check for at least one special character
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character (!@#$%^&*(),.?\":{}|<>)."
    
    # Check password doesn't match username (case insensitive)
    if username and password.lower() == username.lower():
        return False, "Password cannot be the same as your username."
    
    # Check password doesn't match email (case insensitive)
    if email:
        email_parts = email.lower().split('@')
        email_local = email_parts[0] if email_parts else ''
        if password.lower() == email.lower() or password.lower() == email_local:
            return False, "Password cannot be the same as your email or email username."
    
    # Check for common weak passwords
    common_passwords = [
        'password', 'password123', '123456789', 'qwerty123', 'admin123',
        'welcome123', 'Password1', 'Password123', 'Qwerty123', '12345678'
    ]
    if password.lower() in [p.lower() for p in common_passwords]:
        return False, "Password is too common. Please choose a more secure password."
    
    # Check for consecutive characters
    if re.search(r'(.)\1{2,}', password):
        return False, "Password cannot contain 3 or more consecutive identical characters."
    
    # Check for sequential characters (123, abc, etc.)
    sequential_patterns = [
        '123456', '234567', '345678', '456789', '567890',
        'abcdef', 'bcdefg', 'cdefgh', 'defghi', 'efghij',
        'qwerty', 'asdfgh', 'zxcvbn'
    ]
    password_lower = password.lower()
    for pattern in sequential_patterns:
        if pattern in password_lower or pattern[::-1] in password_lower:
            return False, "Password cannot contain sequential characters (like 123456 or abcdef)."
    
    return True, "Password is strong."

class InstructorRegistrationForm(forms.Form):
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    password1 = forms.CharField(widget=forms.PasswordInput, required=True)
    password2 = forms.CharField(widget=forms.PasswordInput, required=True, label="Confirm Password")
    profile_photo = forms.ImageField(required=False, help_text="Upload your profile photo.")
    specialization = forms.CharField(max_length=100, required=True)
    experience = forms.IntegerField(min_value=0, required=True)
    bio = forms.CharField(widget=forms.Textarea, required=True)
    is_otp_verified = forms.CharField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        username = cleaned_data.get('username')
        email = cleaned_data.get('email')
        is_otp_verified = cleaned_data.get('is_otp_verified')

        # Password confirmation check
        if password1 and password2 and password1 != password2:
            self.add_error('password2', "Passwords do not match.")

        # Strong password validation
        if password1:
            is_valid, error_message = validate_password_strength(password1, username, email)
            if not is_valid:
                self.add_error('password1', error_message)

        # Check if OTP was verified
        if is_otp_verified != 'true':
            self.add_error('email', "Please verify your email with OTP before registering.")

        connection = None
        try:
            connection = pymongo.MongoClient("localhost", 27017)
            db = connection["Peer_to_Peer_Education"]
            users_collection = db["users"]

            if users_collection.find_one({"username": cleaned_data.get('username')}):
                self.add_error('username', "This username is already taken.")
            if users_collection.find_one({"email": cleaned_data.get('email')}):
                self.add_error('email', "This email is already registered.")
        except Exception as e:
            self.add_error(None, f"Database error during validation: {e}")
        finally:
            if connection:
                connection.close()
        return cleaned_data

    def save(self, users_collection, profile_photo_path=None):
        username = self.cleaned_data['username']
        email = self.cleaned_data['email']
        password = self.cleaned_data['password1']  # Changed from 'password' to 'password1'
        specialization = self.cleaned_data.get('specialization', '')
        experience = self.cleaned_data.get('experience', 0)
        bio = self.cleaned_data.get('bio', '')

        final_profile_photo_path = profile_photo_path if profile_photo_path else 'users/default.jpg'
        
        # Use bcrypt to hash password (matching MongoDB structure)
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        hashed_password_str = hashed_password.decode('utf-8')

        # Get current UTC time
        current_time = datetime.datetime.utcnow()
        
        # Create user document with required structure matching MongoDB example
        user_doc = {
            "username": username,
            "email": email,
            "password": hashed_password_str,  # bcrypt hashed password
            "role": "instructor",
            "profile_photo": final_profile_photo_path,
            "is_active": True,
            "is_staff": False,
            "date_joined": current_time,
            "last_login": current_time,
            "specialization": specialization,
            "experience": experience,
            "bio": bio
        }
        
        # Insert the document and return the ObjectId
        result = users_collection.insert_one(user_doc)
        return result.inserted_id

class StudentRegistrationForm(forms.Form):
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)
    confirm = forms.CharField(widget=forms.PasswordInput, required=True, label="Confirm Password")
    profile_photo = forms.ImageField(required=True, help_text="Upload your profile photo.")
    is_otp_verified = forms.CharField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm = cleaned_data.get('confirm')
        username = cleaned_data.get('username')
        email = cleaned_data.get('email')
        is_otp_verified = cleaned_data.get('is_otp_verified')

        # Password confirmation check
        if password and confirm and password != confirm:
            self.add_error('confirm', "Passwords do not match.")

        # Strong password validation
        if password:
            is_valid, error_message = validate_password_strength(password, username, email)
            if not is_valid:
                self.add_error('password', error_message)

        # Check if email is verified
        if is_otp_verified != 'true':
            self.add_error('email', "Please verify your email with OTP before registering.")

        connection = None
        try:
            connection = pymongo.MongoClient("localhost", 27017)
            db = connection["Peer_to_Peer_Education"]
            users_collection = db["users"]

            if users_collection.find_one({"username": cleaned_data.get('username')}):
                self.add_error('username', "This username is already taken.")
            if users_collection.find_one({"email": cleaned_data.get('email'), "role": "student"}):
                self.add_error('email', "This email is already registered.")
        except Exception as e:
            self.add_error(None, f"Database error during validation: {e}")
        finally:
            if connection:
                connection.close()
        return cleaned_data

    def save(self, users_collection, profile_photo_path=None):
        username = self.cleaned_data['username']
        email = self.cleaned_data['email']
        password = self.cleaned_data['password']

        final_profile_photo_path = profile_photo_path if profile_photo_path else 'users/default.jpg'
        
        # Use bcrypt to hash password (matching MongoDB structure)
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        hashed_password_str = hashed_password.decode('utf-8')

        # Get current UTC time
        current_time = datetime.datetime.utcnow()
        
        # Create user document with required structure
        user_doc = {
            "username": username,
            "email": email,
            "password": hashed_password_str,  # bcrypt hashed password
            "role": "student",
            "profile_photo": final_profile_photo_path,
            "is_active": True,
            "is_staff": False,
            "date_joined": current_time,
            "last_login": current_time
        }
        
        # Insert the document and return the ObjectId
        result = users_collection.insert_one(user_doc)
        return result.inserted_id

class InstructorProfileForm(forms.Form):
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    description = forms.CharField(widget=forms.Textarea, required=False, help_text="Provide a brief description of your expertise.")
    profile_photo = forms.ImageField(required=False, help_text="Upload a new profile photo.")

    def __init__(self, *args, **kwargs):
        self.user_id = kwargs.pop('user_id', None)
        self.users_collection = kwargs.pop('users_collection', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()

        if self.users_collection is None:
            self.add_error(None, "Users collection not provided to form.")
            return cleaned_data

        username = cleaned_data.get('username')
        email = cleaned_data.get('email')

        connection = None
        try:
            connection = pymongo.MongoClient("localhost", 27017)
            db = connection["Peer_to_Peer_Education"]
            users_collection_for_validation = db['users']

            if username:
                existing_user_by_username = users_collection_for_validation.find_one(
                    {"username": username, "_id": {"$ne": ObjectId(self.user_id)}}
                )
                if existing_user_by_username:
                    self.add_error('username', "This username is already taken by another user.")

            if email:
                existing_user_by_email = users_collection_for_validation.find_one(
                    {"email": email, "_id": {"$ne": ObjectId(self.user_id)}}
                )
                if existing_user_by_email:
                    self.add_error('email', "This email is already taken by another user.")
        except Exception as e:
            self.add_error(None, f"Database error during validation: {e}")
        finally:
            if connection:
                connection.close()
        return cleaned_data

    def save(self, profile_photo_path=None):
        if self.users_collection is None:
            raise Exception("Users collection not provided for profile update.")
        if self.user_id is None:
            raise Exception("User ID not provided for profile update.")

        update_data = {
            "username": self.cleaned_data['username'],
            "email": self.cleaned_data['email'],
            "description": self.cleaned_data.get('description', ''),
        }
        if profile_photo_path:
            update_data["profile_photo"] = profile_photo_path

        self.users_collection.update_one({"_id": ObjectId(self.user_id)}, {"$set": update_data})
        return True

class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(required=True, label="Enter your email address")

    def clean_email(self):
        email = self.cleaned_data['email']
        connection = None
        try:
            connection = pymongo.MongoClient("localhost", 27017)
            db = connection["Peer_to_Peer_Education"]
            users_collection = db['users']
            if users_collection is not None and not users_collection.find_one({"email": email, "role": "instructor"}):
                raise forms.ValidationError("No instructor account found with this email address.")
        except Exception as e:
            raise forms.ValidationError(f"Database error during validation: {e}")
        finally:
            if connection:
                connection.close()
        return email

class AdminProfileForm(forms.Form):
    username = forms.CharField(max_length=150, required=True, label="Username")
    email = forms.EmailField(required=True, label="Email Address")
    current_password = forms.CharField(widget=forms.PasswordInput, required=True, label="Current Password")
    new_password = forms.CharField(widget=forms.PasswordInput, required=False, label="New Password (Optional)")
    confirm_password = forms.CharField(widget=forms.PasswordInput, required=False, label="Confirm New Password")
    profile_photo = forms.ImageField(required=False, help_text="Upload a new profile photo (optional)")

    def __init__(self, *args, **kwargs):
        self.admin_id = kwargs.pop('admin_id', None)
        self.current_admin_data = kwargs.pop('current_admin_data', None)
        super().__init__(*args, **kwargs)
        
        # Pre-populate fields if current data is provided
        if self.current_admin_data:
            self.fields['username'].initial = self.current_admin_data.get('username', '')
            self.fields['email'].initial = self.current_admin_data.get('email', '')

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        email = cleaned_data.get('email')
        current_password = cleaned_data.get('current_password')
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        # Password validation
        if new_password or confirm_password:
            if new_password != confirm_password:
                self.add_error('confirm_password', "New passwords do not match.")
            
            # Apply strong password validation to new password
            if new_password:
                is_valid, error_message = validate_password_strength(new_password, username, email)
                if not is_valid:
                    self.add_error('new_password', error_message)

        # Verify current password
        if current_password and self.current_admin_data:
            import bcrypt
            stored_password = self.current_admin_data.get('password', '')
            if not bcrypt.checkpw(current_password.encode('utf-8'), stored_password.encode('utf-8')):
                self.add_error('current_password', "Current password is incorrect.")

        # Check uniqueness (exclude current admin)
        connection = None
        try:
            connection = pymongo.MongoClient("localhost", 27017)
            db = connection["Peer_to_Peer_Education"]
            users_collection = db["users"]

            if username and self.admin_id:
                existing_user_by_username = users_collection.find_one({
                    "username": username, 
                    "_id": {"$ne": ObjectId(self.admin_id)}
                })
                if existing_user_by_username:
                    self.add_error('username', "This username is already taken by another user.")

            if email and self.admin_id:
                existing_user_by_email = users_collection.find_one({
                    "email": email, 
                    "_id": {"$ne": ObjectId(self.admin_id)}
                })
                if existing_user_by_email:
                    self.add_error('email', "This email is already taken by another user.")
        except Exception as e:
            self.add_error(None, f"Database error during validation: {e}")
        finally:
            if connection:
                connection.close()
        
        return cleaned_data

    def save(self, users_collection, profile_photo_path=None):
        """Save the admin profile updates to the database"""
        if not self.admin_id:
            raise ValueError("Admin ID is required to save profile.")
        
        username = self.cleaned_data['username']
        email = self.cleaned_data['email']
        new_password = self.cleaned_data.get('new_password')

        # Prepare update data
        update_data = {
            "username": username,
            "email": email
        }

        # Update password if provided
        if new_password:
            hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
            update_data["password"] = hashed_password.decode('utf-8')

        # Update profile photo if provided
        if profile_photo_path:
            update_data["profile_photo"] = profile_photo_path

        # Update the admin record in database
        result = users_collection.update_one(
            {"_id": ObjectId(self.admin_id)},
            {"$set": update_data}
        )
        
        return result.modified_count > 0
