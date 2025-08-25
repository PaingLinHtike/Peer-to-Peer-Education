from django.conf import settings
from django.utils import timezone
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.core.mail import send_mail
from django.contrib import messages
import pymongo
import datetime
import random
from django.core.files.storage import default_storage
from bson.objectid import ObjectId
from pymongo import MongoClient
from django.contrib import messages
from passlib.hash import bcrypt
import os
import bcrypt
from django.http import JsonResponse
import json
from dashboard.views import log_user_activity

connection = pymongo.MongoClient("localhost", 27017)
db = connection["Peer_to_Peer_Education"]
users_collection = db["users"]
courses_col = db["courses"]
users_col = db["users"]
payments_col = db["payments"]
enrollments_col = db["enrollments"]
reviews_col = db["reviews"]

# Home Page View
def home(request):
    """Render the home page with available courses"""
    # Get all approved and available courses for display
    course_query = {
        "status": "approved",
        "$or": [
            {"is_available": {"$exists": False}},  # Courses created before ban feature
            {"is_available": True}  # Courses explicitly available
        ]
    }
    
    courses_raw = courses_col.find(course_query).limit(6)  # Limit to 6 courses for home page
    courses = []
    
    for course in courses_raw:
        instructor = users_col.find_one({"_id": course["instructor_id"]}, {"username": 1})
        
        # Calculate dynamic rating from reviews
        avg_rating = calculate_course_rating(str(course["_id"]))
        
        course_data = {
            "id": str(course["_id"]),
            "title": course["title"],
            "category": course["category"],
            "price": course["price"],
            "photo": course["course_photo"],
            "rating": avg_rating,
            "description": course.get("description", "No description available"),
            "instructor": instructor.get("username", "Unknown") if instructor else "Unknown"
        }
        courses.append(course_data)
    
    return render(request, "users/home.html", {
        "courses": courses
    })

# Admin Part

# Admin Login
@csrf_protect
def admin_login(request):
    if request.method == "POST":
        user_name = request.POST.get("user_name", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "").strip()
        user = users_collection.find_one({
            "username": user_name,
            "email": email,
            "role": "admin"
        })
        if user:
            # Verify password using bcrypt
            stored_password = user.get("password")
            if stored_password and bcrypt.checkpw(password.encode(), stored_password.encode("utf-8")):
                # Password is correct - login successful
                request.session['admin_name'] = user.get("username", "")
                request.session['admin_email'] = user.get("email", "")
                request.session['admin_photo'] = user.get("profile_photo", "")
                return redirect('dashboard_home')
            else:
                # Password is incorrect
                return render(request, "users/admin_login.html", {"popup": "Invalid password"})
        else:
            # User not found
            return render(request, "users/admin_login.html", {"popup": "Admin user not found"})
    
    return render(request, "users/admin_login.html")

# Admin Profile View
@csrf_protect
def admin_profile_view(request):
    """Display admin profile information"""
    if not request.session.get('admin_name'):
        return redirect('admin_login')
    
    try:
        admin_name = request.session.get('admin_name')
        admin_email = request.session.get('admin_email')
        
        # Get current admin data from database
        admin_data = users_collection.find_one({
            "username": admin_name,
            "email": admin_email,
            "role": "admin"
        })
        
        if not admin_data:
            return redirect('admin_login')
        
        context = {
            'admin_data': admin_data,
            'admin_name': admin_name,
            'admin_email': admin_email,
            'admin_photo': request.session.get('admin_photo', '')
        }
        
        return render(request, 'users/admin_profile.html', context)
    
    except Exception as e:
        return HttpResponse(f"Error loading profile: {e}", status=500)

# Admin Edit Profile
@csrf_protect  
def admin_edit_profile(request):
    """Handle admin profile editing"""
    if not request.session.get('admin_name'):
        return redirect('admin_login')
    
    try:
        from .forms import AdminProfileForm
        
        admin_name = request.session.get('admin_name')
        admin_email = request.session.get('admin_email')
        
        # Get current admin data
        admin_data = users_collection.find_one({
            "username": admin_name,
            "email": admin_email,
            "role": "admin"
        })
        
        if not admin_data:
            return redirect('admin_login')
        
        admin_id = str(admin_data['_id'])
        
        if request.method == 'POST':
            form = AdminProfileForm(
                request.POST, 
                request.FILES,
                admin_id=admin_id,
                current_admin_data=admin_data
            )
            
            if form.is_valid():
                # Handle profile photo upload
                profile_photo_path = None
                if 'profile_photo' in request.FILES:
                    photo = request.FILES['profile_photo']
                    photo_name = f"admin_{admin_id}_{photo.name}"
                    photo_path = f"users/{photo_name}"
                    full_path = os.path.join(settings.MEDIA_ROOT, photo_path)
                    
                    # Create directory if it doesn't exist
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    
                    # Save the file
                    with open(full_path, 'wb') as f:
                        for chunk in photo.chunks():
                            f.write(chunk)
                    
                    profile_photo_path = photo_path
                
                try:
                    # Save the profile updates
                    success = form.save(users_collection, profile_photo_path)
                    
                    if success:
                        # Update session data with new values
                        request.session['admin_name'] = form.cleaned_data['username']
                        request.session['admin_email'] = form.cleaned_data['email']
                        if profile_photo_path:
                            request.session['admin_photo'] = profile_photo_path
                        
                        # Log the profile update activity
                        log_user_activity(
                            user_id=ObjectId(admin_id),
                            username=form.cleaned_data['username'],
                            role="admin",
                            action="✏️ Admin profile updated",
                            performed_by="system"
                        )
                        
                        messages.success(request, "Profile updated successfully!")
                        return redirect('admin_profile')
                    else:
                        form.add_error(None, "Failed to update profile. Please try again.")
                
                except Exception as e:
                    # Clean up uploaded photo if database save fails
                    if profile_photo_path and os.path.exists(os.path.join(settings.MEDIA_ROOT, profile_photo_path)):
                        os.remove(os.path.join(settings.MEDIA_ROOT, profile_photo_path))
                    form.add_error(None, f"Error updating profile: {str(e)}")
        else:
            form = AdminProfileForm(
                admin_id=admin_id,
                current_admin_data=admin_data
            )
        
        context = {
            'form': form,
            'admin_data': admin_data,
            'admin_name': admin_name,
            'admin_email': admin_email,
            'admin_photo': request.session.get('admin_photo', '')
        }
        
        return render(request, 'users/admin_edit_profile.html', context)
    
    except Exception as e:
        return HttpResponse(f"Error loading edit profile: {e}", status=500)

