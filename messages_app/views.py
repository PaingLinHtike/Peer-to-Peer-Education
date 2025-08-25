import datetime
from django.shortcuts import render, redirect
from bson import ObjectId
from functools import wraps
from pymongo import MongoClient

# Connect to MongoDB
try:
    client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
    db = client['Peer_to_Peer_Education']
    
    # Test the connection
    db.command('ping')
    
    messages_collection = db['messages']
    courses_collection = db['courses']
    users_collection = db['users']
    
    print("MongoDB connection established successfully")
except Exception as e:
    print(f"Failed to establish initial MongoDB connection: {e}")
    print(f"Error type: {type(e).__name__}")
    print(f"Error details: {str(e)}")
    
    # Set collections to None so other functions can handle the error
    client = None
    db = None
    messages_collection = None
    courses_collection = None
    users_collection = None

# Decorator to ensure student is logged in
def student_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get('student_id'):
            return redirect('student_login')  # Redirect to login if not logged in
        return view_func(request, *args, **kwargs)
    return wrapper

@student_login_required
def inbox(request):
    student_id = request.session.get('student_id')
    try:
        student_obj_id = ObjectId(student_id)
    except:
        return redirect('student_login')

    conversations = messages_collection.find({'participants': student_obj_id})

    inbox_list = []
    for convo in conversations:
        other_participant_id = next(
            (p for p in convo.get('participants', []) if p != student_obj_id),
            None
        )

        other_user_doc = users_collection.find_one({'_id': other_participant_id})
        other_user_name = other_user_doc.get('username') if other_user_doc else "Unknown"

        course_doc = courses_collection.find_one({'_id': convo.get('course_id')})
        course_title = course_doc.get('title') if course_doc else "Unknown Course"

        if convo.get('messages'):
            last_message = max(convo['messages'], key=lambda m: m['sent_at'])
            sent_at = last_message['sent_at'].strftime("%Y-%m-%d %H:%M")
            last_message_content = last_message.get('content', '')
        else:
            sent_at = "N/A"
            last_message_content = "No messages"

        inbox_list.append({
            'other_user': other_user_name,
            'course': course_title,
            'date': sent_at,
            'message': last_message_content,
            'conversation_id': str(convo['_id']),
        })

    student_name = request.session.get('student_name', '')
    student_profile_pic = request.session.get(
        'student_photo',
        'users/default_profile.png'
    )

    return render(request, 'messages_app/inbox.html', {
        'inbox_list': inbox_list,
        'student_name': student_name,
        'student_profile_pic': student_profile_pic,
    })


@student_login_required
def send_message(request):
    student_id = request.session.get('student_id')
    try:
        student_obj_id = ObjectId(student_id)
    except:
        return redirect('student_login')

    # Connect to collections
    enrollments_collection = db['enrollments']

    # 1️⃣ Get all course_ids the student is enrolled in
    enrolled_course_ids = [
        e['course_id']
        for e in enrollments_collection.find({'student_id': student_obj_id})
    ]

    if not enrolled_course_ids:
        return render(request, 'messages_app/send_message.html', {
            'student_name': request.session.get('student_name', ''),
            'student_profile_pic': request.session.get('student_photo', 'users/default_profile.png'),
            'error': "You are not enrolled in any courses, so you cannot send messages."
        })

    # 2️⃣ Get courses and instructors for these course_ids
    courses_cursor = courses_collection.find({'_id': {'$in': enrolled_course_ids}})
    instructor_course_map = {}
    instructor_ids = set()

    for course in courses_cursor:
        instructor_id = course.get('instructor_id')
        if instructor_id:
            instructor_ids.add(instructor_id)
            instructor_course_map.setdefault(instructor_id, []).append({
                'id': str(course['_id']),
                'title': course['title']
            })

    # 3️⃣ Fetch instructor user docs
    instructors = users_collection.find({
        '_id': {'$in': list(instructor_ids)},
        'role': 'instructor'
    })

    instructors_list = []
    for instructor in instructors:
        instructors_list.append({
            'id': str(instructor['_id']),
            'username': instructor['username'],
            'courses': instructor_course_map.get(instructor['_id'], [])
        })

    context = {
        'instructors_list': instructors_list,
        'student_name': request.session.get('student_name', ''),
        'student_profile_pic': request.session.get('student_photo', 'users/default_profile.png'),
    }

    # 4️⃣ Handle POST (Send Message)
    if request.method == 'POST':
        recipient = request.POST.get('recipient')
        message_content = request.POST.get('message')

        if not (recipient and message_content.strip()):
            context['error'] = "Please fill in all fields."
            return render(request, 'messages_app/send_message.html', context)

        try:
            instructor_id, course_id = recipient.split('|')
        except ValueError:
            context['error'] = "Invalid recipient format."
            return render(request, 'messages_app/send_message.html', context)

        instructor_obj_id = ObjectId(instructor_id)
        course_obj_id = ObjectId(course_id)
        now = datetime.datetime.utcnow()

        new_message = {
            'sender_id': student_obj_id,
            'receiver_id': instructor_obj_id,
            'content': message_content.strip(),
            'sent_at': now
        }

        convo = messages_collection.find_one({
            'course_id': course_obj_id,
            'participants': {'$all': [student_obj_id, instructor_obj_id]}
        })

        if convo:
            messages_collection.update_one(
                {'_id': convo['_id']},
                {'$push': {'messages': new_message}}
            )
        else:
            messages_collection.insert_one({
                'course_id': course_obj_id,
                'participants': [student_obj_id, instructor_obj_id],
                'messages': [new_message]
            })

        return redirect('student_inbox')

    return render(request, 'messages_app/send_message.html', context)


