# enrollments/views.py

from django.shortcuts import render, redirect
from django.http import HttpResponse, Http404, JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.http import require_POST
import pymongo
from bson.objectid import ObjectId, InvalidId
from users.views import manual_login_required, manual_instructor_required, load_session, save_session, get_db


@manual_login_required
@manual_instructor_required
def instructor_enrollments_view(request):
    """
    Renders a summary of all enrollments for all of the instructor's courses.
    This view now correctly fetches both the student's account status (is_active)
    and the enrollment approval status (approval_status).
    """
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id

        instructor_id = session_data.get('user_id')
        if not instructor_id:
            response = redirect('instructor_login')
            save_session(response, session_id, session_data)
            return response

        try:
            instructor_object_id = ObjectId(instructor_id)
        except InvalidId:
            return HttpResponse("Invalid user ID format. Please log in again.", status=400)

        courses_collection = db['courses']
        enrollments_collection = db['enrollments']
        users_collection = db['users']

        instructor_doc = users_collection.find_one(
            {"_id": instructor_object_id},
            {"username": 1, "email": 1, "profile_photo": 1}
        )
        if not instructor_doc:
            raise Http404("Instructor not found.")

        instructor_courses = list(courses_collection.find(
            {"instructor_id": instructor_object_id},
            {"_id": 1, "title": 1}
        ))

        instructor_course_ids = [course['_id'] for course in instructor_courses]
        instructor_course_titles = {str(course['_id']): course['title'] for course in instructor_courses}

        enrollments_cursor = enrollments_collection.find(
            {"course_id": {"$in": instructor_course_ids}}
        ).sort("enrolled_at", -1)

        enrollments_list = []
        for enrollment in enrollments_cursor:
            student_doc = users_collection.find_one({"_id": enrollment['student_id']}, {"username": 1, "is_active": 1})
            if not student_doc:
                continue

            enrollment['student_username'] = student_doc.get('username', 'Unknown Student')
            enrollment['course_title'] = instructor_course_titles.get(str(enrollment['course_id']), 'Unknown Course')
            enrollment['is_active'] = student_doc.get('is_active', False)
            enrollment['approval_status'] = enrollment.get('approval_status', 'Pending')
            # Provide string form for URLs/templates
            enrollment['course_id_str'] = str(enrollment.get('course_id'))

            enrollments_list.append(enrollment)

        context = {
            'enrollments': enrollments_list,
            'instructor_photo': instructor_doc.get('profile_photo'),
            'instructor_name': instructor_doc.get('username'),
            'instructor_email': instructor_doc.get('email'),
        }

        response = render(request, 'enrollments/instructor_enrollments.html', context)
        save_session(response, session_id, session_data)
        return response

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return HttpResponse(f"An unexpected error occurred: {e}", status=500)
    finally:
        if conn:
            conn.close()


@manual_login_required
@manual_instructor_required
def course_enrollments_detail_view(request, course_id):
    """
    Displays the detailed list of students enrolled in a specific course.
    It shows the student's account status, enrollment approval status, and payment proof.
    """
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id

        instructor_id = session_data.get('user_id')
        if not instructor_id:
            response = redirect('instructor_login')
            save_session(response, session_id, session_data)
            return response

        users_collection = db['users']
        instructor_doc = users_collection.find_one(
            {"_id": ObjectId(instructor_id)},
            {"username": 1, "email": 1, "profile_photo": 1}
        )

        courses_collection = db['courses']
        enrollments_collection = db['enrollments']

        try:
            course_object_id = ObjectId(course_id)
            instructor_object_id = ObjectId(instructor_id)
        except InvalidId:
            raise Http404("Invalid Course ID.")

        course = courses_collection.find_one(
            {"_id": course_object_id, "instructor_id": instructor_object_id},
            {"title": 1}
        )
        if not course:
            return HttpResponse("You are not authorized to view enrollments for this course.", status=403)

        enrollments_cursor = enrollments_collection.find(
            {"course_id": course_object_id}
        ).sort("enrolled_at", -1)

        enrollments_list = []
        for enrollment in enrollments_cursor:
            student_doc = users_collection.find_one({"_id": enrollment['student_id']}, {"username": 1, "is_active": 1})
            if not student_doc:
                continue

            enrollment['student_username'] = student_doc.get('username', 'Unknown Student')
            enrollment['is_active'] = student_doc.get('is_active', False)
            enrollment['approval_status'] = enrollment.get('approval_status', 'Pending')
            enrollment['payment_proof_url'] = enrollment.get('payment_proof_url')
            enrollment['enrollment_id_str'] = str(enrollment['_id'])

            enrollments_list.append(enrollment)

        context = {
            'course_title': course['title'],
            'enrollments': enrollments_list,
            'instructor_photo': instructor_doc.get('profile_photo'),
            'instructor_name': instructor_doc.get('username'),
            'instructor_email': instructor_doc.get('email'),
        }

        response = render(request, 'enrollments/course_enrollments_detail.html', context)
        save_session(response, session_id, session_data)
        return response

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return HttpResponse(f"An unexpected error occurred: {e}", status=500)
    finally:
        if conn:
            conn.close()