# Admin Logout
def admin_logout(request):
    request.session.flush()  # Clear all session data
    return redirect('admin_login')  # Redirect to login page

# User Table
@csrf_protect
def admin_page(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')
    instructor_count = users_collection.count_documents({"role": "instructor"})
    student_count = users_collection.count_documents({"role": "student"})
    users = []
    search_query = ''
    role_filter = ''
    query = {
    "role": {"$ne": "admin"},
    "is_active": True
}
  # ✅ exclude admin always
    if request.method == "POST":
        search_query = request.POST.get('search_query', '').strip()
        role_filter = request.POST.get('role_filter', '').strip()
        if role_filter:
            query["role"] = role_filter
        if search_query:
            query["$or"] = [
                {"username": {"$regex": search_query, "$options": "i"}},
                {"email": {"$regex": search_query, "$options": "i"}}
            ]
    projection = {
        "_id": 0,
        "username": 1,
        "email": 1,
        "role": 1,
        "is_active": 1
    }
    users = list(users_collection.find(query, projection))
    return render(request, 'users/user_list.html', {
        'instructor_count': instructor_count,
        'student_count': student_count,
        'users': users,
        'search_query': search_query,
        'role_filter': role_filter,
        'admin_name': request.session.get('admin_name', ''),
        'admin_photo': request.session.get('admin_photo', ''),
    })

# View User
def view_user(request, username):
    user = users_collection.find_one({"username": username}, {"_id": 0})
    if not user:
        return HttpResponse("User not found", status=404)

    # Add dummy data
    user["num_courses"] = 3  # Dummy
    user["enrolled_students"] = 42  # Dummy
    user["reports"] = 1  # Dummy
    return render(request, "users/user_profile.html", {"user": user})

# Ban User
@csrf_exempt
@csrf_protect
def ban_user(request, username):
    user = users_collection.find_one({"username": username})
    if not user:
        return HttpResponse("User not found", status=404)
    if request.method == "POST":
        # ✅ Log activity with user info (not just ID)
        db["user_activity_logs"].insert_one({
            "user_id": user["_id"],  # still store ID, in case needed
            "username": user["username"],
            "role": user["role"],
            "action": f"❌ {user['username']} ({user['role']}) was banned.",
            "performed_by": request.session.get("admin_name", "admin"),
            "timestamp": datetime.datetime.utcnow()
        })
        
        # Special handling for instructor ban
        if user["role"] == "instructor":
            # Get instructor's courses
            instructor_courses = list(courses_col.find({"instructor_id": user["_id"]}))
            
            # Get enrolled students for notification
            enrolled_students = []
            for course in instructor_courses:
                course_enrollments = list(enrollments_col.find({
                    "course_id": course["_id"],
                    "approval_status": "Approved"
                }))
                for enrollment in course_enrollments:
                    student = users_collection.find_one({"_id": enrollment["student_id"]})
                    if student:
                        enrolled_students.append({
                            "email": student["email"],
                            "username": student["username"],
                            "course_title": course["title"]
                        })
            
            # Mark instructor courses as unavailable (soft delete)
            courses_col.update_many(
                {"instructor_id": user["_id"]},
                {"$set": {"is_available": False, "banned_at": datetime.datetime.utcnow()}}
            )
            
            # Send notifications to enrolled students
            for student_info in enrolled_students:
                try:
                    send_mail(
                        subject=f"Important Notice: Course '{student_info['course_title']}' Access Update",
                        message=f"""Dear {student_info['username']},

We regret to inform you that the instructor for your enrolled course '{student_info['course_title']}' has been banned from our platform due to policy violations.

As a result:
- The course is no longer available for new enrollments
- You can still download and access all course materials you were enrolled in
- Your enrollment status remains valid for downloading purposes

You can download your course materials from your student dashboard.

We apologize for any inconvenience caused.

Best regards,
Peer to Peer Education Team""",
                        from_email=settings.EMAIL_HOST_USER,
                        recipient_list=[student_info["email"]],
                        fail_silently=True
                    )
                except Exception as e:
                    print(f"Failed to send email to {student_info['email']}: {e}")
        
        # ✅ Update user status to banned instead of deleting
        users_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"is_active": False}}
        )
        
        # Send ban notification to the user
        send_mail(
            subject="🚫 Account Banned from Peer to Peer Education",
            message="Your account has been banned due to policy violations. You can no longer access the platform.",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user["email"]],
            fail_silently=False
        )
        
        success_message = f"{user['username']}'s account has been banned and notified via email."
        if user["role"] == "instructor":
            course_count = courses_col.count_documents({"instructor_id": user["_id"]})
            student_count = len(enrolled_students)
            success_message += f" {course_count} courses have been made unavailable and {student_count} enrolled students have been notified."
        
        return render(request, "users/action_success.html", {
            "message": success_message
        })
    return render(request, "users/ban_user.html", {"user": user})