@student_login_required
def student_conversation_detail(request, conversation_id):
    """
    Displays a specific conversation for the student and handles sending new messages.
    """
    try:
        conversation_obj_id = ObjectId(conversation_id)
    except:
        return redirect('student_login')

    student_id = request.session.get('student_id')
    try:
        student_obj_id = ObjectId(student_id)
    except:
        return redirect('student_login')

    # Find the conversation
    conversation = messages_collection.find_one({
        '_id': conversation_obj_id,
        'participants': student_obj_id
    })

    if not conversation:
        return redirect('student_inbox')

    # Get the other participant (instructor)
    other_participant_id = next(
        (p for p in conversation.get('participants', []) if p != student_obj_id), None
    )

    if not other_participant_id:
        return redirect('student_inbox')

    # Get instructor details
    instructor_doc = users_collection.find_one({'_id': other_participant_id})
    instructor_name = instructor_doc.get('username', 'Unknown Instructor') if instructor_doc else 'Unknown Instructor'

    # Get course details
    course_doc = courses_collection.find_one({'_id': conversation.get('course_id')})
    course_title = course_doc.get('title', 'Unknown Course') if course_doc else 'Unknown Course'

    # Handle POST (Send Message)
    if request.method == 'POST':
        message_content = request.POST.get('message_content')
        if message_content and message_content.strip():
            new_message = {
                'sender_id': student_obj_id,
                'receiver_id': other_participant_id,
                'content': message_content.strip(),
                'sent_at': datetime.datetime.utcnow()
            }

            # Update the conversation with the new message
            messages_collection.update_one(
                {'_id': conversation_obj_id},
                {'$push': {'messages': new_message}}
            )
            
            # Redirect to refresh the page
            return redirect('student_conversation_detail', conversation_id=conversation_id)

    # Get all messages for this conversation
    messages = conversation.get('messages', [])
    
    # Sort messages by sent_at
    messages.sort(key=lambda m: m.get('sent_at', datetime.datetime.min))

    context = {
        'conversation': {
            'id_str': conversation_id,
            'course_title': course_title
        },
        'messages': messages,
        'instructor_name': instructor_name,
        'student_id': str(student_obj_id),
        'student_name': request.session.get('student_name', ''),
        'student_profile_pic': request.session.get('student_photo', 'users/default_profile.png'),
    }

    return render(request, 'messages_app/student_conversation_detail.html', context)


# Instructor Part
# messages_app/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404
from pymongo import MongoClient

from bson.objectid import ObjectId, InvalidId
import datetime

# Assumed imports for decorators and session management
from users.views import manual_login_required, manual_instructor_required, load_session, save_session


