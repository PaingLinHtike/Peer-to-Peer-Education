from calendar import month_name
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST, require_POST, require_GET
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from django.http import JsonResponse
import pymongo
from django.core.paginator import Paginator
from pymongo import MongoClient
from statistics import mean
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse 
from django.utils.timezone import is_aware
from datetime import datetime, timezone
from django.utils.dateparse import parse_datetime
from django.core.mail import send_mail
from django.conf import settings
import pymongo

connection = pymongo.MongoClient("localhost", 27017)
db = connection["Peer_to_Peer_Education"]
users_collection = db["users"]
enrollments_collection = db["enrollments"]
courses_collection = db["courses"]
payments_collection = db["payments"]

def log_user_activity(user_id, username, role, action, performed_by="system"):
    """Log user activity to the user_activity_logs collection"""
    try:
        db["user_activity_logs"].insert_one({
            "user_id": user_id,
            "username": username,
            "role": role,
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.utcnow()
        })
    except Exception as e:
        print(f"Error logging user activity: {e}")

def dashboard_home(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    today = datetime.utcnow()
    start_of_week = today - timedelta(days=today.weekday())  # ⬅️ FIXED: move before use
    start_of_day = datetime(today.year, today.month, today.day)

    total_students = users_collection.count_documents({"role": "student"})
    total_instructors = users_collection.count_documents({"role": "instructor"})
    total_users = users_collection.count_documents({"role": {"$in": ["student", "instructor"]}})
    total_courses = db["courses"].count_documents({"status": "approved"})

    # 🧮 New Courses This Week
    print("Today:", today)
    print("Start of week:", start_of_week)
    for c in db["courses"].find({"status": "approved"}):
        print(c["title"], " | created_at:", c.get("created_at"))

    new_this_week = db["courses"].count_documents({
        "status": "approved",
        "created_at": {"$gte": start_of_week}
    })

    # Modified activity logs to show user activities
    logs_cursor = db["user_activity_logs"].aggregate([
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user"
            }
        },
        {"$unwind": "$user"},
        {
            "$project": {
                "_id": 0,
                "action": 1,
                "timestamp": 1,
                "username": "$user.username",
                "role": "$user.role",
                "performed_by": 1
            }
        },
        {"$sort": {"timestamp": -1}},
        {"$limit": 20}  # Increased limit to show more activities
    ])
    activity_logs = list(logs_cursor)

    # Check if admin wants to clear the view
    if request.session.get('clear_activity_view'):
        activity_logs = []  # Clear the view
        del request.session['clear_activity_view']  # Remove the flag

    # Get and clear the view cleared message
    view_cleared_message = request.session.get('view_cleared_message', '')
    if view_cleared_message:
        del request.session['view_cleared_message']

    # Apply activity filtering if requested
    activity_filter = request.GET.get('activity_filter', '')
    if activity_filter:
        if activity_filter == 'login':
            activity_logs = [log for log in activity_logs if 'logged in' in log['action']]
        elif activity_filter == 'logout':
            activity_logs = [log for log in activity_logs if 'logged out' in log['action']]
        elif activity_filter == 'register':
            activity_logs = [log for log in activity_logs if 'account created' in log['action']]
        elif activity_filter == 'profile':
            activity_logs = [log for log in activity_logs if 'profile updated' in log['action']]
        elif activity_filter == 'enrollment':
            activity_logs = [log for log in activity_logs if 'Enrolled in course' in log['action']]
        elif activity_filter == 'admin':
            activity_logs = [log for log in activity_logs if log.get('performed_by') and log['performed_by'] != 'system']

    # Activity Summary Calculations
    # Today's logins (both student and instructor)
    today_logins = db["user_activity_logs"].count_documents({
        "action": {"$in": ["🔐 Student logged in", "🔐 Instructor logged in"]},
        "timestamp": {"$gte": start_of_day}
    })

    # New users this week
    new_users_week = db["user_activity_logs"].count_documents({
        "action": {"$in": ["🆕 New student account created", "🆕 New instructor account created"]},
        "timestamp": {"$gte": start_of_week}
    })

    # Total activities in the system
    total_activities = db["user_activity_logs"].count_documents({})

    # 💰 Total Revenue from course enrollments (100% of course fees)
    total_revenue_data = enrollments_collection.aggregate([
        {
            "$lookup": {
                "from": "courses",
                "localField": "course_id",
                "foreignField": "_id",
                "as": "course"
            }
        },
        {"$unwind": "$course"},
        {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
    ])
    total_revenue = next(total_revenue_data, {}).get("total", 0)

    # 💰 This Month Revenue from enrollments
    start_of_month = datetime(today.year, today.month, 1)
    month_revenue_data = enrollments_collection.aggregate([
        {"$match": {"enrolled_at": {"$gte": start_of_month}}},
        {
            "$lookup": {
                "from": "courses",
                "localField": "course_id",
                "foreignField": "_id",
                "as": "course"
            }
        },
        {"$unwind": "$course"},
        {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
    ])
    month_revenue = next(month_revenue_data, {}).get("total", 0)

    return render(request, "dashboard/dashboard_home.html", {
        "total_students": total_students,
        "total_instructors": total_instructors,
        "total_users": total_users,
        "total_courses": total_courses,
        "new_this_week": new_this_week,
        "activity_logs": activity_logs,
        "total_revenue": total_revenue,
        "month_revenue": month_revenue,
        "today_logins": today_logins,
        "new_users_week": new_users_week,
        "total_activities": total_activities,
        "view_cleared_message": request.session.get('view_cleared_message', ''),
    })

@require_POST
def clear_activity_logs(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    db["user_activity_logs"].delete_many({})
    return redirect('dashboard_home')

@require_POST
def clear_activity_view(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    # Set a session flag to clear the view
    request.session['clear_activity_view'] = True
    request.session['view_cleared_message'] = "Activity view cleared successfully. Data remains in database."
    return redirect('dashboard_home')

# Earning Overview
def earnings_overview(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    today = datetime.utcnow()
    start_of_month = datetime(today.year, today.month, 1)

    # Calculate total revenue from course enrollments (100% of course fees)
    total_revenue_data = enrollments_collection.aggregate([
        {
            "$lookup": {
                "from": "courses",
                "localField": "course_id",
                "foreignField": "_id",
                "as": "course"
            }
        },
        {"$unwind": "$course"},
        {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
    ])
    total_revenue = next(total_revenue_data, {}).get("total", 0)

    # Platform Commission is 30% of total course fees
    platform_fee = int(total_revenue * 0.3)
    
    # Course payouts to instructors (70% of total course fees)
    instructor_course_earnings = int(total_revenue * 0.7)

    # This month revenue from enrollments
    month_revenue_data = enrollments_collection.aggregate([
        {"$match": {"enrolled_at": {"$gte": start_of_month}}},
        {
            "$lookup": {
                "from": "courses",
                "localField": "course_id",
                "foreignField": "_id",
                "as": "course"
            }
        },
        {"$unwind": "$course"},
        {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
    ])
    month_revenue = next(month_revenue_data, {}).get("total", 0)

    # Monthly earnings breakdown based on enrollments
    monthly_cursor = enrollments_collection.aggregate([
        {
            "$lookup": {
                "from": "courses",
                "localField": "course_id",
                "foreignField": "_id",
                "as": "course"
            }
        },
        {"$unwind": "$course"},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$enrolled_at"},
                    "month": {"$month": "$enrolled_at"}
                },
                "total": {"$sum": "$course.price"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1}}
    ])

    monthly_earnings = []
    for row in monthly_cursor:
        y, m = row["_id"]["year"], row["_id"]["month"]
        amount = row["total"]
        instructor_share = int(amount * 0.7)  # 70% goes to instructors based on actual enrollments
        monthly_earnings.append({
            "month_name": f"{month_name[m]} {y}",
            "total": amount,
            "paid_out": instructor_share  # Actual course-based payouts
        })

    return render(request, "dashboard/earnings_overview.html", {
        "total_revenue": total_revenue,
        "month_revenue": month_revenue,
        "total_platform_fee": platform_fee,
        "total_paid_out": instructor_course_earnings,
        "monthly_earnings": monthly_earnings
    })

# User Growth
def user_growth(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    role_filter = request.GET.get('role', '')
    today = datetime.utcnow()
    start_of_week = today - timedelta(days=today.weekday())

    base_query = {"is_active": True, "role": {"$ne": "admin"}}
    if role_filter:
        base_query["role"] = role_filter

    total_users = users_collection.count_documents(base_query)
    new_this_week = users_collection.count_documents({
        **base_query,
        "date_joined": {"$gte": start_of_week}
    })

    # Weekly Aggregation
    pipeline = [
        {"$match": base_query},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$date_joined"},
                    "week": {"$isoWeek": "$date_joined"}
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id.year": 1, "_id.week": 1}}
    ]
    weekly_data = list(users_collection.aggregate(pipeline))
    new_users_by_week = [
        {
            "week_label": f"Week {w['_id']['week']}, {w['_id']['year']}",
            "count": w["count"]
        } for w in weekly_data
    ]

    chart_labels = [row["week_label"] for row in new_users_by_week]
    chart_values = [row["count"] for row in new_users_by_week]

    return render(request, "dashboard/user_growth.html", {
        "total_users": total_users,
        "new_this_week": new_this_week,
        "new_users_by_week": new_users_by_week,
        "role_filter": role_filter,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
    })

# Helper function to calculate average rating for a course
def calculate_course_rating(course_id):
    """Calculate average rating for a course from reviews collection"""
    try:
        reviews = db["reviews"].find({"course_id": ObjectId(course_id)})
        ratings = [r["rating"] for r in reviews]
        if ratings:
            avg_rating = mean(ratings)
            return round(avg_rating, 1)
        return 0.0
    except Exception as e:
        print(f"Error calculating rating for course {course_id}: {e}")
        return 0.0

# Course Overview
db = pymongo.MongoClient("localhost", 27017)["Peer_to_Peer_Education"]

def course_overview(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    courses_collection = db["courses"]
    enrollments_collection = db["enrollments"]
    users_collection = db["users"]
    reviews_collection = db["reviews"]

    # 📊 Top 3 Most Enrolled Courses
    enroll_agg = enrollments_collection.aggregate([
        {"$group": {"_id": "$course_id", "enroll_count": {"$sum": 1}}},
        {"$sort": {"enroll_count": -1}},
        {"$limit": 3}
    ])

    top_courses = []
    for item in enroll_agg:
        course_id = item["_id"]
        enroll_count = item["enroll_count"]
        course = courses_collection.find_one({
            "_id": ObjectId(course_id),
            "status": "approved"
        })
        if not course:
            continue
        instructor_id = course.get("instructor_id")
        instructor = users_collection.find_one({"_id": ObjectId(instructor_id)}) if instructor_id else None

        # Use helper function to calculate average rating
        avg_rating = calculate_course_rating(course_id)

        top_courses.append({
            "title": course.get("title", ""),
            "instructor": instructor["username"] if instructor else "Unknown",
            "enrollments": enroll_count,
            "avg_rating": avg_rating,
        })

    # 📝 Courses Pending Approval
    pending_courses_cursor = courses_collection.find({"status": "pending"})
    pending_courses = []
    for course in pending_courses_cursor:
        # ✅ FIXED HERE: handle missing or non-objectId instructor_id
        instructor_id = course.get("instructor_id")
        instructor = users_collection.find_one({"_id": ObjectId(instructor_id)}) if instructor_id else None

        pending_courses.append({
            "id": str(course["_id"]),  # ✅ Fix here
            "title": course.get("title", ""),
            "description": course.get("description", ""),
            "instructor": instructor["username"] if instructor else "Unknown",
            "status": course.get("status", "unknown")
        })


    return render(request, "dashboard/course_overview.html", {
        "top_courses": top_courses,
        "pending_courses": pending_courses
    })

# Delete Course and Warn 
from django.core.mail import send_mail
from django.views.decorators.http import require_POST

@require_POST
def delete_course_and_warn(request, course_id):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    course = db["courses"].find_one({"_id": ObjectId(course_id)})
    if not course:
        return HttpResponse("Course not found", status=404)

    instructor = users_collection.find_one({"_id": ObjectId(course["instructor_id"])})
    instructor_email = instructor.get("email", "")
    instructor_name = instructor.get("username", "Unknown")

    db["courses"].delete_one({"_id": ObjectId(course_id)})

    db["user_activity_logs"].insert_one({
        "user_id": instructor["_id"],
        "action": f"❌ Course '{course['title']}' deleted by admin due to student report.",
        "performed_by": request.session.get("admin_name"),
        "timestamp": datetime.utcnow()
    })

    # ✅ Send email
    send_mail(
        subject="⚠️ Course Removed Due to Student Report",
        message=(
            f"Dear {instructor_name},\n\n"
            f"Your course \"{course['title']}\" has been removed by the admin because it was reported by a student.\n"
            f"If you believe this was a mistake, please contact the platform support.\n\n"
            f"Regards,\nAdmin Team"
        ),
        from_email="admin@ptp.com",
        recipient_list=[instructor_email],
        fail_silently=False,
    )

    return redirect('view_all_courses')

# Course Approve or Reject
@require_POST
def approve_course(request, course_id):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    course = db["courses"].find_one({"_id": ObjectId(course_id)})
    if not course:
        return HttpResponse("Course not found", status=404)

    instructor = users_collection.find_one({"_id": ObjectId(course["instructor_id"])})
    instructor_email = instructor.get("email")
    instructor_name = instructor.get("username", "Instructor")

    update_data = {"status": "approved"}

    if not course.get("created_at"):
        update_data["created_at"] = datetime.utcnow()

    db["courses"].update_one({"_id": ObjectId(course_id)}, {"$set": update_data})

    # ✅ Send approval email
    send_mail(
        subject="✅ Course Approved",
        message=(
            f"Dear {instructor_name},\n\n"
            f"Your course \"{course['title']}\" has been approved and is now visible to students.\n"
            f"Thank you for your contribution!\n\n"
            f"Best,\nAdmin Team"
        ),
        from_email="admin@ptp.com",
        recipient_list=[instructor_email],
        fail_silently=False,
    )
    return HttpResponseRedirect(reverse('course_overview'))

# Reject Course + Email
@require_POST
def reject_course(request, course_id):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    course = db["courses"].find_one({"_id": ObjectId(course_id)})
    if not course:
        return HttpResponse("Course not found", status=404)

    instructor = users_collection.find_one({"_id": ObjectId(course["instructor_id"])})
    instructor_email = instructor.get("email")
    instructor_name = instructor.get("username", "Instructor")

    db["courses"].delete_one({"_id": ObjectId(course_id)})

    # ✅ Send rejection email
    send_mail(
        subject="❌ Course Rejected",
        message=(
            f"Dear {instructor_name},\n\n"
            f"Unfortunately, your course \"{course['title']}\" was rejected by the admin.\n"
            f"If you’d like to revise and resubmit, please follow the guidelines or contact support.\n\n"
            f"Best,\nAdmin Team"
        ),
        from_email="admin@ptp.com",
        recipient_list=[instructor_email],
        fail_silently=False,
    )

    return HttpResponseRedirect(reverse('course_overview'))


# View All Courses
def view_all_courses(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    courses_collection = db["courses"]
    users_collection = db["users"]
    enrollments_collection = db["enrollments"]

    search = request.GET.get("search", "").strip().lower()
    sort_by = request.GET.get("sort", "newest")
    min_price = request.GET.get("min_price")
    max_price = request.GET.get("max_price")

    instructors = {
        str(u["_id"]): u["username"]
        for u in users_collection.find({"role": "instructor"})
    }

    enroll_agg = enrollments_collection.aggregate([
        {"$group": {"_id": "$course_id", "count": {"$sum": 1}}}
    ])
    enroll_counts = {str(e["_id"]): e["count"] for e in enroll_agg}

    course_cursor = courses_collection.find({"status": "approved"})
    courses = []

    for c in course_cursor:
        course_id = str(c["_id"])
        title = c.get("title", "")
        instructor_id = str(c.get("instructor_id"))
        instructor_name = instructors.get(instructor_id, "Unknown")
        count = enroll_counts.get(course_id, 0)
        price = c.get("price", 0)

        if search and search not in title.lower() and search not in instructor_name.lower():
            continue

        if min_price and price < int(min_price):
            continue
        if max_price and price > int(max_price):
            continue

        created_at = c.get("created_at")
        if isinstance(created_at, str):
            created_at = parse_datetime(created_at)
        if created_at is None:
            created_at = datetime.min.replace(tzinfo=timezone.utc)
        elif created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Calculate average rating for the course
        avg_rating = calculate_course_rating(c["_id"])
        
        courses.append({
            "id": course_id,
            "title": title,
            "instructor": instructor_name,
            "status": c.get("status", "unknown"),
            "enrollments": int(count),
            "created_at": created_at,
            "price": price,
            "avg_rating": avg_rating
        })

    if sort_by == "most_enrolled":
        courses.sort(key=lambda x: x["enrollments"], reverse=True)
    else:
        courses.sort(key=lambda x: x["created_at"], reverse=True)

    return render(request, "dashboard/view_all_course.html", {
        "courses": courses
    })

# Report
def report_view(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    reports_collection = db["reports"]
    users_collection = db["users"]
    courses_collection = db["courses"]

    total_reports = reports_collection.count_documents({"resolved_at": None})

    recent_reports = []
    cursor = reports_collection.find({"resolved_at": None}).sort("submitted_at", -1).limit(10)

    for r in cursor:
        student = users_collection.find_one({"_id": ObjectId(r["reported_by"])})
        course = courses_collection.find_one({"_id": ObjectId(r["target_course"])})

        recent_reports.append({
            "date": r.get("submitted_at"),
            "reported_by": student["username"] if student else "Unknown",
            "course_title": course["title"] if course else "Unknown",
            "reason": r.get("reason", ""),
        })

    return render(request, "dashboard/report.html", {
        "total_reports": total_reports,
        "recent_reports": recent_reports
    })

# View All Reports
@require_GET
def all_reports(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    filter_query = {}
    user_id = request.GET.get('user_id')
    course_id = request.GET.get('course_id')
    status = request.GET.get('status')
    date_str = request.GET.get('date')

    if user_id:
        filter_query["reported_by"] = user_id
    if course_id:
        filter_query["target_course"] = course_id
    if status == "resolved":
        filter_query["resolved_at"] = {"$ne": None}
    elif status == "unresolved":
        filter_query["resolved_at"] = None
    if date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d")
            next_day = day + timedelta(days=1)
            filter_query["submitted_at"] = {"$gte": day, "$lt": next_day}
        except:
            pass

    reports = list(db["reports"].find(filter_query).sort("submitted_at", -1))
    users = {str(u["_id"]): u["username"] for u in db["users"].find({})}
    courses = {str(c["_id"]): c["title"] for c in db["courses"].find({})}

    for r in reports:
        r["id"] = str(r["_id"])
        r["date"] = r.get("submitted_at")
        r["reported_by_name"] = users.get(r.get("reported_by"), "Unknown")
        r["course_title"] = courses.get(r.get("target_course"), "Unknown")

    return render(request, "dashboard/all_reports.html", {
        "reports": reports,
        "all_users": users,
        "all_courses": courses
    })

@require_POST
def resolve_report(request, report_id):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    db["reports"].update_one(
        {"_id": ObjectId(report_id)},
        {"$set": {"resolved_at": datetime.utcnow()}}
    )
    return redirect('all_reports')


# --- Admin: Enrollments monitor (who enrolled which course, approval status) ---
def enrollments_monitor(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    status_filter = request.GET.get('status', '')

    query = {}
    if status_filter:
        query["approval_status"] = status_filter

    cursor = enrollments_collection.find(query).sort("enrolled_at", -1)

    # Build lookup maps to reduce queries
    user_ids = set()
    course_ids = set()
    enrollments = list(cursor)
    for e in enrollments:
        user_ids.add(e.get('student_id'))
        course_ids.add(e.get('course_id'))

    users_map = {u["_id"]: u for u in users_collection.find({"_id": {"$in": list(user_ids)}})}
    course_map = {c["_id"]: c for c in courses_collection.find({"_id": {"$in": list(course_ids)}})}

    rows = []
    for e in enrollments:
        student = users_map.get(e.get('student_id'))
        course = course_map.get(e.get('course_id'))
        instructor = users_collection.find_one({"_id": course.get('instructor_id')}) if course else None
        rows.append({
            "enrollment_id": str(e.get('_id')),
            "student_name": student.get('username') if student else 'Unknown',
            "student_email": student.get('email') if student else '-',
            "student_status": student.get('is_active', False) if student else False,
            "course_title": course.get('title') if course else 'Unknown',
            "instructor_name": instructor.get('username') if instructor else 'Unknown',
            "approval_status": e.get('approval_status', 'Pending'),
            "enrolled_at": e.get('enrolled_at')
        })

    return render(request, 'dashboard/admin_enrollments.html', {
        'rows': rows,
        'status_filter': status_filter,
        'admin_name': request.session.get('admin_name', ''),
        'admin_photo': request.session.get('admin_photo', ''),
    })


# --- Admin: Payouts management for all enrollments ---
def admin_payouts(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    # Fetch all enrollments that are not yet marked as paid (including pending ones)
    cursor = enrollments_collection.find({
        "$or": [{"payout_status": {"$exists": False}}, {"payout_status": {"$ne": "Paid"}}]
    }).sort("enrolled_at", -1)

    enrollments = list(cursor)
    user_ids = set()
    course_ids = set()
    for e in enrollments:
        user_ids.add(e.get('student_id'))
        course_ids.add(e.get('course_id'))

    users_map = {u["_id"]: u for u in users_collection.find({"_id": {"$in": list(user_ids)}})}
    course_map = {c["_id"]: c for c in courses_collection.find({"_id": {"$in": list(course_ids)}})}

    rows = []
    total_due = 0
    approved_due = 0  # Separate counter for approved enrollments only
    
    for e in enrollments:
        student = users_map.get(e.get('student_id'))
        course = course_map.get(e.get('course_id'))
        if not course:
            continue
        instructor = users_collection.find_one({"_id": course.get('instructor_id')}) if course else None
        price = int(course.get('price', 0))
        instructor_share = int(round(price * 0.7))  # 70% to instructor
        approval_status = e.get('approval_status', 'Pending')
        
        # Only count approved enrollments toward total due for payout
        if approval_status == 'Approved':
            approved_due += instructor_share
        
        # Count all enrollments for display purposes
        total_due += instructor_share
        
        rows.append({
            "enrollment_id": str(e.get('_id')),
            "student_name": student.get('username') if student else 'Unknown',
            "student_email": student.get('email') if student else 'Unknown',
            "student_status": student.get('is_active', False) if student else False,
            "course_title": course.get('title', 'Unknown'),
            "instructor_name": instructor.get('username') if instructor else 'Unknown',
            "instructor_email": instructor.get('email') if instructor else '-',
            "price": price,
            "instructor_share": instructor_share,
            "approval_status": approval_status,
            "enrolled_at": e.get('enrolled_at'),
        })

    # Calculate Admin Available Balance (30% commission)
    # Get total revenue from all enrollments (including paid ones)
    total_revenue_data = enrollments_collection.aggregate([
        {
            "$lookup": {
                "from": "courses",
                "localField": "course_id",
                "foreignField": "_id",
                "as": "course"
            }
        },
        {"$unwind": "$course"},
        {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
    ])
    total_revenue = next(total_revenue_data, {}).get('total', 0)
    admin_commission = int(total_revenue * 0.3)  # 30% to admin
    
    # Calculate total admin withdrawals
    admin_withdrawals_data = db["withdrawals"].aggregate([
        {"$match": {"role": "admin"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ])
    total_admin_withdrawals = next(admin_withdrawals_data, {}).get('total', 0)
    
    # Calculate admin available balance
    admin_available_balance = admin_commission - total_admin_withdrawals

    return render(request, 'dashboard/admin_payouts.html', {
        'rows': rows,
        'total_due': total_due,
        'approved_due': approved_due,  # Only approved enrollments
        'admin_available_balance': admin_available_balance,  # Admin's 30% commission balance
        'admin_commission': admin_commission,  # Total 30% commission earned
        'total_admin_withdrawals': total_admin_withdrawals,  # Total withdrawn by admin
        'admin_name': request.session.get('admin_name', ''),
        'admin_photo': request.session.get('admin_photo', ''),
    })


@require_POST
def mark_payout_paid(request, enrollment_id):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    en = enrollments_collection.find_one({"_id": ObjectId(enrollment_id)})
    if not en:
        return HttpResponse("Enrollment not found", status=404)

    course = courses_collection.find_one({"_id": en.get('course_id')})
    if not course:
        return HttpResponse("Course not found", status=404)

    instructor = users_collection.find_one({"_id": course.get('instructor_id')})

    price = int(course.get('price', 0))
    instructor_share = int(round(price * 0.7))

    # Insert payout record
    db['payouts'].insert_one({
        'enrollment_id': en['_id'],
        'instructor_id': course.get('instructor_id'),
        'course_id': en.get('course_id'),
        'amount': instructor_share,
        'paid_at': datetime.utcnow(),
        'paid_by': request.session.get('admin_name', 'admin')
    })

    # Mark enrollment as paid
    enrollments_collection.update_one(
        {"_id": en['_id']},
        {"$set": {"payout_status": "Paid"}}
    )

    # Optional: notify instructor by email
    try:
        if instructor and instructor.get('email'):
            send_mail(
                subject=f"Payout Processed: {course.get('title', 'Course')}",
                message=(
                    f"Dear {instructor.get('username', 'Instructor')},\n\n"
                    f"You have been paid {instructor_share} MMK for an approved enrollment in \"{course.get('title', 'Course')}\".\n"
                    f"Regards,\nAdmin Team"
                ),
                from_email=getattr(settings, 'EMAIL_HOST_USER', 'admin@ptp.com'),
                recipient_list=[instructor.get('email')],
                fail_silently=True,
            )
    except Exception:
        pass

    return redirect('admin_payouts')


@require_POST
def process_pending_payout(request, enrollment_id):
    """Process pending enrollment payout - add instructor share to their balance"""
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    en = enrollments_collection.find_one({"_id": ObjectId(enrollment_id)})
    if not en:
        return HttpResponse("Enrollment not found", status=404)

    # Check if enrollment is indeed pending
    if en.get('approval_status') != 'Pending':
        return HttpResponse("This enrollment is not pending", status=400)

    course = courses_collection.find_one({"_id": en.get('course_id')})
    if not course:
        return HttpResponse("Course not found", status=404)

    instructor = users_collection.find_one({"_id": course.get('instructor_id')})
    if not instructor:
        return HttpResponse("Instructor not found", status=404)

    price = int(course.get('price', 0))
    instructor_share = int(round(price * 0.7))  # 70% to instructor
    admin_share = int(round(price * 0.3))  # 30% to admin

    # Insert payout record (this adds to instructor's available balance)
    payout_result = db['payouts'].insert_one({
        'enrollment_id': en['_id'],
        'instructor_id': course.get('instructor_id'),
        'course_id': en.get('course_id'),
        'amount': instructor_share,
        'paid_at': datetime.utcnow(),
        'paid_by': request.session.get('admin_name', 'admin'),
        'payout_type': 'pending_processed',  # Mark this as processed from pending
        'note': f'Processed from pending by admin: {request.session.get("admin_name")}'
    })

    # Update platform balance (admin gets 30% commission)
    current_platform_balance = db["platform_balance"].find_one({})
    if current_platform_balance and 'balance' in current_platform_balance:
        new_platform_balance = current_platform_balance['balance'] + admin_share
    else:
        # Calculate initial balance if it doesn't exist
        total_revenue_data = enrollments_collection.aggregate([
            {
                "$lookup": {
                    "from": "courses",
                    "localField": "course_id",
                    "foreignField": "_id",
                    "as": "course"
                }
            },
            {"$unwind": "$course"},
            {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
        ])
        total_revenue = next(total_revenue_data, {}).get('total', 0)
        platform_commission = int(total_revenue * 0.3)
        
        # Calculate total admin withdrawals
        total_admin_withdrawals_data = db["withdrawals"].aggregate([
            {"$match": {"role": "admin"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ])
        total_admin_withdrawals = next(total_admin_withdrawals_data, {}).get('total', 0)
        
        new_platform_balance = platform_commission - total_admin_withdrawals
    
    # Update the platform balance
    db["platform_balance"].update_one(
        {},
        {"$set": {"balance": new_platform_balance}},
        upsert=True
    )

    # Update enrollment status to mark as processed
    enrollments_collection.update_one(
        {"_id": en['_id']},
        {"$set": {
            "payout_status": "Paid",
            "processed_at": datetime.utcnow(),
            "processed_by": request.session.get('admin_name', 'admin')
        }}
    )

    # Send notification email to instructor
    try:
        if instructor and instructor.get('email'):
            send_mail(
                subject=f"Balance Added: {course.get('title', 'Course')}",
                message=(
                    f"Dear {instructor.get('username', 'Instructor')},\n\n"
                    f"Good news! {instructor_share} MMK has been added to your available balance "
                    f"for the enrollment in \"{course.get('title', 'Course')}\".\n\n"
                    f"You can now withdraw this amount from your instructor dashboard.\n\n"
                    f"Course: {course.get('title', 'Course')}\n"
                    f"Amount Added: {instructor_share} MMK (70% instructor share)\n"
                    f"Admin Commission: {admin_share} MMK (30% platform fee)\n"
                    f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"Best regards,\nAdmin Team"
                ),
                from_email=getattr(settings, 'EMAIL_HOST_USER', 'admin@ptp.com'),
                recipient_list=[instructor.get('email')],
                fail_silently=True,
            )
    except Exception as e:
        print(f"Failed to send email notification: {e}")

    return redirect('admin_payouts')


# --- Admin Platform Commission Withdrawal ---
@require_POST
def admin_withdraw_platform_commission(request):
    if not request.session.get('admin_name'):
        return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)
    
    try:
        print("Starting withdrawal process...")  # Debug log
        withdrawal_amount = float(request.POST.get('withdrawal_amount', 0))
        print(f"Withdrawal amount: {withdrawal_amount}")  # Debug log
        
        if withdrawal_amount <= 0:
            return JsonResponse({"success": False, "error": "Withdrawal amount must be greater than zero."})
        
        # Get the current platform balance
        platform_balance = db["platform_balance"].find_one({})
        print(f"Initial platform balance: {platform_balance}")  # Debug log
        
        if not platform_balance or 'balance' not in platform_balance:
            print("No existing balance found, calculating initial balance...")  # Debug log
            # If no balance exists, calculate it from enrollments and withdrawals
            total_revenue_data = list(enrollments_collection.aggregate([
                {
                    "$lookup": {
                        "from": "courses",
                        "localField": "course_id",
                        "foreignField": "_id",
                        "as": "course"
                    }
                },
                {"$unwind": "$course"},
                {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
            ]))
            print(f"Total revenue data: {total_revenue_data}")  # Debug log
            total_revenue = total_revenue_data[0]['total'] if total_revenue_data else 0
            platform_commission = int(total_revenue * 0.3)
            
            # Calculate total admin withdrawals
            total_admin_withdrawals_data = list(db["withdrawals"].aggregate([
                {"$match": {"role": "admin"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ]))
            print(f"Total withdrawals data: {total_admin_withdrawals_data}")  # Debug log
            total_admin_withdrawals = total_admin_withdrawals_data[0]['total'] if total_admin_withdrawals_data else 0
            
            current_balance = platform_commission - total_admin_withdrawals
            print(f"Calculated initial balance: {current_balance}")  # Debug log
            
            # Store the initial balance
            result = db["platform_balance"].update_one(
                {},
                {"$set": {"balance": current_balance}},
                upsert=True
            )
            print(f"Update result: {result.raw_result}")  # Debug log
        else:
            current_balance = platform_balance['balance']
            print(f"Using existing balance: {current_balance}")  # Debug log
        
        if withdrawal_amount > current_balance:
            return JsonResponse({"success": False, "error": f"Insufficient balance. Available: {current_balance:,.2f} MMK"})
        
        # Calculate new balance
        new_balance = current_balance - withdrawal_amount
        print(f"New balance after withdrawal: {new_balance}")  # Debug log
        
        # Get the current platform commission
        enrollments_collection = db["enrollments"]
        platform_commission = 0
        try:
            commission_data = list(enrollments_collection.aggregate([
                {"$lookup": {"from": "courses", "localField": "course_id", "foreignField": "_id", "as": "course"}},
                {"$unwind": "$course"},
                {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
            ]))
            print(f"Commission data: {commission_data}")  # Debug log
            platform_commission = int((commission_data[0]['total'] if commission_data else 0) * 0.3)
        except Exception as e:
            print(f"Error calculating platform commission: {str(e)}")
            return JsonResponse({"success": False, "error": f"Error calculating platform commission: {str(e)}"})
        
        # Record the withdrawal
        withdrawal_record = {
            "type": "admin_balance_withdrawal",
            "role": "admin",
            "amount": withdrawal_amount,
            "withdrawn_by": request.session.get('admin_name', 'admin'),
            "withdrawn_at": datetime.utcnow(),
            "balance_before": current_balance,
            "balance_after": new_balance,
            "platform_commission": platform_commission
        }
        print(f"Withdrawal record: {withdrawal_record}")  # Debug log
        
        try:
            # Insert withdrawal record
            db["withdrawals"].insert_one(withdrawal_record)
            
            # Update the platform balance
            db["platform_balance"].update_one(
                {},
                {"$set": {"balance": new_balance}},
                upsert=True
            )
            print("Withdrawal processed successfully")  # Debug log
            
        except Exception as e:
            print(f"Error processing withdrawal: {str(e)}")  # Debug log
            return JsonResponse({"success": False, "error": f"Failed to process withdrawal: {str(e)}"})
        
        # Send email notification (non-critical operation, so outside transaction)
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            
            subject = "Admin Balance Withdrawal"
            message = f"""
Admin Balance Withdrawal Notification

Amount Withdrawn: {withdrawal_amount:,.2f} MMK
Withdrawn By: {request.session.get('admin_name', 'admin')}
Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
Current Balance Before: {current_balance:,.2f} MMK
Current Balance After: {new_balance:,.2f} MMK
Total Platform Commission: {platform_commission:,.2f} MMK

This withdrawal has been processed successfully.
            """
            
            # Send to admin email (you can configure this in settings)
            admin_email = getattr(settings, 'ADMIN_EMAIL', 'admin@ptp.com')
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'EMAIL_HOST_USER', 'noreply@ptp.com'),
                recipient_list=[admin_email],
                fail_silently=True
            )
            print("Email notification sent")  # Debug log
        except Exception as e:
            print(f"Failed to send withdrawal email: {str(e)}")
        
        return JsonResponse({"success": True, "message": f"Successfully withdrew {withdrawal_amount:,.2f} MMK from current balance."})
        
    except ValueError as e:
        print(f"ValueError: {str(e)}")  # Debug log
        return JsonResponse({"success": False, "error": "Invalid withdrawal amount. Please enter a valid number."})
    except Exception as e:
        print(f"Unexpected error: {str(e)}")  # Debug log
        import traceback
        print(traceback.format_exc())  # Print full traceback
        return JsonResponse({"success": False, "error": f"An error occurred: {str(e)}"})


# Clear all withdrawals
@require_POST
def clear_withdrawals(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')
    
    try:
        # Delete all admin withdrawals
        result = db["withdrawals"].delete_many({"role": "admin"})
        
        from django.http import JsonResponse
        return JsonResponse({
            "success": True, 
            "message": f"Successfully cleared {result.deleted_count} withdrawal records."
        })
        
    except Exception as e:
        return JsonResponse({
            "success": False, 
            "error": f"An error occurred while clearing withdrawals: {str(e)}"
        })


def admin_withdraw_view(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')
    
    # First, check if there's a stored platform balance
    platform_balance = db["platform_balance"].find_one({})
    
    if platform_balance and 'balance' in platform_balance:
        # Use the stored balance if it exists
        current_balance = platform_balance['balance']
    else:
        # Calculate initial balance if it doesn't exist
        total_revenue_data = enrollments_collection.aggregate([
            {
                "$lookup": {
                    "from": "courses",
                    "localField": "course_id",
                    "foreignField": "_id",
                    "as": "course"
                }
            },
            {"$unwind": "$course"},
            {"$group": {"_id": None, "total": {"$sum": "$course.price"}}}
        ])
        total_revenue = next(total_revenue_data, {}).get('total', 0)
        platform_commission = total_revenue * 0.3  # 30% platform commission
        
        # Calculate total admin withdrawals
        total_admin_withdrawals = db["withdrawals"].aggregate([
            {"$match": {"role": "admin"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ])
        total_admin_withdrawals = next(total_admin_withdrawals, {}).get('total', 0)
        
        # Calculate current balance
        current_balance = platform_commission - total_admin_withdrawals
        
        # Store the initial balance
        db["platform_balance"].update_one(
            {},
            {"$set": {"balance": current_balance}},
            upsert=True
        )
    
    # Get recent admin withdrawals
    recent_withdrawals = list(db["withdrawals"].find({"role": "admin"}).sort("withdrawn_at", -1).limit(10))
    
    return render(request, 'dashboard/admin_withdraw.html', {
        'available_commission': current_balance,
        'recent_withdrawals': recent_withdrawals,
        'admin_name': request.session.get('admin_name', ''),
        'admin_photo': request.session.get('admin_photo', ''),
    })