# Unban User
@csrf_exempt
@csrf_protect
def unban_user(request, username):
    user = users_collection.find_one({"username": username})
    if not user:
        return HttpResponse("User not found", status=404)
    if request.method == "POST":
        # ✅ Log activity with user info
        db["user_activity_logs"].insert_one({
            "user_id": user["_id"],
            "username": user["username"],
            "role": user["role"],
            "action": f"✅ {user['username']} ({user['role']}) was unbanned.",
            "performed_by": request.session.get("admin_name", "admin"),
            "timestamp": datetime.datetime.utcnow()
        })
        # ✅ Update user status to active
        users_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"is_active": True}}
        )
        send_mail(
            subject="✅ Account Reactivated - Peer to Peer Education",
            message="Your account has been reactivated. You can now access the platform again.",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user["email"]],
            fail_silently=False
        )
        return render(request, "users/action_success.html", {
            "message": f"{user['username']}'s account has been reactivated and notified via email."
        })
    return render(request, "users/unban_user.html", {"user": user})

# Warning User
@csrf_protect
@csrf_protect
def warn_user(request, username):
    user = users_collection.find_one({"username": username})
    if not user:
        return HttpResponse("User not found", status=404)
    if request.method == "POST":
        message = request.POST.get("message", "").strip()
        send_mail(
            subject=f"⚠️ Warning from Peer to Peer Education",
            message=message,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user["email"]],
            fail_silently=False
        )
        db["user_activity_logs"].insert_one({
            "user_id": user["_id"],
            "action": f"⚠️ Warning sent to {user['username']} ({user['role']})",
            "role": user["role"],
            "performed_by": request.session.get("admin_name", "admin"),
            "timestamp": datetime.datetime.utcnow()
        })
        return render(request, "users/action_success.html", {
            "message": f"Warning sent to {user['username']} successfully!"
        })
    return render(request, "users/warning_user.html", {"user": user})


# Student Part

# Student Registration
def student_register(request):
    from .forms import StudentRegistrationForm
    
    if request.method == "POST":
        form = StudentRegistrationForm(request.POST, request.FILES)
        
        # Set OTP verification status from session
        email = request.POST.get("email", "").strip()
        if request.session.get("verified_email") == email:
            form.data = form.data.copy()
            form.data['is_otp_verified'] = 'true'
        
        if form.is_valid():
            # Handle profile photo upload
            photo = form.cleaned_data.get('profile_photo')
            profile_photo_path = None
            
            if photo:
                photo_path = f"users/{photo.name}"
                full_path = os.path.join(settings.MEDIA_ROOT, photo_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "wb") as f:
                    for chunk in photo.chunks():
                        f.write(chunk)
                profile_photo_path = photo_path

            try:
                # Save user using form's save method
                result = form.save(users_collection, profile_photo_path)
                
                # Log the new user registration
                log_user_activity(
                    user_id=result,
                    username=form.cleaned_data['username'],
                    role="student",
                    action="🆕 New student account created",
                    performed_by="system"
                )
                
                # Clear verified email session
                if 'verified_email' in request.session:
                    del request.session['verified_email']
                
                return redirect("student_login")
            except Exception as e:
                # Clean up uploaded photo if save fails
                if profile_photo_path and os.path.exists(os.path.join(settings.MEDIA_ROOT, profile_photo_path)):
                    os.remove(os.path.join(settings.MEDIA_ROOT, profile_photo_path))
                form.add_error(None, f"Registration failed: {str(e)}")
    else:
        form = StudentRegistrationForm()

    return render(request, "users/student_register.html", {"form": form})

# Check if email exists for instructors
def check_instructor_email(request):
    email = request.GET.get("email")
    
    # Check if email already exists for any user (student or instructor)
    if users_collection.find_one({"email": email}):
        return JsonResponse({"status": "exists", "message": "This email is already registered."})
    
    return JsonResponse({"status": "available", "message": "Email is available."})

# Check instructor email availability
def check_instructor_email(request):
    email = request.GET.get("email")
    if users_collection.find_one({"email": email, "role": "instructor"}):
        return JsonResponse({"status": "exists", "message": "This email is already registered."})
    return JsonResponse({"status": "available"})

# OTP Sender for instructors
def send_instructor_otp(request):
    email = request.GET.get("email")

    # ✅ Block if email already exists
    if users_collection.find_one({"email": email}):
        return JsonResponse({"status": "exists", "message": "This email is already registered."})

    otp = str(random.randint(100000, 999999))
    request.session["instructor_otp"] = otp
    request.session["instructor_otp_email"] = email

    send_mail(
        subject="Your OTP Code - Instructor Registration",
        message=f"Use this OTP to verify your email for instructor registration: {otp}",
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[email],
        fail_silently=False,
    )
    return JsonResponse({"status": "sent"})