@require_POST
@manual_login_required
@manual_instructor_required
def approve_enrollment(request, enrollment_id):
    """
    Approves a student's enrollment by updating the approval_status in the database.
    This is the action taken by the instructor after being notified by the admin.
    """
    db, conn = get_db()
    if db is None:
        return JsonResponse({"success": False, "error": "Database connection failed."}, status=500)

    try:
        session_id, session_data = load_session(request)
        instructor_id = session_data.get('user_id')
        if not instructor_id:
            return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)

        try:
            enrollment_object_id = ObjectId(enrollment_id)
            instructor_object_id = ObjectId(instructor_id)
        except InvalidId:
            return JsonResponse({'success': False, 'error': 'Invalid ID format'}, status=400)

        enrollments_collection = db['enrollments']
        courses_collection = db['courses']

        # Find the enrollment and verify the instructor is the owner of the course
        enrollment = enrollments_collection.find_one({"_id": enrollment_object_id})
        if not enrollment:
            return JsonResponse({'success': False, 'error': 'Enrollment not found'}, status=404)

        course = courses_collection.find_one({"_id": enrollment['course_id'], "instructor_id": instructor_object_id})
        if not course:
            return JsonResponse({'success': False, 'error': 'Not authorized to approve this enrollment'}, status=403)

        # Check if enrollment is already approved
        if enrollment.get('approval_status') == 'Approved':
            return JsonResponse({"success": False, "error": "Enrollment already approved"})

        # Update the enrollment status in the database
        result = enrollments_collection.update_one(
            {"_id": enrollment_object_id},
            {"$set": {"approval_status": "Approved"}}
        )

        if result.modified_count == 1:
            # Send email notification to student upon approval
            users_collection = db['users']
            enrollment = enrollments_collection.find_one({"_id": enrollment_object_id})
            student_doc = users_collection.find_one({"_id": enrollment['student_id']}) if enrollment else None
            course_doc = courses_collection.find_one({"_id": enrollment['course_id']}) if enrollment else None

            try:
                if student_doc and course_doc:
                    send_mail(
                        subject=f"Enrollment Approved: {course_doc.get('title', 'Course')}",
                        message=(
                            f"Hello {student_doc.get('username', 'Student')},\n\n"
                            f"Your enrollment for the course \"{course_doc.get('title', 'Course')}\" has been approved by the instructor.\n"
                            f"You can now access it in My Courses.\n\n"
                            f"Regards,\nPeer to Peer Education"
                        ),
                        from_email=settings.EMAIL_HOST_USER,
                        recipient_list=[student_doc.get('email')],
                        fail_silently=True
                    )
            except Exception:
                # Do not block approval if email fails
                pass

            # Optionally return updated totals to refresh dashboard widgets client-side if needed
            return JsonResponse({'success': True, "message": "Enrollment successfully approved."})
        else:
            return JsonResponse({'success': False, 'error': 'Enrollment not updated'}, status=500)

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    finally:
        if conn:
            conn.close()

