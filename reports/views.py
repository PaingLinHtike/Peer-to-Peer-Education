from django.shortcuts import render, redirect
from django.shortcuts import render, redirect
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from bson.objectid import ObjectId, InvalidId
from pymongo import MongoClient
from datetime import datetime, timedelta
from django.core.mail import send_mail
from users.views import manual_login_required

db = MongoClient("localhost", 27017)["Peer_to_Peer_Education"]

# Admin functionality (existing)
def all_reports(request):
    now = datetime.utcnow()
    expire_before = now - timedelta(days=3)

    # ✅ Delete reports with resolved_at older than 3 days only
    db["reports"].delete_many({
        "resolved_at": {"$ne": None, "$lt": expire_before}
    })

    # 🔍 Filter conditions
    query = {}
    if request.GET.get("status") == "resolved":
        query["resolved_at"] = {"$ne": None}
    elif request.GET.get("status") == "unresolved":
        query["resolved_at"] = None

    if user := request.GET.get("user_id"):
        try:
            query["reported_by"] = ObjectId(user)
        except:
            pass
    if course := request.GET.get("course_id"):
        try:
            query["target_course"] = ObjectId(course)
        except:
            pass
    if date := request.GET.get("date"):
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            query["submitted_at"] = {
                "$gte": datetime(dt.year, dt.month, dt.day),
                "$lt": datetime(dt.year, dt.month, dt.day + 1)
            }
        except ValueError:
            pass

    reports_cursor = db["reports"].find(query).sort("submitted_at", -1)

    # ✅ Use only students for the reporters dropdown
    user_map = {
        str(u["_id"]): u.get("username", "Unknown")
        for u in db["users"].find({"role": "student"})
    }
    course_map = {
        str(c["_id"]): c.get("title", "Unknown Course")
        for c in db["courses"].find()
    }

    reports = []
    for r in reports_cursor:
        reports.append({
            "id": str(r["_id"]),
            "reason": r.get("reason", ""),
            "description": r.get("description", ""),
            "date": r.get("submitted_at"),
            "resolved_at": r.get("resolved_at"),
            "reported_by_name": user_map.get(str(r.get("reported_by")), "Unknown"),
            "course_title": course_map.get(str(r.get("target_course")), "Unknown Course"),
        })

    return render(request, "reports/all_reports.html", {
        "reports": reports,
        "all_users": user_map,
        "all_courses": course_map,
    })


@require_POST
def resolve_report(request, report_id):
    if not request.session.get('admin_name'):
        return HttpResponseRedirect(reverse("all_reports"))

    report = db["reports"].find_one({"_id": ObjectId(report_id)})
    if not report:
        return HttpResponseRedirect(reverse("all_reports"))

    # ✅ Mark as resolved
    db["reports"].update_one(
        {"_id": ObjectId(report_id)},
        {"$set": {"resolved_at": datetime.utcnow()}}
    )

    user = db["users"].find_one({"_id": report.get("reported_by")})
    course = db["courses"].find_one({"_id": report.get("target_course")})

    # ✅ Email student if info available
    if user and course:
        send_mail(
            subject="✅ Your report has been reviewed",
            message=(
                f"Dear {user['username']},\n\n"
                f"Thank you for reporting the course \"{course['title']}\".\n"
                f"Our team has reviewed the report and taken appropriate action.\n\n"
                f"Regards,\nAdmin Team"
            ),
            from_email="admin@ptp.com",
            recipient_list=[user["email"]],
            fail_silently=False,
        )

    return HttpResponseRedirect(reverse("all_reports"))