# Verify OTP for instructors
def verify_instructor_otp(request):
    user_otp = request.GET.get("otp")
    if user_otp == request.session.get("instructor_otp"):
        request.session["verified_instructor_email"] = request.session.get("instructor_otp_email")
        return JsonResponse({"status": "verified"})
    return JsonResponse({"status": "failed"})

# OTP Sender for students
def send_otp(request):
    email = request.GET.get("email")

    # ✅ Block if email already exists
    if users_collection.find_one({"email": email, "role": "student"}):
        return JsonResponse({"status": "exists", "message": "This email is already registered."})

    otp = str(random.randint(100000, 999999))
    request.session["otp"] = otp
    request.session["otp_email"] = email

    send_mail(
        subject="Your OTP Code",
        message=f"Use this OTP to verify your email: {otp}",
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[email],
        fail_silently=False,
    )
    return JsonResponse({"status": "sent"})

# Verify OTP
def verify_otp(request):
    user_otp = request.GET.get("otp")
    stored_otp = request.session.get("otp")
    
    if not user_otp:
        return JsonResponse({"status": "failed", "message": "Please enter the OTP code"})
        
    if not stored_otp:
        return JsonResponse({"status": "failed", "message": "No OTP found. Please request a new OTP."})
        
    if user_otp == stored_otp:
        request.session["verified_email"] = request.session.get("otp_email")
        # Clear the OTP after successful verification to prevent reuse
        request.session["otp"] = None
        return JsonResponse({"status": "verified", "message": "Email verified successfully!"})
        
    return JsonResponse({"status": "failed", "message": "Invalid OTP code. Please try again."})

# Student Logout
def student_logout(request):
    if request.session.get("student_id"):
        # Log logout before clearing session
        try:
            user = users_collection.find_one({"_id": ObjectId(request.session["student_id"])})
            if user:
                log_user_activity(
                    user_id=user["_id"],
                    username=user["username"],
                    role="student",
                    action="🚪 Student logged out",
                    performed_by="system"
                )
        except:
            pass  # Don't fail logout if logging fails
    
    request.session.flush()
    return redirect("student_login")

