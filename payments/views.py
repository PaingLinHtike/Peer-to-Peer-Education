from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET
import pymongo

connection = pymongo.MongoClient("localhost", 27017)
db = connection["Peer_to_Peer_Education"]
users_collection = db["users"]

# view_all_payments
@require_GET
def view_all_payments(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    payments_collection = db["payments"]
    users_collection = db["users"]
    courses_collection = db["courses"]

    users = {str(u["_id"]): u["username"] for u in users_collection.find({"role": "student"})}
    courses = {str(c["_id"]): c["title"] for c in courses_collection.find()}

    payment_cursor = payments_collection.find().sort("paid_at", -1)

    payments = []
    for p in payment_cursor:
        payments.append({
            "student": users.get(str(p.get("student_id")), "Unknown"),
            "course": courses.get(str(p.get("course_id")), "Unknown"),
            "amount": p.get("amount", 0),
            "method": p.get("payment_method", ""),
            "date": p.get("paid_at")
        })

    return render(request, "payments/view_all_payments.html", {"payments": payments})

# View All Withdrawals
@require_GET
def view_withdrawals(request):
    if not request.session.get('admin_name'):
        return redirect('admin_login')

    withdrawals_collection = db["withdrawals"]
    users_collection = db["users"]
    
    withdrawals = []
    # Filter to show only instructor withdrawals (exclude admin withdrawals)
    for w in withdrawals_collection.find({"role": "instructor"}).sort("requested_at", -1):
        instructor_id = w.get("instructor_id")
        
        # Get instructor information
        instructor_doc = users_collection.find_one({"_id": instructor_id})
        instructor_name = instructor_doc.get("username", "Unknown") if instructor_doc else "Unknown"
        
        # Calculate instructor's current available balance
        current_balance = 0
        if instructor_id:
            try:
                earnings_summary = get_instructor_earnings(db, instructor_id)
                current_balance = earnings_summary.get('current_balance', 0)
            except Exception as e:
                print(f"Error calculating balance for instructor {instructor_id}: {e}")
                current_balance = 0
        
        withdrawals.append({
            "instructor": instructor_name,
            "withdrawal_amount": w.get("amount", 0),
            "date": w.get("requested_at"),  # Changed from "paid_at" to "requested_at"
            "course_earning": current_balance  # Show current available balance
        })

    return render(request, "payments/view_withdrawals.html", {"withdrawals": withdrawals})


# Instructor Part
# payments/views.py

from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_protect
import pymongo
from bson.objectid import ObjectId, InvalidId
import datetime
from users.views import manual_login_required, manual_instructor_required, load_session, save_session, \
    get_instructor_context


def get_db():
    """Establishes a connection to the MongoDB database."""
    try:
        connection = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=5000)
        connection.admin.command('ping')  # Check the connection
        return connection["Peer_to_Peer_Education"], connection
    except pymongo.errors.ConnectionFailure as e:
        print(f"Error: Could not connect to MongoDB: {e}")
        return None, None


def get_instructor_earnings(db, instructor_object_id):
    """
    Helper function to calculate total sales, total withdrawals, and current balance for an instructor.
    This function ensures the balance is always calculated from the most up-to-date data.
    Instructors now only earn from course fees (70%) - no admin salary.
    """
    courses_collection = db["courses"]
    enrollments_collection = db["enrollments"]
    payouts_collection = db["payouts"]
    withdrawals_collection = db["withdrawals"]

    # Get all course IDs for the current instructor
    instructor_course_ids = [
        c["_id"] for c in courses_collection.find({"instructor_id": instructor_object_id}, {"_id": 1})
    ]

    # Calculate totals from payouts (only after admin marks as paid)
    pipeline_payouts = [
        {"$match": {"instructor_id": instructor_object_id}},
        {"$group": {"_id": None, "total_payouts": {"$sum": "$amount"}}}
    ]
    total_payouts_doc = list(payouts_collection.aggregate(pipeline_payouts))
    earnings_from_courses = total_payouts_doc[0]["total_payouts"] if total_payouts_doc else 0

    # Derive gross sales and platform fee from payouts
    total_sales = int(round(earnings_from_courses / 0.7)) if earnings_from_courses else 0

    # Calculate total withdrawals
    pipeline_withdrawals = [
        {"$match": {"instructor_id": instructor_object_id}},
        {"$group": {
            "_id": None,
            "total_withdrawals": {"$sum": "$amount"}
        }}
    ]
    total_withdrawals_doc = list(withdrawals_collection.aggregate(pipeline_withdrawals))
    total_withdrawals = total_withdrawals_doc[0]["total_withdrawals"] if total_withdrawals_doc else 0

    # Calculate the final balance - only from course earnings (no admin salary)
    platform_fee = total_sales - earnings_from_courses
    current_balance = earnings_from_courses - total_withdrawals

    return {
        "total_sales": total_sales,
        "total_withdrawals": total_withdrawals,
        "current_balance": current_balance,
        "earnings_from_courses": earnings_from_courses,
        "platform_fee": platform_fee
    }


