from django import forms
import pymongo
from bson.objectid import ObjectId
import datetime
import os
from django.conf import settings  # Import settings to get MEDIA_ROOT

# Assuming get_db is available from users.views as per previous conversation
from users.views import get_db


class CourseForm(forms.Form):
    title = forms.CharField(max_length=255, required=True)
    description = forms.CharField(widget=forms.Textarea, required=True)
    price = forms.DecimalField(max_digits=10, decimal_places=2, required=True, min_value=0)
    category = forms.CharField(max_length=100, required=True)
    course_photo = forms.ImageField(required=False, help_text="Upload a cover photo for your course.")
    file = forms.FileField(required=False, help_text="Upload the main course material (e.g., ZIP, PDF).")

    def __init__(self, *args, **kwargs):
        self.instructor_id = kwargs.pop('instructor_id', None)
        self.instance_id = kwargs.pop('instance_id', None)  # For update scenarios
        super().__init__(*args, **kwargs)

    def clean_title(self):
        title = self.cleaned_data['title']
        conn = None
        try:
            db, conn = get_db()
            courses_collection = db['courses']

            query = {"title": title, "instructor_id": ObjectId(self.instructor_id)}
            if self.instance_id:  # Exclude current instance if updating
                query["_id"] = {"$ne": ObjectId(self.instance_id)}

            if courses_collection.find_one(query):
                raise forms.ValidationError("You already have a course with this title.")
        except Exception as e:
            # Re-raise ValidationError or add a non-field error
            raise forms.ValidationError(f"Database error during title validation: {e}")
        finally:
            if conn:
                conn.close()
        return title

    def save(self, courses_collection, instructor_id, course_photo_path=None, file_path=None):
        course_doc = {
            "title": self.cleaned_data['title'],
            "description": self.cleaned_data['description'],
            "price": float(self.cleaned_data['price']),  # Store as float for MongoDB
            "category": self.cleaned_data['category'],
            "course_photo": course_photo_path if course_photo_path else 'courses/default_course.jpg',
            "file": file_path if file_path else None,  # Can be None if no file uploaded
            "instructor_id": ObjectId(instructor_id),
            "created_at": datetime.datetime.utcnow(),
            "updated_at": datetime.datetime.utcnow(),
            "status": "pending",  # Set default status to pending for admin approval
        }

        if self.instance_id:
            # Update existing course
            courses_collection.update_one(
                {"_id": ObjectId(self.instance_id)},
                {"$set": course_doc}
            )
            return self.instance_id
        else:
            # Insert new course
            result = courses_collection.insert_one(course_doc)
            return str(result.inserted_id)