# Student Login
def student_login(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        # Check for exact match of username, email, and password
        user = users_collection.find_one({
            "username": username,
            "email": email,
            "role": "student",
            "is_active": True
        })

        if user:
            db_password = user["password"]
            if bcrypt.checkpw(password.encode(), db_password.encode("utf-8")):
                # Save session and redirect
                request.session["student_id"] = str(user["_id"])
                request.session["student_name"] = user["username"]
                request.session["student_email"] = user["email"]
                request.session["student_photo"] = user["profile_photo"]

                # Log successful login
                log_user_activity(
                    user_id=user["_id"],
                    username=user["username"],
                    role="student",
                    action="🔐 Student logged in",
                    performed_by="system"
                )

                return redirect("student_dashboard")

        return render(request, "users/student_login.html", {
            "error": "Invalid credentials. Please check your username, email, or password."
        })

    return render(request, "users/student_login.html")

# Helper function to calculate average rating for a course
def calculate_course_rating(course_id):
    """Calculate average rating for a course from reviews collection"""
    try:
        ratings = list(reviews_col.find({"course_id": ObjectId(course_id)}))
        if ratings:
            avg_rating = round(sum(r["rating"] for r in ratings) / len(ratings), 1)
            return avg_rating
        return 0.0
    except Exception as e:
        print(f"Error calculating rating for course {course_id}: {e}")
        return 0.0

# Student Dashboard
def student_dashboard(request):
    if not request.session.get("student_id"):
        return redirect("student_login")

    student_id = ObjectId(request.session["student_id"])

    # Get enrolled course IDs for this student
    enrolled_course_ids = [
        str(e["course_id"]) for e in enrollments_col.find({"student_id": student_id})
    ]

    # Category filter handling
    selected_category = request.GET.get("category", "").strip()
    course_query = {
        "status": "approved",
        "$or": [
            {"is_available": {"$exists": False}},  # Courses created before ban feature
            {"is_available": True}  # Courses explicitly available
        ]
    }
    if selected_category:
        course_query["category"] = selected_category

    # Distinct categories list for filter dropdown
    categories_query = {
        "status": "approved",
        "$or": [
            {"is_available": {"$exists": False}},
            {"is_available": True}
        ]
    }
    categories = sorted([c for c in courses_col.distinct("category", categories_query) if c])

    courses_raw = courses_col.find(course_query)
    courses = []
    for course in courses_raw:
        instructor = users_col.find_one({"_id": course["instructor_id"]}, {"username": 1})
        
        # Calculate dynamic rating from reviews
        avg_rating = calculate_course_rating(course["_id"])
        
        course_data = {
            "id": str(course["_id"]),
            "title": course["title"],
            "category": course["category"],
            "price": course["price"],
            "photo": course["course_photo"],
            "rating": avg_rating,  # Use calculated rating instead of hardcoded
            "description": course.get("description", "No description available"),
            "instructor": instructor.get("username", "Unknown") if instructor else "Unknown"
        }
        courses.append(course_data)

    return render(request, "users/student_dashboard.html", {
        "student_name": request.session.get("student_name"),
        "student_email": request.session.get("student_email"),
        "profile_photo": request.session.get("student_photo"),
        "courses": courses,
        "enrolled_course_ids": enrolled_course_ids,
        "categories": categories,
        "selected_category": selected_category,
    })

# Edit Student Profile - add logging
@csrf_protect
def edit_student_profile(request):
    if not request.session.get("student_id"):
        return redirect("student_login")

    student_id = request.session["student_id"]
    student = users_collection.find_one({"_id": ObjectId(student_id)})

    if not student:
        return redirect("student_login")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm", "")
        photo = request.FILES.get("profile_photo")

        # Password check
        if password and password != confirm:
            return render(request, "users/edit_student_profile.html", {
                "student": student,
                "error": "Passwords do not match."
            })

        # Check email change
        email_changed = (email != student["email"])
        if email_changed:
            if request.session.get("verified_email") != email:
                return render(request, "users/edit_student_profile.html", {
                    "student": student,
                    "error": "Please verify your email before saving."
                })

        # Prepare update data
        update_data = {
            "username": username,
            "email": email
        }

        # Update password if provided
        if password:
            hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
            update_data["password"] = hashed_pw.decode()

        # Update profile photo if provided
        if photo:
            photo_path = f"users/{photo.name}"
            full_path = os.path.join(settings.MEDIA_ROOT, photo_path)
            with open(full_path, "wb") as f:
                for chunk in photo.chunks():
                    f.write(chunk)
            update_data["profile_photo"] = photo_path
            request.session["student_photo"] = photo_path

        # Save changes
        users_collection.update_one({"_id": ObjectId(student_id)}, {"$set": update_data})

        # Log profile update
        log_user_activity(
            user_id=ObjectId(student_id),
            username=username,
            role="student",
            action="✏️ Student profile updated",
            performed_by="system"
        )

        # Update session data
        request.session["student_name"] = username
        request.session["student_email"] = email
        if "profile_photo" in update_data:
            request.session["student_photo"] = update_data["profile_photo"]

        return redirect("student_dashboard")

    return render(request, "users/edit_student_profile.html", {"student": student})

# Student Enroll
from django.shortcuts import get_object_or_404
from bson import ObjectId

payments_col = db["payments"]
enrollments_col = db["enrollments"]
reviews_col = db["reviews"]

# Enroll Course - add logging
def enroll_course(request, course_id):
    if not request.session.get("student_id"):
        return redirect("student_login")

    course = courses_col.find_one({"_id": ObjectId(course_id)})
    if not course:
        return redirect("student_dashboard")

    # Calculate average rating using helper function
    avg_rating = calculate_course_rating(course_id)

    if request.method == "POST":
        payment_method = request.POST.get("payment_method")
        student_id = ObjectId(request.session["student_id"])

        # Add to payments collection
        payments_col.insert_one({
            "student_id": student_id,
            "course_id": ObjectId(course_id),
            "amount": course["price"],
            "payment_method": payment_method,
            "paid_at": datetime.datetime.utcnow()
        })

        # Add to enrollments collection with Pending status
        enrollments_col.insert_one({
            "student_id": student_id,
            "course_id": ObjectId(course_id),
            "enrolled_at": datetime.datetime.utcnow(),
            "approval_status": "Pending"
        })

        # Log course enrollment
        student = users_collection.find_one({"_id": student_id})
        if student:
            log_user_activity(
                user_id=student_id,
                username=student["username"],
                role="student",
                action=f"📚 Enrolled in course: {course['title']}",
                performed_by="system"
            )

        messages.success(request, "Enrollment successful!")
        return redirect("student_dashboard")

    return render(request, "users/enroll_course.html", {
        "course": course,
        "avg_rating": avg_rating
    })

# Pay Course and send email to instructor and student
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import datetime

def pay_course(request, course_id):
    print(f"pay_course called with course_id: {course_id}")
    print(f"Request method: {request.method}")
    print(f"Request body: {request.body}")
    
    # Check if collections exist
    try:
        print(f"Available collections: {db.list_collection_names()}")
        print(f"Payments collection count: {payments_col.count_documents({})}")
        print(f"Enrollments collection count: {enrollments_col.count_documents({})}")
        print(f"Courses collection count: {courses_col.count_documents({})}")
    except Exception as e:
        print(f"Error checking collections: {e}")
    
    if not request.session.get("student_id"):
        print("No student_id in session")
        return JsonResponse({"status": "error", "message": "Login required"}, status=403)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            print(f"Parsed JSON data: {data}")
            payment_method = data.get("payment_method")
            print(f"Payment method: {payment_method}")

            if not payment_method:
                print("No payment method provided")
                return JsonResponse({"status": "error", "message": "Payment method required"})

            student_id = ObjectId(request.session["student_id"])
            course_oid = ObjectId(course_id)
            print(f"Student ID: {student_id}, Course ID: {course_oid}")

            # Prevent duplicate enrollment
            if enrollments_col.find_one({"student_id": student_id, "course_id": course_oid}):
                print("Student already enrolled")
                return JsonResponse({"status": "error", "message": "Already enrolled"})

            course = courses_col.find_one({"_id": course_oid})
            if not course:
                print("Course not found")
                return JsonResponse({"status": "error", "message": "Course not found"})
            
            print(f"Course found: {course['title']}")

            # Insert into payments
            payment_result = payments_col.insert_one({
                "student_id": student_id,
                "course_id": course_oid,
                "amount": course["price"],
                "payment_method": payment_method,
                "paid_at": datetime.datetime.utcnow()
            })
            print(f"Payment inserted: {payment_result.inserted_id}")

            # Insert into enrollments with Pending status
            enrollment_result = enrollments_col.insert_one({
                "student_id": student_id,
                "course_id": course_oid,
                "enrolled_at": datetime.datetime.utcnow(),
                "approval_status": "Pending"
            })
            print(f"Enrollment inserted: {enrollment_result.inserted_id}")

            # --- SEND EMAILS ---
            student = users_col.find_one({"_id": student_id})
            instructor = users_col.find_one({"_id": course["instructor_id"]})

            paid_at_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            # 1️⃣ Email to Instructor (includes a link to approve the enrollment)
            if instructor:
                try:
                    subject = f"New Enrollment: {course['title']}"
                    message = f"""
Hello {instructor['username']},

Your course "{course['title']}" (Category: {course['category']}) has a new enrollment.

Student: {student['username']}
Price: {course['price']} MMK
Payment Method: {payment_method}
Date: {paid_at_str}

To approve this enrollment, visit: /enrollments/{str(course_oid)}/

Regards,
Peer to Peer Education Platform
"""
                    send_mail(subject, message, settings.EMAIL_HOST_USER, [instructor['email']], fail_silently=False)
                    print("Email sent to instructor")
                except Exception as e:
                    print(f"Failed to send email to instructor: {e}")

            # 2️⃣ Email to Student (pending approval notification)
            try:
                subject_student = f"Enrollment Pending Approval: {course['title']}"
                message_student = f"""
Hello {student['username']},

We received your enrollment request for "{course['title']}" taught by {instructor['username'] if instructor else 'Unknown'}.
Your access will be available after the instructor approves your enrollment. We will email you once it's approved.

Price: {course['price']} MMK
Payment Method: {payment_method}
Date: {paid_at_str}

Thank you for your patience.
Peer to Peer Education Platform
"""
                send_mail(subject_student, message_student, settings.EMAIL_HOST_USER, [student['email']], fail_silently=False)
                print("Pending approval email sent to student")
            except Exception as e:
                print(f"Failed to send pending email to student: {e}")

            print("Enrollment successful, returning success response")
            return JsonResponse({"status": "success"})
            
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return JsonResponse({"status": "error", "message": "Invalid JSON data"}, status=400)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JsonResponse({"status": "error", "message": f"Unexpected error: {str(e)}"}, status=500)

    print("Invalid request method")
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

from django.views.decorators.http import require_GET

# Get Course Info
@require_GET
def get_course_info(request, course_id):
    course = courses_col.find_one({"_id": ObjectId(course_id)})
    if not course:
        return JsonResponse({"error": "Course not found"}, status=404)

    # Calculate average rating using helper function
    avg_rating = calculate_course_rating(course_id)

    instructor = users_col.find_one({"_id": course["instructor_id"]}, {"username": 1})

    return JsonResponse({
        "title": course["title"],
        "photo": f"/users_media/{course['course_photo']}",
        "description": course.get("description", "No description"),
        "price": course["price"],
        "category": course.get("category", "No category"),
        "avg_rating": avg_rating,
        "instructor": instructor.get("username") if instructor else "Unknown"
    })


# Instructor Part
# users/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password, make_password
import pymongo
from bson.objectid import ObjectId, InvalidId
import datetime
import uuid
import os
from django.conf import settings
from django.utils import timezone
import bcrypt
from .forms import InstructorProfileForm, InstructorRegistrationForm, ForgotPasswordForm


def get_db():
    """Establishes a connection to the MongoDB database."""
    try:
        connection = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=5000)
        connection.admin.command('ping')  # Check the connection
        return connection["Peer_to_Peer_Education"], connection
    except pymongo.errors.ConnectionFailure as e:
        print(f"Error: Could not connect to MongoDB: {e}")
        return None, None