# Student functionality (new)
def student_write_report(request):
    """
    Allow students to write reports about courses they are enrolled in.
    """
    # Check if student is logged in
    if not request.session.get("student_id"):
        return redirect('student_login')
    
    student_id = request.session.get('student_id')
    
    try:
        student_object_id = ObjectId(student_id)
    except InvalidId:
        return HttpResponse("Invalid student ID format.", status=400)
    
    message = ""
    
    # Get enrolled courses for this student
    enrollments_collection = db["enrollments"]
    courses_collection = db["courses"]
    users_collection = db["users"]
    
    enrolled_courses = []
    for enrollment in enrollments_collection.find({"student_id": student_object_id, "approval_status": "Approved"}):
        course = courses_collection.find_one({"_id": enrollment["course_id"]})
        if course:
            # Get instructor information from users collection
            instructor_id = course.get("instructor_id")
            instructor_name = "Unknown Instructor"
            if instructor_id:
                instructor_doc = users_collection.find_one({"_id": instructor_id}, {"username": 1})
                if instructor_doc:
                    instructor_name = instructor_doc.get("username", "Unknown Instructor")
            
            enrolled_courses.append({
                "id": str(course["_id"]),
                "title": course.get("title", "Unknown Course"),
                "instructor": instructor_name
            })
    
    if request.method == "POST":
        course_id = request.POST.get('course_id')
        reason = request.POST.get('reason')
        description = request.POST.get('description')
        
        if not course_id or not reason or not description:
            message = "All fields are required."
        else:
            try:
                course_object_id = ObjectId(course_id)
                
                # Verify student is enrolled in this course
                enrollment = enrollments_collection.find_one({
                    "student_id": student_object_id,
                    "course_id": course_object_id,
                    "approval_status": "Approved"
                })
                
                if not enrollment:
                    message = "You can only report courses you are enrolled in."
                else:
                    # Create the report
                    new_report = {
                        "reported_by": student_object_id,
                        "target_course": course_object_id,
                        "reason": reason,
                        "description": description,
                        "submitted_at": datetime.utcnow(),
                        "resolved_at": None
                    }
                    
                    db["reports"].insert_one(new_report)
                    message = "Report submitted successfully. Admin will review your report."
                    
            except InvalidId:
                message = "Invalid course ID."
            except Exception as e:
                message = f"Error submitting report: {str(e)}"
    
    # Get student info for template context
    student_name = request.session.get('student_name', 'Student')
    student_profile_pic = request.session.get('student_photo', 'users/default_profile.png')
    
    context = {
        'enrolled_courses': enrolled_courses,
        'message': message,
        'student_name': student_name,
        'student_profile_pic': student_profile_pic,
    }
    
    return render(request, 'reports/student_write_report.html', context)


def student_view_reports(request):
    """
    Allow students to view their submitted reports and their status.
    """
    # Check if student is logged in
    if not request.session.get("student_id"):
        return redirect('student_login')
    
    student_id = request.session.get('student_id')
    
    try:
        student_object_id = ObjectId(student_id)
    except InvalidId:
        return HttpResponse("Invalid student ID format.", status=400)
    
    # Get all reports submitted by this student
    reports_cursor = db["reports"].find({"reported_by": student_object_id}).sort("submitted_at", -1)
    
    # Get course information for each report
    courses_collection = db["courses"]
    course_map = {
        str(c["_id"]): c.get("title", "Unknown Course")
        for c in courses_collection.find()
    }
    
    student_reports = []
    total_reports = 0
    pending_reports = 0
    resolved_reports = 0
    
    for report in reports_cursor:
        total_reports += 1
        if report.get("resolved_at"):
            resolved_reports += 1
        else:
            pending_reports += 1
            
        student_reports.append({
            "id": str(report["_id"]),
            "course_title": course_map.get(str(report.get("target_course")), "Unknown Course"),
            "reason": report.get("reason", ""),
            "description": report.get("description", ""),
            "date": report.get("submitted_at"),
            "resolved_at": report.get("resolved_at"),
        })
    
    # Get student info for template context
    student_name = request.session.get('student_name', 'Student')
    student_profile_pic = request.session.get('student_photo', 'users/default_profile.png')
    
    context = {
        'reports': student_reports,
        'total_reports': total_reports,
        'pending_reports': pending_reports,
        'resolved_reports': resolved_reports,
        'student_name': student_name,
        'student_profile_pic': student_profile_pic,
    }
    
    return render(request, 'reports/student_view_reports.html', context)