def get_mongo_connection():
    """
    Helper function to get a MongoDB database object.
    Returns the database object or None on failure.
    """
    try:
        # First try to use the global connection if it's available
        if 'db' in globals() and db is not None:
            # Test if the global connection is still alive
            try:
                db.command('ping')
                return db
            except:
                pass  # Global connection is dead, create a new one
        
        # Create a new connection if global connection is not available
        client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
        db_new = client['Peer_to_Peer_Education']
        # Test the connection
        db_new.command('ping')
        return db_new
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        print(f"Error type: {type(e).__name__}")
        print(f"Error details: {str(e)}")
        if 'client' in locals():
            client.close()
        return None


def get_instructor_data_for_sidebar(db, instructor_id):
    """
    Helper function to fetch instructor's profile data for the sidebar.
    """
    if db is None:
        return {}

    try:
        users_collection = db['users']
        instructor_doc = users_collection.find_one(
            {"_id": ObjectId(instructor_id)},
            {"username": 1, "email": 1, "profile_photo": 1}
        )
        return {
            'instructor_photo': instructor_doc.get('profile_photo', 'default_profile.jpg'),
            'instructor_name': instructor_doc.get('username', 'Instructor'),
            'instructor_email': instructor_doc.get('email', 'N/A'),
        } if instructor_doc else {}
    except (InvalidId, Exception) as e:
        print(f"Error fetching instructor data: {e}")
        return {}