def load_session(request):
    db, conn = get_db()
    sessions_collection = db["sessions"]
    session_id = request.COOKIES.get("sessionid")
    session_data = {}
    if session_id:
        session_doc = sessions_collection.find_one({"_id": session_id})
        if session_doc:
            session_data = session_doc.get("data", {})
    else:
        session_id = str(uuid.uuid4())
    conn.close()
    return session_id, session_data


def save_session(response, session_id, session_data):
    db, conn = get_db()
    sessions_collection = db["sessions"]
    if sessions_collection is not None:
        sessions_collection.update_one(
            {"_id": session_id},
            {"$set": {"data": session_data, "updated": datetime.datetime.utcnow()}},
            upsert=True
        )
    response.set_cookie("sessionid", session_id, httponly=True)
    conn.close()


def manual_login_required(view_func):
    def wrapper(request, *args, **kwargs):
        session_id, session = load_session(request)
        if not session.get("instructor_name"):
            response = redirect("instructor_login")
            save_session(response, session_id, session)
            return response
        request.session_data = session
        request.session_id = session_id
        return view_func(request, *args, **kwargs)

    return wrapper


def manual_instructor_required(view_func):
    def wrapper(request, *args, **kwargs):
        session_id, session = load_session(request)
        if session.get("role") != "instructor":
            response = HttpResponse("Access Denied: Instructors only.", status=403)
            save_session(response, session_id, session)
            return response
        request.session_data = session
        request.session_id = session_id
        return view_func(request, *args, **kwargs)

    return wrapper


