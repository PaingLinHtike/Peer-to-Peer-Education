from django.shortcuts import render, redirect
from pymongo import MongoClient
from bson.objectid import ObjectId

client = MongoClient("localhost", 27017)
db = client["Peer_to_Peer_Education"]
enrollments_col = db["enrollments"]
courses_col = db["courses"]
users_col = db["users"]

def my_courses(request):
    if not request.session.get("student_id"):
        return redirect("student_login")

    student_id = ObjectId(request.session["student_id"])

    # Fetch student info for header/profile
    student = users_col.find_one(
        {"_id": student_id, "role": "student"},
        {"username": 1, "profile_photo": 1}
    )
    student_name = student.get("username", "Unknown") if student else "Unknown"
    student_profile_pic = student.get("profile_photo") if student else None

    # Only show courses after instructor approval
    enrollments = enrollments_col.find({"student_id": student_id, "approval_status": "Approved"})

    enrolled_courses = []
    for enroll in enrollments:
        course = courses_col.find_one({"_id": enroll["course_id"]})
        if course:
            instructor = users_col.find_one({"_id": course["instructor_id"]}, {"username": 1})
            enrolled_courses.append({
                "title": course.get("title", ""),
                "instructor": instructor.get("username", "Unknown") if instructor else "Unknown",
                "category": course.get("category", ""),
                "enrolled_at": enroll.get("enrolled_at"),  # Keep enrolled date
                "course_file": course.get("file", ""),  # Add course file path
                "course_id": str(course["_id"])  # Add course ID for download link
            })

    context = {
        "courses": enrolled_courses,
        "student_name": student_name,
        "student_profile_pic": student_profile_pic
    }

    return render(request, "courses/my_courses.html", context)


# Instructor Part
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404
from django.views.decorators.csrf import csrf_protect
import pymongo
from bson.objectid import ObjectId, InvalidId
import datetime
import os
import uuid
from django.conf import settings

# Import custom session and DB functions from users.views
from users.views import get_db, load_session, save_session, manual_login_required, manual_instructor_required

from .forms import CourseForm  # Import the new CourseForm


# --- Helper function for common context data ---
def get_instructor_context(request):
    """Returns common instructor session data for templates."""
    session_data = request.session_data if hasattr(request, 'session_data') else load_session(request)[1]
    return {
        'instructor_name': session_data.get('instructor_name', ''),
        'instructor_photo': session_data.get('instructor_photo', ''),
        'instructor_email': session_data.get('instructor_email', ''),
    }


# --- Instructor Course Views ---

@manual_login_required
@manual_instructor_required
def instructor_course_list(request):
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id

        courses_collection = db['courses']
        instructor_id = request.session_data.get('user_id')

        if not instructor_id:
            response = HttpResponse("Instructor ID not found in session.", status=400)
            save_session(response, request.session_id, request.session_data)
            return response

        # Fetch courses for the logged-in instructor
        courses_cursor = courses_collection.find({"instructor_id": ObjectId(instructor_id)}).sort("created_at", -1)
        courses_list = list(courses_cursor)

        # Fix: Convert ObjectId to string for template access
        for course in courses_list:
            course['id_str'] = str(course['_id'])

        context = {
            'courses': courses_list,
            **get_instructor_context(request)  # Add common instructor data
        }
        response = render(request, 'courses/instructor_course_list.html', context)
        save_session(response, request.session_id, request.session_data)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()


@csrf_protect
@manual_login_required
@manual_instructor_required
def instructor_course_create(request):
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id

        courses_collection = db['courses']
        instructor_id = request.session_data.get('user_id')

        if not instructor_id:
            response = HttpResponse("Instructor ID not found in session.", status=400)
            save_session(response, request.session_id, request.session_data)
            return response

        if request.method == 'POST':
            form = CourseForm(request.POST, request.FILES, instructor_id=instructor_id)
            if form.is_valid():
                course_photo_file = form.cleaned_data.get('course_photo')
                main_file = form.cleaned_data.get('file')
                course_photo_path = None
                file_path = None

                # Handle course photo upload
                if course_photo_file:
                    upload_dir = os.path.join(settings.MEDIA_ROOT, 'course_photos')
                    os.makedirs(upload_dir, exist_ok=True)
                    unique_filename = f"{uuid.uuid4().hex}_{course_photo_file.name}"
                    file_path_on_disk = os.path.join(upload_dir, unique_filename)
                    with open(file_path_on_disk, 'wb+') as destination:
                        for chunk in course_photo_file.chunks():
                            destination.write(chunk)
                    course_photo_path = os.path.join('course_photos', unique_filename).replace('\\', '/')

                # Handle main course file upload
                if main_file:
                    upload_dir = os.path.join(settings.MEDIA_ROOT, 'course_files')
                    os.makedirs(upload_dir, exist_ok=True)
                    unique_filename = f"{uuid.uuid4().hex}_{main_file.name}"
                    file_path_on_disk = os.path.join(upload_dir, unique_filename)
                    with open(file_path_on_disk, 'wb+') as destination:
                        for chunk in main_file.chunks():
                            destination.write(chunk)
                    file_path = os.path.join('course_files', unique_filename).replace('\\', '/')

                try:
                    form.save(courses_collection, instructor_id, course_photo_path, file_path)
                    response = redirect('instructor_course_list')
                    save_session(response, request.session_id, request.session_data)
                    return response
                except Exception as e:
                    form.add_error(None, str(e))  # Add a non-field error for database issues
            # If form is not valid, it falls through to render with errors
        else:
            form = CourseForm(instructor_id=instructor_id)  # Pass instructor_id for initial form setup

        context = {
            'form': form,
            'form_type': 'Create',
            **get_instructor_context(request)  # Add common instructor data
        }
        response = render(request, 'courses/instructor_course_form.html', context)
        save_session(response, request.session_id, request.session_data)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()