@manual_login_required
@manual_instructor_required
def instructor_conversations_list(request):
    """
    Displays a list of all conversations for the instructor.
    """
    db = get_mongo_connection()
    if db is None:
        return HttpResponse("""
            <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                <h2 style="color: #e74c3c;">⚠️ Database Connection Error</h2>
                <p style="color: #7f8c8d; margin: 20px 0;">Unable to connect to the database. Please try the following:</p>
                <ul style="text-align: left; max-width: 400px; margin: 0 auto; color: #7f8c8d;">
                    <li>Check if MongoDB service is running</li>
                    <li>Verify database connection settings</li>
                    <li>Contact system administrator</li>
                </ul>
                <p style="margin-top: 30px;">
                    <a href="{% url 'instructor_dashboard' %}" style="background: #3498db; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">← Back to Dashboard</a>
                </p>
            </div>
        """, status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id
        instructor_id = request.session_data.get('user_id')
        if not instructor_id:
            return redirect('instructor_login')

        instructor_object_id = ObjectId(instructor_id)

        messages_collection = db['messages']
        users_collection = db['users']
        courses_collection = db['courses']

        context = get_instructor_data_for_sidebar(db, instructor_id)
        if not context:
            return redirect('instructor_login')

        # Find all conversations where the instructor is a participant
        conversations_cursor = messages_collection.find(
            {"participants": instructor_object_id}
        )

        conversations = []
        for conv in conversations_cursor:
            # Manually find the other participant's ID
            other_participant_id = next(
                (p for p in conv.get('participants', []) if p != instructor_object_id), None
            )

            if other_participant_id:
                # Find the user details for the other participant
                other_user = users_collection.find_one({"_id": other_participant_id})

                # --- NEW VALIDATION: Check if the student is active ---
                if other_user and not other_user.get('is_active', True):
                    # Skip this conversation if the student is banned/inactive
                    continue
                # --- END NEW VALIDATION ---

                conv['other_participant_name'] = other_user.get('username',
                                                                'Unknown User') if other_user else 'Unknown User'
            else:
                conv['other_participant_name'] = 'Unknown User'

            # Find the course details
            if 'course_id' in conv:
                course = courses_collection.find_one({"_id": conv['course_id']})
                conv['course_title'] = course.get('title', 'Unknown Course') if course else 'Unknown Course'

            # Get the last message details if available
            if conv.get('messages'):
                last_message = conv['messages'][-1]
                conv['last_message'] = last_message.get('content', '')
                conv['last_message_date'] = last_message.get('sent_at')

            # Convert ObjectId to string for the template
            conv['id_str'] = str(conv['_id'])

            conversations.append(conv)

        context['conversations'] = conversations

        response = render(request, 'messages_app/instructor_conversations_list.html', context)
        save_session(response, session_id, session_data)
        return response
    except InvalidId:
        return HttpResponse("Invalid user ID format. Please log in again.", status=400)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return HttpResponse(f"An unexpected error occurred: {e}", status=500)


@manual_login_required
@manual_instructor_required
def instructor_new_conversation(request):
    """
    Renders a form to start a new conversation and handles POST to create it.
    """
    db = get_mongo_connection()
    if db is None:
        return HttpResponse("""
            <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                <h2 style="color: #e74c3c;">⚠️ Database Connection Error</h2>
                <p style="color: #7f8c8d; margin: 20px 0;">Unable to connect to the database. Please try the following:</p>
                <ul style="text-align: left; max-width: 400px; margin: 0 auto; color: #7f8c8d;">
                    <li>Check if MongoDB service is running</li>
                    <li>Verify database connection settings</li>
                    <li>Contact system administrator</li>
                </ul>
                <p style="margin-top: 30px;">
                    <a href="{% url 'instructor_dashboard' %}" style="background: #3498db; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">← Back to Dashboard</a>
                </p>
            </div>
        """, status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id
        instructor_id = request.session_data.get('user_id')
        if not instructor_id:
            return redirect('instructor_login')

        instructor_object_id = ObjectId(instructor_id)

        courses_collection = db['courses']
        enrollments_collection = db['enrollments']
        users_collection = db['users']
        messages_collection = db['messages']

        context = get_instructor_data_for_sidebar(db, instructor_id)
        if not context:
            return redirect('instructor_login')

        if request.method == 'POST':
            student_id = request.POST.get('student_id')
            course_id = request.POST.get('course_id')

            if not student_id or not course_id:
                return HttpResponse("Student ID and Course ID are required.", status=400)

            try:
                student_obj_id = ObjectId(student_id)
                course_obj_id = ObjectId(course_id)
            except InvalidId:
                return HttpResponse("Invalid ID format.", status=400)

            # --- NEW VALIDATION: Check if the student is active ---
            student_doc = users_collection.find_one({"_id": student_obj_id})
            if student_doc is None or not student_doc.get('is_active', True):
                return HttpResponse("Cannot start a conversation with a banned or non-existent student.", status=403)

            # --- NEW VALIDATION: Check if student is enrolled in the course ---
            is_enrolled = enrollments_collection.find_one({
                "student_id": student_obj_id,
                "course_id": course_obj_id
            })
            if not is_enrolled:
                return HttpResponse("The selected student is not enrolled in this course.", status=403)
            # --- END NEW VALIDATION ---

            existing_conversation = messages_collection.find_one({
                "participants": {"$all": [instructor_object_id, student_obj_id]},
                "course_id": course_obj_id
            })

            if existing_conversation:
                response = redirect('instructor_conversation_detail', pk=str(existing_conversation['_id']))
                save_session(response, session_id, session_data)
                return response

            new_conversation = {
                "course_id": course_obj_id,
                "participants": [instructor_object_id, student_obj_id],
                "messages": []
            }
            result = messages_collection.insert_one(new_conversation)

            response = redirect('instructor_conversation_detail', pk=str(result.inserted_id))
            save_session(response, session_id, session_data)
            return response

        instructor_courses = list(courses_collection.find(
            {"instructor_id": instructor_object_id},
            {"_id": 1, "title": 1}
        ))

        instructor_course_ids = [course['_id'] for course in instructor_courses]
        enrolled_students_ids_cursor = enrollments_collection.find(
            {"course_id": {"$in": instructor_course_ids}},
            {"student_id": 1}
        )
        unique_student_ids = list(set([e['student_id'] for e in enrolled_students_ids_cursor]))

        students_for_dropdown = []
        for student_id in unique_student_ids:
            student_doc = users_collection.find_one({"_id": student_id}, {"username": 1, "is_active": 1})
            if student_doc and student_doc.get('is_active', True):
                students_for_dropdown.append({
                    'id_str': str(student_doc['_id']),
                    'username': student_doc['username']
                })

        context['students'] = students_for_dropdown
        context['courses'] = [{'id_str': str(c['_id']), 'title': c['title']} for c in instructor_courses]

        response = render(request, 'messages_app/instructor_new_conversation.html', context)
        save_session(response, session_id, session_data)
        return response
    except InvalidId:
        return HttpResponse("Invalid user ID format. Please log in again.", status=400)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return HttpResponse(f"An unexpected error occurred: {e}", status=500)


@manual_login_required
@manual_instructor_required
def instructor_conversation_detail(request, pk):
    """
    Displays a specific conversation and handles sending new messages.
    """
    db = get_mongo_connection()
    if db is None:
        return HttpResponse("""
            <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                <h2 style="color: #e74c3c;">⚠️ Database Connection Error</h2>
                <p style="color: #7f8c8d; margin: 20px 0;">Unable to connect to the database. Please try the following:</p>
                <ul style="text-align: left; max-width: 400px; margin: 0 auto; color: #7f8c8d;">
                    <li>Check if MongoDB service is running</li>
                    <li>Verify database connection settings</li>
                    <li>Contact system administrator</li>
                </ul>
                <p style="margin-top: 30px;">
                    <a href="{% url 'instructor_dashboard' %}" style="background: #3498db; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">← Back to Dashboard</a>
                </p>
            </div>
        """, status=500)

    try:
        session_id, session_data = load_session(request)
        request.session_data = session_data
        request.session_id = session_id
        instructor_id = request.session_data.get('user_id')
        if not instructor_id:
            return redirect('instructor_login')

        instructor_object_id = ObjectId(instructor_id)

        messages_collection = db['messages']
        users_collection = db['users']
        courses_collection = db['courses']

        try:
            conversation_obj_id = ObjectId(pk)
        except InvalidId:
            raise Http404("Invalid Conversation ID format.")

        context = get_instructor_data_for_sidebar(db, instructor_id)
        if not context:
            return redirect('instructor_login')

        # Fetch the conversation document
        conversation = messages_collection.find_one({
            "_id": conversation_obj_id,
            "participants": instructor_object_id
        })

        if conversation is None:
            raise Http404("Conversation not found or you are not a participant.")

        # --- NEW VALIDATION: Check if the other participant is active ---
        other_participant_id = next(
            (p for p in conversation.get('participants', []) if p != instructor_object_id), None
        )
        if other_participant_id:
            other_user = users_collection.find_one({'_id': other_participant_id}, {'is_active': 1})
            if other_user and not other_user.get('is_active', True):
                # If the other participant is not active, prevent messages and show a different page.
                return HttpResponse("This conversation is with a banned student and is now read-only.", status=403)
        # --- END NEW VALIDATION ---

        if request.method == 'POST':
            message_content = request.POST.get('message_content')
            if message_content:
                if other_participant_id is None:
                    return HttpResponse("Could not find a valid recipient for the message.", status=400)

                new_message = {
                    "sender_id": instructor_object_id,
                    "receiver_id": other_participant_id,
                    "content": message_content,
                    "sent_at": datetime.datetime.utcnow()
                }

                # Update the conversation with the new message
                messages_collection.update_one(
                    {"_id": conversation_obj_id},
                    {"$push": {"messages": new_message}}
                )
                response = redirect('instructor_conversation_detail', pk=pk)
                save_session(response, session_id, session_data)
                return response

        # Fetch participant names for the conversation detail page
        participant_ids = conversation.get('participants', [])
        participant_names = {}
        other_participant_id = None
        for participant_id in participant_ids:
            if participant_id != instructor_object_id:
                other_participant_id = participant_id
            user = users_collection.find_one({"_id": participant_id}, {"username": 1})
            if user:
                participant_names[str(participant_id)] = user.get('username', 'Unknown User')

        # Get course title
        course = courses_collection.find_one(
            {'_id': conversation['course_id']}) if 'course_id' in conversation else None

        # Check if other participant is active
        other_user_is_active = False
        if other_participant_id:
            other_user = users_collection.find_one({'_id': other_participant_id}, {'is_active': 1})
            other_user_is_active = other_user.get('is_active', True) if other_user else False

        context['conversation'] = {
            'id_str': str(conversation['_id']),
            'course_title': course.get('title', 'Unknown Course') if course else 'Unknown Course'
        }
        context['messages'] = conversation.get('messages', [])
        context['participant_names'] = participant_names
        context['instructor_id'] = str(instructor_object_id)
        context['is_student_active'] = other_user_is_active

        response = render(request, 'messages_app/instructor_conversation_detail.html', context)
        save_session(response, session_id, session_data)
        return response
    except InvalidId:
        return HttpResponse("Invalid ID format.", status=400)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return HttpResponse(f"An unexpected error occurred: {e}", status=500)


def health_check(request):
    """
    Simple health check endpoint to test database connectivity
    """
    try:
        db = get_mongo_connection()
        if db is None:
            return HttpResponse("""
                <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                    <h2 style="color: #e74c3c;">❌ Database Connection Failed</h2>
                    <p style="color: #7f8c8d;">MongoDB is not accessible</p>
                    <p style="color: #7f8c8d; font-size: 0.9em;">Check if MongoDB service is running on localhost:27017</p>
                </div>
            """, status=500)
        
        # Test basic operations
        db.command('ping')
        
        # Test collections
        users_count = db['users'].count_documents({})
        courses_count = db['courses'].count_documents({})
        messages_count = db['messages'].count_documents({})
        
        return HttpResponse(f"""
            <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                <h2 style="color: #27ae60;">✅ Database Connection Successful</h2>
                <p style="color: #7f8c8d;">MongoDB is running and accessible</p>
                <div style="background: #f8f9fa; padding: 20px; border-radius: 10px; margin: 20px auto; max-width: 400px;">
                    <p><strong>Users:</strong> {users_count}</p>
                    <p><strong>Courses:</strong> {courses_count}</p>
                    <p><strong>Messages:</strong> {messages_count}</p>
                </div>
            </div>
        """)
        
    except Exception as e:
        return HttpResponse(f"""
            <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                <h2 style="color: #e74c3c;">❌ Database Error</h2>
                <p style="color: #7f8c8d;">Error: {str(e)}</p>
                <p style="color: #7f8c8d; font-size: 0.9em;">Type: {type(e).__name__}</p>
            </div>
        """, status=500)


@student_login_required
def clear_student_conversation(request, conversation_id):
    """
    Clear all messages in a conversation for a student
    """
    if request.method != 'POST':
        return redirect('student_inbox')
    
    student_id = request.session.get('student_id')
    try:
        student_obj_id = ObjectId(student_id)
        conversation_obj_id = ObjectId(conversation_id)
    except:
        return redirect('student_inbox')
    
    # Find the conversation and verify the student is a participant
    conversation = messages_collection.find_one({
        '_id': conversation_obj_id,
        'participants': student_obj_id
    })
    
    if not conversation:
        return redirect('student_inbox')
    
    # Clear all messages in the conversation
    messages_collection.update_one(
        {'_id': conversation_obj_id},
        {'$set': {'messages': []}}
    )
    
    return redirect('student_inbox')


@manual_login_required
@manual_instructor_required
def clear_instructor_conversation(request, pk):
    """
    Clear all messages in a conversation for an instructor
    """
    if request.method != 'POST':
        return redirect('instructor_conversations_list')
    
    db = get_mongo_connection()
    if db is None:
        return redirect('instructor_conversations_list')
    
    try:
        session_id, session_data = load_session(request)
        instructor_id = session_data.get('user_id')
        if not instructor_id:
            return redirect('instructor_login')
        
        instructor_obj_id = ObjectId(instructor_id)
        conversation_obj_id = ObjectId(pk)
        
        messages_collection = db['messages']
        
        # Find the conversation and verify the instructor is a participant
        conversation = messages_collection.find_one({
            '_id': conversation_obj_id,
            'participants': instructor_obj_id
        })
        
        if not conversation:
            return redirect('instructor_conversations_list')
        
        # Clear all messages in the conversation
        messages_collection.update_one(
            {'_id': conversation_obj_id},
            {'$set': {'messages': []}}
        )
        
        response = redirect('instructor_conversations_list')
        save_session(response, session_id, session_data)
        return response
        
    except Exception as e:
        print(f"Error clearing instructor conversation: {e}")
        return redirect('instructor_conversations_list')