def get_instructor_context(request):
    session_data = request.session_data if hasattr(request, 'session_data') else load_session(request)[1]
    return {
        'instructor_name': session_data.get('instructor_name', ''),
        'instructor_photo': session_data.get('instructor_photo', ''),
        'instructor_email': session_data.get('instructor_email', ''),
    }

# Instructor Login - add logging
@csrf_protect
def instructor_login(request):
    db, conn = get_db()
    try:
        users_collection = db["users"]
        session_id, session = load_session(request)

        if request.method == "POST":
            username = request.POST.get("username", "").strip()
            email = request.POST.get("email", "").strip()
            password = request.POST.get("password", "").strip()

            user_doc = users_collection.find_one({
                "username": {"$regex": username, "$options": "i"},
                "email": {"$regex": email, "$options": "i"},
                "role": "instructor"
            })

            if user_doc and bcrypt.checkpw(password.encode(), user_doc["password"].encode()):
                session.update({
                    "user_id": str(user_doc["_id"]),
                    "username": user_doc["username"],
                    "role": user_doc["role"],
                    "instructor_name": user_doc.get("username", ""),
                    "instructor_email": user_doc.get("email", ""),
                    "instructor_photo": user_doc.get("profile_photo", "")
                })

                users_collection.update_one(
                    {"_id": user_doc["_id"]},
                    {"$set": {"last_login": datetime.datetime.utcnow()}}
                )

                # Log successful instructor login
                log_user_activity(
                    user_id=user_doc["_id"],
                    username=user_doc["username"],
                    role="instructor",
                    action="🔐 Instructor logged in",
                    performed_by="system"
                )

                response = redirect("instructor_dashboard")
                save_session(response, session_id, session)
                return response
            else:
                context = {"error_message": "Invalid username, email, or password."}
                response = render(request, "users/instructor_login.html", context)
                save_session(response, session_id, session)
                return response

        context = {}
        response = render(request, "users/instructor_login.html", context)
        save_session(response, session_id, session)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()

# Instructor Logout - add logging
def instructor_logout(request):
    session_id, session = load_session(request)
    
    # Log logout before clearing session
    if session.get("user_id"):
        try:
            from dashboard.views import log_user_activity
            log_user_activity(
                user_id=ObjectId(session["user_id"]),
                username=session.get("username", "Unknown"),
                role="instructor",
                action="🚪 Instructor logged out",
                performed_by="system"
            )
        except:
            pass  # Don't fail logout if logging fails
    
    session.clear()
    response = redirect("instructor_login")
    save_session(response, session_id, session)
    return response


@csrf_protect
def instructor_register_view(request):
    db, conn = get_db()
    try:
        users_collection = db["users"]
        session_id, session = load_session(request)

        if request.method == 'POST':
            form = InstructorRegistrationForm(request.POST, request.FILES)
            
            if form.is_valid():
                profile_photo_file = form.cleaned_data.get('profile_photo')
                profile_photo_path = None
                file_path_on_disk = None

                if profile_photo_file:
                    upload_dir = os.path.join(settings.MEDIA_ROOT, 'users_profile_photos')
                    os.makedirs(upload_dir, exist_ok=True)

                    unique_filename = f"{uuid.uuid4().hex}_{profile_photo_file.name}"
                    file_path_on_disk = os.path.join(upload_dir, unique_filename)

                    with open(file_path_on_disk, 'wb+') as destination:
                        for chunk in profile_photo_file.chunks():
                            destination.write(chunk)

                    profile_photo_path = os.path.join('users_profile_photos', unique_filename).replace('\\', '/')

                if users_collection is not None:
                    try:
                        user_id = form.save(users_collection, profile_photo_path)
                        
                        # Log the new instructor registration
                        log_user_activity(
                            user_id=user_id,  # user_id is already an ObjectId
                            username=form.cleaned_data["username"],
                            role="instructor",
                            action="🆕 New instructor account created",
                            performed_by="system"
                        )
                        
                        # Add success message and redirect to login page
                        messages.success(request, f"Registration successful! Welcome {form.cleaned_data['username']}. Please login with your credentials.")
                        response = redirect('instructor_login')
                        save_session(response, session_id, session)
                        return response
                    except Exception as e:
                        if file_path_on_disk and os.path.exists(file_path_on_disk):
                            os.remove(file_path_on_disk)
                        form.add_error(None, str(e))
                else:
                    form.add_error(None, "Database connection failed.")
        else:
            form = InstructorRegistrationForm()

        context = {'form': form}
        response = render(request, 'users/instructor_register.html', context)
        save_session(response, session_id, session)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()


@csrf_protect
def forgot_password_view(request):
    db, conn = get_db()
    try:
        users_collection = db["users"]
        session_id, session = load_session(request)

        if request.method == 'POST':
            form = ForgotPasswordForm(request.POST)
            if form.is_valid():
                email = form.cleaned_data['email']
                context = {
                    'message': f"If an account with {email} exists, a password reset link has been sent.",
                    'form': ForgotPasswordForm()
                }
                response = render(request, 'users/forgot_password.html', context)
                save_session(response, session_id, session)
                return response
        else:
            form = ForgotPasswordForm()

        context = {'form': form}
        response = render(request, 'users/forgot_password.html', context)
        save_session(response, session_id, session)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()


