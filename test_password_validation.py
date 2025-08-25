#!/usr/bin/env python3
"""
Test script for password validation functionality
"""

import sys
import os

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the validation function
from users.forms import validate_password_strength

def test_password_validation():
    """Test the password validation function with various scenarios"""
    
    print("🔐 Testing Password Validation System")
    print("=" * 50)
    
    test_cases = [
        # Valid passwords
        ("StrongPass123!", "testuser", "test@example.com", True, "Valid strong password"),
        ("MySecure2024@", "user123", "user@test.com", True, "Valid password with special chars"),
        ("Complex#Pass9", "different", "email@domain.com", True, "Valid complex password"),
        
        # Invalid passwords - too short
        ("Short1!", "user", "email@test.com", False, "Too short (< 8 characters)"),
        
        # Invalid passwords - missing requirements
        ("lowercase123!", "user", "email@test.com", False, "No uppercase letter"),
        ("UPPERCASE123!", "user", "email@test.com", False, "No lowercase letter"),
        ("NoNumbers!", "user", "email@test.com", False, "No numbers"),
        ("NoSpecial123", "user", "email@test.com", False, "No special characters"),
        
        # Invalid passwords - matches username/email
        ("testuser", "testuser", "test@example.com", False, "Matches username"),
        ("test@example.com", "user123", "test@example.com", False, "Matches email"),
        ("test", "different", "test@example.com", False, "Matches email local part"),
        
        # Invalid passwords - common passwords
        ("Password123", "user", "email@test.com", False, "Common password"),
        ("password123", "user", "email@test.com", False, "Common password (lowercase)"),
        
        # Invalid passwords - consecutive characters
        ("MyPasss123!", "user", "email@test.com", False, "Consecutive identical characters"),
        
        # Invalid passwords - sequential characters
        ("MyPass123456!", "user", "email@test.com", False, "Sequential numbers"),
        ("MyPassabcdef!", "user", "email@test.com", False, "Sequential letters"),
    ]
    
    passed = 0
    failed = 0
    
    for password, username, email, expected_valid, description in test_cases:
        is_valid, message = validate_password_strength(password, username, email)
        
        if is_valid == expected_valid:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1
        
        print(f"{status} | {description}")
        print(f"      Password: '{password}'")
        print(f"      Expected: {'Valid' if expected_valid else 'Invalid'}")
        print(f"      Got: {'Valid' if is_valid else 'Invalid'}")
        if not is_valid:
            print(f"      Message: {message}")
        print()
    
    print("=" * 50)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! Password validation is working correctly.")
        return True
    else:
        print("⚠️  Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = test_password_validation()
    sys.exit(0 if success else 1)