@manual_login_required
@manual_instructor_required
def instructor_course_detail(request, pk):
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id

        courses_collection = db['courses']
        course = courses_collection.find_one(
            {"_id": ObjectId(pk), "instructor_id": ObjectId(request.session_data['user_id'])})
        if not course:
            raise Http404("Course not found or you don't have permission to view it.")

        # Fix: Convert ObjectId to string for template access
        course['id_str'] = str(course['_id'])

        context = {
            'course': course,
            **get_instructor_context(request)
        }
        response = render(request, 'courses/instructor_course_detail.html', context)
        save_session(response, request.session_id, request.session_data)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()


@csrf_protect
@manual_login_required
@manual_instructor_required
def instructor_course_update(request, pk):
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id

        courses_collection = db['courses']
        instructor_id = request.session_data.get('user_id')
        course = courses_collection.find_one({"_id": ObjectId(pk), "instructor_id": ObjectId(instructor_id)})
        if not course:
            raise Http404("Course not found or you don't have permission to edit it.")

        # Fix: Convert ObjectId to string for template access
        course['id_str'] = str(course['_id'])

        if request.method == 'POST':
            form = CourseForm(request.POST, request.FILES, instructor_id=instructor_id, instance_id=pk)
            if form.is_valid():
                course_photo_file = form.cleaned_data.get('course_photo')
                main_file = form.cleaned_data.get('file')
                course_photo_path = course.get('course_photo')  # Keep existing if not new upload
                file_path = course.get('file')  # Keep existing if not new upload

                # Handle course photo upload (if new file is provided)
                if course_photo_file:
                    upload_dir = os.path.join(settings.MEDIA_ROOT, 'course_photos')
                    os.makedirs(upload_dir, exist_ok=True)
                    unique_filename = f"{uuid.uuid4().hex}_{course_photo_file.name}"
                    file_path_on_disk = os.path.join(upload_dir, unique_filename)
                    with open(file_path_on_disk, 'wb+') as destination:
                        for chunk in course_photo_file.chunks():
                            destination.write(chunk)
                    course_photo_path = os.path.join('course_photos', unique_filename).replace('\\', '/')

                # Handle main course file upload (if new file is provided)
                if main_file:
                    upload_dir = os.path.join(settings.MEDIA_ROOT, 'course_files')
                    os.makedirs(upload_dir, exist_ok=True)
                    unique_filename = f"{uuid.uuid4().hex}_{main_file.name}"
                    file_path_on_disk = os.path.join(upload_dir, unique_filename)
                    with open(file_path_on_disk, 'wb+') as destination:
                        for chunk in main_file.chunks():
                            destination.write(chunk)
                    file_path = os.path.join('course_files', unique_filename).replace('\\', '/')

                form.save(courses_collection, instructor_id, course_photo_path, file_path)
                response = redirect('instructor_course_detail', pk=pk)
                save_session(response, request.session_id, request.session_data)
                return response
            # If form is not valid, it falls through to render with errors
        else:
            # Prepare initial data for the form from the existing course document
            initial_data = {
                'title': course.get('title'),
                'description': course.get('description'),
                'price': course.get('price'),
                'category': course.get('category'),
                'status': course.get('status'),
                # Note: For ImageField/FileField, you typically don't set initial for the file input itself
                # but rather display the existing file path/URL. The form handles this.
            }
            form = CourseForm(initial=initial_data, instructor_id=instructor_id, instance_id=pk)

        context = {
            'form': form,
            'form_type': 'Edit',
            'course': course,  # Pass course object for template context
            **get_instructor_context(request)
        }
        response = render(request, 'courses/instructor_course_form.html', context)
        save_session(response, request.session_id, request.session_data)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()


@csrf_protect
@manual_login_required
@manual_instructor_required
def instructor_course_delete(request, pk):
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id

        courses_collection = db['courses']
        instructor_id = request.session_data.get('user_id')
        course = courses_collection.find_one({"_id": ObjectId(pk), "instructor_id": ObjectId(instructor_id)})
        if not course:
            raise Http404("Course not found or you don't have permission to delete it.")

        # Fix: Convert ObjectId to string for template access
        course['id_str'] = str(course['_id'])

        if request.method == 'POST':
            # Optionally delete associated files from disk
            if course.get('course_photo') and course['course_photo'] != 'courses/default_course.jpg':
                file_path = os.path.join(settings.MEDIA_ROOT, course['course_photo'])
                if os.path.exists(file_path):
                    os.remove(file_path)
            if course.get('file'):
                file_path = os.path.join(settings.MEDIA_ROOT, course['file'])
                if os.path.exists(file_path):
                    os.remove(file_path)

            courses_collection.delete_one({"_id": ObjectId(pk)})
            response = redirect('instructor_course_list')
            save_session(response, request.session_id, request.session_data)
            return response

        context = {
            'course': course,
            **get_instructor_context(request)
        }
        response = render(request, 'courses/instructor_course_confirm_delete.html', context)
        save_session(response, request.session_id, request.session_data)
        return response
    except Exception as e:
        return HttpResponse(f"Database connection error: {e}", status=500)
    finally:
        if conn:
            conn.close()