@manual_login_required
@manual_instructor_required
def instructor_dashboard_view(request):
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed. Please check if MongoDB is running.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id
        instructor_id = request.session_data.get("user_id")

        if not instructor_id:
            return redirect('instructor_login')

        try:
            instructor_object_id = ObjectId(instructor_id)
        except InvalidId:
            return HttpResponse("Invalid user ID format. Please log in again.", status=400)

        courses_collection = db['courses']
        enrollments_collection = db['enrollments']
        earnings_summary_collection = db['instructor_earnings_summary']

        # Fetch instructor data for the sidebar
        context = get_instructor_context(request)

        # 1. Get total course count
        my_course_count = courses_collection.count_documents({"instructor_id": instructor_object_id})
        context['my_course_count'] = my_course_count

        # 2. Get total earnings (course earnings only - no admin salary)
        from payments.views import get_instructor_earnings
        earnings_summary = get_instructor_earnings(db, instructor_object_id)
        total_earnings = earnings_summary['earnings_from_courses']
        context['total_earnings'] = total_earnings

        # 3. Get total enrollments for all of the instructor's courses
        instructor_course_ids = [c["_id"] for c in courses_collection.find({"instructor_id": instructor_object_id}, {"_id": 1})]
        total_enrollments = enrollments_collection.count_documents({
            "course_id": {"$in": instructor_course_ids},
            "approval_status": "Approved"
        })
        context['total_enrollments'] = total_enrollments

        # 4. Get the top 3 most recent courses
        top_courses_cursor = courses_collection.find(
            {"instructor_id": instructor_object_id}
        ).sort("created_at", -1).limit(3)
        top_courses = list(top_courses_cursor)

        # Convert ObjectIds to strings and set the correct photo URL for the template
        for course in top_courses:
            course['id_str'] = str(course['_id'])
            # Here is the fix: Check if the photo field is a non-empty string.
            # The database field is correctly named 'course_photo'.
            photo_path = course.get('course_photo')
            if photo_path and photo_path.strip():
                # Correctly set the full URL for the template
                course['photo_url'] = photo_path
            else:
                # Fallback if no photo is set or the path is invalid
                course['photo_url'] = None

        context['top_courses'] = top_courses

        response = render(request, "users/instructor_dashboard.html", context)
        save_session(response, request.session_id, request.session_data)
        return response

    except Exception as e:
        print(f"FATAL ERROR in instructor_dashboard_view: {e}")
        return HttpResponse("An internal server error occurred. Please check the server logs for details.", status=500)
    finally:
        if conn:
            conn.close()

# Instructor Profile View - add logging for profile updates
@csrf_protect
@manual_login_required
@manual_instructor_required
def instructor_profile_view(request):
    db, conn = get_db()
    try:
        users_collection = db["users"]
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id

        user_id = request.session_data.get("user_id")
        user_doc = None
        if users_collection is not None:
            user_doc = users_collection.find_one({"_id": ObjectId(user_id)})

        if not user_doc:
            response = Http404("User not found.")
            save_session(response, session_id, session_data)
            return response

        initial_data = {
            "username": user_doc.get("username"),
            "email": user_doc.get("email"),
            "description": user_doc.get("description", ""),  # Load description from user_doc
        }

        if request.method == "POST":
            form = InstructorProfileForm(request.POST, request.FILES, user_id=user_id,
                                         users_collection=users_collection)
            if form.is_valid():
                profile_photo_file = form.cleaned_data.get('profile_photo')
                profile_photo_path = user_doc.get('profile_photo')

                if profile_photo_file:
                    upload_dir = os.path.join(settings.MEDIA_ROOT, 'users_profile_photos')
                    os.makedirs(upload_dir, exist_ok=True)

                    unique_filename = f"{uuid.uuid4().hex}_{profile_photo_file.name}"
                    file_path_on_disk = os.path.join(upload_dir, unique_filename)

                    from PIL import Image
                    img = Image.open(profile_photo_file)
                    img.save(file_path_on_disk)

                    profile_photo_path = os.path.join('users_profile_photos', unique_filename).replace('\\', '/')

                    old_photo_path = user_doc.get('profile_photo')
                    if old_photo_path and old_photo_path != 'users/default.jpg':
                        old_file_path_on_disk = os.path.join(settings.MEDIA_ROOT, old_photo_path)
                        if os.path.exists(old_file_path_on_disk):
                            os.remove(old_file_path_on_disk)

                try:
                    form.save(profile_photo_path=profile_photo_path)
                    
                    # Log profile update
                    log_user_activity(
                        user_id=ObjectId(user_id),
                        username=form.cleaned_data["username"],
                        role="instructor",
                        action="✏️ Instructor profile updated",
                        performed_by="system"
                    )
                    
                    request.session_data.update({
                        "username": form.cleaned_data["username"],
                        "instructor_name": form.cleaned_data["username"],
                        "instructor_email": form.cleaned_data["email"],
                        "instructor_photo": profile_photo_path
                    })
                    response = redirect("instructor_profile")
                    save_session(response, request.session_id, request.session_data)
                    return response
                except Exception as e:
                    form.add_error(None, str(e))
        else:
            form = InstructorProfileForm(initial=initial_data, user_id=user_id, users_collection=users_collection)

        context = {
            "form": form,
            "user_doc": user_doc,
            **get_instructor_context(request)
        }

        response = render(request, "users/instructor_profile.html", context)
        save_session(response, request.session_id, request.session_data)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()
