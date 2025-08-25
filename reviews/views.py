from django.shortcuts import render, redirect
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import json

client = MongoClient("localhost", 27017)
db = client["Peer_to_Peer_Education"]
reviews_col = db["reviews"]
enrollments_col = db["enrollments"]
courses_col = db["courses"]
students_col = db["students"]


def write_review(request):
    if not request.session.get("student_id"):
        return redirect("student_login")

    student_id = ObjectId(request.session["student_id"])

    # Get student info for header/profile
    student = db["users"].find_one(
        {"_id": student_id, "role": "student"},
        {"username": 1, "profile_photo": 1}
    )
    student_name = student.get("username", "Unknown") if student else "Unknown"
    student_profile_pic = student.get("profile_photo") if student else None

    # Get all courses the student enrolled in
    enrollments = enrollments_col.find({"student_id": student_id})
    enrolled_course_ids = [enroll["course_id"] for enroll in enrollments]

    courses_raw = list(courses_col.find({"_id": {"$in": enrolled_course_ids}}))

    # Convert _id to string 'id' for safe use in Django template
    courses = []
    for c in courses_raw:
        courses.append({
            "id": str(c["_id"]),
            "title": c.get("title", "")
        })

    context = {
        "courses": courses,
        "student_name": student_name,
        "student_profile_pic": student_profile_pic,
    }

    if request.method == "POST":
        course_id = request.POST.get("course_id")
        comment = request.POST.get("comment", "").strip()
        rating = int(request.POST.get("rating", 0))

        if not course_id or not comment or rating < 1 or rating > 5:
            context["error"] = "Please select a course, write a comment, and select a rating between 1 and 5."
            return render(request, "reviews/write_review.html", context)

        review_doc = {
            "student_id": student_id,
            "course_id": ObjectId(course_id),
            "rating": rating,
            "comment": comment,
            "reviewed_at": datetime.utcnow()
        }

        reviews_col.insert_one(review_doc)

        context["success"] = "Your review has been submitted successfully!"

    return render(request, "reviews/write_review.html", context)


# View Student Reviews
def my_reviews(request):
    if not request.session.get("student_id"):
        return redirect("student_login")

    student_id = ObjectId(request.session["student_id"])

    # Get student from users collection
    student = db["users"].find_one(
        {"_id": student_id, "role": "student"},
        {"username": 1, "profile_photo": 1}
    )

    if not student:
        return render(request, "reviews/my_review.html", {
            "reviews": [],
            "student_name": "Unknown",
            "student_profile_pic": None,
            "error": "Student profile not found."
        })

    # Fetch reviews for this student
    reviews = list(reviews_col.find({"student_id": student_id}))

    # Add course titles + formatted date
    for r in reviews:
        course = courses_col.find_one({"_id": r["course_id"]}, {"title": 1})
        r["course_title"] = course["title"] if course else "Unknown Course"
        r["reviewed_at_str"] = r["reviewed_at"].strftime("%Y-%m-%d %H:%M")
        r["id"] = str(r["_id"])  # Add string ID for template use

    # Prepare lightweight JSON for client-side restore without extra templating
    reviews_for_json = [
        {
            "id": r["id"],
            "courseTitle": r.get("course_title", "Unknown Course"),
            "rating": int(r.get("rating", 0)),
            "comment": r.get("comment", ""),
            "reviewedAt": r.get("reviewed_at_str", "")
        }
        for r in reviews
    ]

    context = {
        "reviews": reviews,
        "student_name": student.get("username", "Unknown"),
        "student_profile_pic": student.get("profile_photo"),
        "reviews_json": json.dumps(reviews_for_json),
        "student_id_str": str(student_id)
    }
    return render(request, "reviews/my_review.html", context)


def delete_all_reviews(request):
    if not request.session.get("student_id"):
        return redirect("student_login")
    
    if request.method == "POST":
        student_id = ObjectId(request.session["student_id"])
        
        # Delete all reviews for this student
        result = reviews_col.delete_many({"student_id": student_id})
        
        # Return JSON response
        from django.http import JsonResponse
        return JsonResponse({
            "success": True,
            "deleted_count": result.deleted_count,
            "message": f"Successfully deleted {result.deleted_count} reviews"
        })
    
    return JsonResponse({"success": False, "message": "Invalid request method"})


# Instructor Part

from django.shortcuts import render, redirect
from django.http import HttpResponse
from pymongo import MongoClient
from bson.objectid import ObjectId, InvalidId
from users.views import manual_login_required, manual_instructor_required, load_session, save_session


def get_mongo_connection():
    """Helper function to establish a MongoDB connection."""
    client = None
    try:
        client = MongoClient("localhost", 27017, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client["Peer_to_Peer_Education"]
        return client, db
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        if client:
            client.close()
        raise Exception("Could not connect to database.")


@manual_login_required
@manual_instructor_required
def instructor_reviews_view(request):
    """
    Displays a list of all reviews for the instructor's courses.
    """
    client = None
    try:
        client, db = get_mongo_connection()
        reviews_collection = db['reviews']
        courses_collection = db['courses']
        users_collection = db['users']

        # Get instructor_id from the manually managed session
        instructor_id = request.session_data.get('user_id')
        if not instructor_id:
            return redirect('instructor_login')

        try:
            instructor_object_id = ObjectId(instructor_id)
        except InvalidId:
            return HttpResponse("Invalid user ID format. Please log in again.", status=400)

        # 1. Fetch the instructor's profile photo and details for the sidebar
        instructor_doc = users_collection.find_one(
            {"_id": instructor_object_id},
            {"username": 1, "email": 1, "profile_photo": 1}
        )
        if not instructor_doc:
            return HttpResponse("Instructor not found.", status=404)

        # 2. Find all courses taught by this instructor
        instructor_courses = list(courses_collection.find(
            {"instructor_id": instructor_object_id},
            {"_id": 1, "title": 1}
        ))

        instructor_course_ids = [course['_id'] for course in instructor_courses]
        instructor_course_titles = {str(course['_id']): course['title'] for course in instructor_courses}

        # 3. Find all reviews for these courses using a proper $in query
        reviews_cursor = reviews_collection.find(
            {"course_id": {"$in": instructor_course_ids}}
        ).sort("reviewed_at", -1)

        reviews_list = []
        # 4. Populate student username and course title for each review
        for review in reviews_cursor:
            student_doc = users_collection.find_one({"_id": review['student_id']}, {"username": 1})
            review['student_username'] = student_doc['username'] if student_doc else 'Unknown Student'
            review['course_title'] = instructor_course_titles.get(str(review['course_id']), 'Unknown Course')
            reviews_list.append(review)

        context = {
            'instructor_photo': instructor_doc.get('profile_photo'),
            'instructor_name': instructor_doc.get('username'),
            'instructor_email': instructor_doc.get('email'),
            'reviews': reviews_list,
        }

        response = render(request, 'reviews/instructor_reviews.html', context)
        save_session(response, request.session_id, request.session_data)
        return response

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return HttpResponse(f"An unexpected error occurred: {e}", status=500)
    finally:
        if client:
            client.close()