@manual_login_required
@manual_instructor_required
def instructor_earnings_view(request):
    """
    Renders the instructor's earnings page, fetching data from the database.
    This version dynamically calculates earnings based on enrollments and withdrawals.
    """
    db, conn = get_db()

    if db is None:
        return HttpResponse("Database connection failed. Please check if MongoDB is running.", status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id
        instructor_id = request.session_data.get("user_id")

        if not instructor_id:
            print("ERROR: user_id is missing from the session. Redirecting to login.")
            return redirect('instructor_login')

        try:
            instructor_object_id = ObjectId(instructor_id)
        except InvalidId:
            print(f"ERROR: Invalid instructor_id '{instructor_id}' in session.")
            return HttpResponse("Invalid user ID format. Please log in again.", status=400)

        # Get relevant collections
        courses_collection = db["courses"]
        payouts_collection = db["payouts"]

        # --- Aggregation Pipeline for Monthly Earnings ---
        # Get all course IDs for the current instructor
        instructor_course_ids = [
            c["_id"] for c in courses_collection.find({"instructor_id": instructor_object_id}, {"_id": 1})
        ]

        # Group payouts (instructor net) by paid month
        pipeline = [
            {"$match": {"instructor_id": instructor_object_id}},
            {"$project": {
                "month": {"$month": "$paid_at"},
                "year": {"$year": "$paid_at"},
                "amount": 1
            }},
            {"$group": {"_id": {"year": "$year", "month": "$month"}, "total_net": {"$sum": "$amount"}}},
            {"$sort": {"_id.year": 1, "_id.month": 1}}
        ]

        monthly_earnings_cursor = payouts_collection.aggregate(pipeline)
        monthly_earnings_list = []

        # Get total earnings for final balance
        earnings_summary = get_instructor_earnings(db, instructor_object_id)
        current_balance = earnings_summary['current_balance']

        for doc in monthly_earnings_cursor:
            earnings_from_courses = doc["total_net"]  # already net 70%
            total_sales = int(round(earnings_from_courses / 0.7)) if earnings_from_courses else 0
            platform_fee = total_sales - earnings_from_courses
            # Only course earnings - no admin salary
            total_final_earnings = earnings_from_courses

            monthly_earnings_list.append({
                "month_year": datetime.date(doc["_id"]["year"], doc["_id"]["month"], 1).strftime("%B %Y"),
                "total_sales": f"{total_sales:,.2f}",
                "platform_fee": f"{platform_fee:,.2f}",
                "earnings_from_courses": f"{earnings_from_courses:,.2f}",
                "total_final_earnings": f"{total_final_earnings:,.2f}",
            })

        context = {
            "monthly_earnings": monthly_earnings_list,
            "current_balance": f"{current_balance:,.2f}",
            **get_instructor_context(request)
        }

        response = render(request, "payments/instructor_earnings.html", context)
        save_session(response, request.session_id, request.session_data)
        return response

    except Exception as e:
        print(f"FATAL ERROR: An unexpected exception occurred in instructor_earnings_view: {e}")
        return HttpResponse("An internal server error occurred. Please check the server logs for details.", status=500)
    finally:
        if conn is not None:
            conn.close()


@csrf_protect
@manual_login_required
@manual_instructor_required
def instructor_withdrawals_view(request):
    db, conn = get_db()
    if db is None:
        return HttpResponse("Database connection failed. Please check if MongoDB is running.", status=500)

    try:
        withdrawals_collection = db['withdrawals']
        users_collection = db['users']
        admin_notifications_collection = db['admin_notifications']  # New collection for admin notifications
        message = ""

        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id
        instructor_id = request.session_data.get('user_id')

        if not instructor_id:
            response = HttpResponse("Instructor ID not found in session.", status=400)
            save_session(response, request.session_id, request.session_data)
            return response

        try:
            instructor_object_id = ObjectId(instructor_id)
        except InvalidId:
            return HttpResponse("Invalid instructor ID format.", status=400)

        # Get the instructor's name for the e-script
        instructor_doc = users_collection.find_one({"_id": instructor_object_id})
        instructor_name = instructor_doc.get("username", "Unknown Instructor")  # Use username instead of name
        instructor_email = instructor_doc.get("email", "N/A")

        # Handle withdrawal request
        if request.method == "POST":
            withdrawal_amount_str = request.POST.get('withdrawal_amount')
            try:
                withdrawal_amount = float(withdrawal_amount_str)
                if withdrawal_amount <= 0:
                    message = "Withdrawal amount must be greater than zero."
                else:
                    # Check for available balance using the dynamic helper function
                    earnings_summary = get_instructor_earnings(db, instructor_object_id)
                    current_balance = earnings_summary['current_balance']

                    if withdrawal_amount > current_balance:
                        message = "Insufficient balance for this withdrawal."
                    else:
                        # Process the withdrawal immediately
                        requested_at = datetime.datetime.utcnow()

                        # Create the e-script content to be saved locally
                        e_script_content = (
                            f"Withdrawal E-Script for {instructor_name} ({instructor_email}):\n"
                            f"  - Amount: {withdrawal_amount:,.2f} MMK\n"
                            f"  - Date & Time: {requested_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        )

                        new_withdrawal = {
                            "instructor_id": instructor_object_id,
                            "role": "instructor",
                            "amount": withdrawal_amount,
                            "status": "completed",
                            "requested_at": requested_at,
                            "is_script_sent": True,
                            "email_content": e_script_content  # Save the email content locally
                        }
                        withdrawals_collection.insert_one(new_withdrawal)

                        # Create and save the admin notification
                        admin_notifications_collection.insert_one({
                            "instructor_id": instructor_object_id,
                            "instructor_name": instructor_name,
                            "withdrawal_amount": withdrawal_amount,
                            "withdrawal_date_time": requested_at,
                            "type": "withdrawal_notification"
                        })
                        message = "Withdrawal completed successfully! Admin has been notified and the script has been saved."

            except (ValueError, TypeError):
                message = "Invalid withdrawal amount. Please enter a number."

        # Fetch withdrawals for the logged-in instructor for display
        withdrawals_cursor = withdrawals_collection.find(
            {"instructor_id": instructor_object_id}
        ).sort("requested_at", -1)

        withdrawals_list = list(withdrawals_cursor)

        # Get the latest balance and total withdrawals after processing the request
        earnings_summary = get_instructor_earnings(db, instructor_object_id)
        current_balance = earnings_summary['current_balance']
        total_withdrawals = earnings_summary['total_withdrawals']

        context = {
            'withdrawals': withdrawals_list,
            'total_withdrawals': f"{total_withdrawals:,.2f}",
            'current_balance': f"{current_balance:,.2f}",
            'message': message,
            **get_instructor_context(request)
        }
        response = render(request, 'payments/instructor_withdrawals.html', context)
        save_session(response, request.session_id, request.session_data)
        return response
    except Exception as e:
        print(f"FATAL ERROR: An unexpected exception occurred in instructor_withdrawals_view: {e}")
        return HttpResponse(f"An internal server error occurred: {e}", status=500)
    finally:
        if conn:
            conn.close()
