from decimal import Decimal
import enum
from flask_login import UserMixin
from datetime import datetime, timedelta
from app import now_eat



# 1. Qeexidda Enum-ka
# 1. Enum-ka Doorka (Role Definition)
class UserRole(enum.Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    TEACHER = "teacher"
    USER = "user"



class User(UserMixin):
    def __init__(self, data):
        self.data = data or {}

        self.id = str(self.data.get("_id"))
        self.username = self.data.get("username")
        self.fullname = self.data.get("fullname")
        self.email = self.data.get("email")
        self.password = self.data.get("password")

        # Role system (Mongo style)
        self.role = self.data.get("role", "user")
        self.role_id = self.data.get("role_id")  # ObjectId string if using reference

        # Basic info
        self.phone = self.data.get("phone")
        self.country = self.data.get("country")
        self.city = self.data.get("city")
        self.state = self.data.get("state")
        self.address = self.data.get("address")
        self.bio = self.data.get("bio")
        self.photo = self.data.get("photo")
        self.gender = self.data.get("gender")
        self.photo_visibility = self.data.get("photo_visibility", "everyone")

        self.status = self.data.get("status", True)

        # Device info
        self.device = self.data.get("device")
        self.browser = self.data.get("browser")
        self.platform = self.data.get("platform")
        self.device_name = self.data.get("device_name")
        self.interface_name = self.data.get("interface_name")

        # Security
        self.is_verified = self.data.get("is_verified", False)
        self.auth_status = self.data.get("auth_status", "logout")
        self.session_token = self.data.get("session_token")
        self.login_time = self.data.get("login_time")
        self.last_seen = self.data.get("last_seen")

        self.phone_verified = self.data.get("phone_verified", False)
        self.two_factor_enabled = self.data.get("two_factor_enabled", False)
        self.two_factor_code = self.data.get("two_factor_code")
        self.two_factor_expires_at = self.data.get("two_factor_expires_at")

        self.last_login_ip = self.data.get("last_login_ip")
        self.remember_token = self.data.get("remember_token")
        self.failed_login_attempts = self.data.get("failed_login_attempts", 0)

        self.auth_provider = self.data.get("auth_provider", "local")
        self.last_active = self.data.get("last_active")

        # Socials
        self.facebook = self.data.get("facebook")
        self.twitter = self.data.get("twitter")
        self.google = self.data.get("google")
        self.whatsapp = self.data.get("whatsapp")
        self.instagram = self.data.get("instagram")
        self.github = self.data.get("github")
        self.github_id = self.data.get("github_id")

        # Timestamps
        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")

        # Embedded relationships (Mongo style)
        self.user_logs = self.data.get("user_logs", [])
        self.sessions = self.data.get("sessions", [])
        self.user_permissions = self.data.get("user_permissions", [])

        # Muhiim: Haddii uu yahay macallin, halkan waxaa ku jiraya ID-ga uu ku leeyahay Teacher collection-ka
        self.teacher_id = str(self.data.get("teacher_id")) if self.data.get("teacher_id") else None
        
        self.status = self.data.get("status", True)
        self.created_at = self.data.get("created_at")


    # Flask-Login required
    def get_id(self):
        return self.id

    @property
    def is_active(self):
        return self.status is True

    @property
    def permissions(self):
        return [p.get("permission") for p in self.user_permissions]

    def to_dict(self):
        return self.data

    def __repr__(self):
        return f"<User {self.username}>"


class Teacher:
    def __init__(self, data):
        self.data = data or {}

        self.id = str(self.data.get("_id"))

        # Unique teacher code
        self.teacher_role_id = self.data.get("teacher_role_id")  # e.g TCH-2026-001

        # Basic info
        self.full_name = self.data.get("full_name")

        # Timestamps
        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")



class TeacherAssignment:
    def __init__(self, data):
        self.data = data or {}

        self.id = str(self.data.get("_id"))
        self.teacher_id = str(self.data.get("teacher_id"))
        self.class_id = str(self.data.get("class_id"))
        self.section_id = str(self.data.get("section_id"))
        self.subject_id = str(self.data.get("subject_id"))

        # 🔥 NEW: DEADLINE RANGE
        self.start_time = self.data.get("start_time")  # FROM
        self.end_time = self.data.get("end_time")      # TO

        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")


        
class Student:
    def __init__(self, data):
        self.data = data or {}
        self.id = str(self.data.get("_id"))

        # Student info
        self.role_no = self.data.get("role_no")
        self.full_name = self.data.get("full_name")

        # Relationships
        self.class_id = str(self.data.get("class_id"))
        self.section_id = str(self.data.get("section_id"))

        # 🔥 AUTO SHIFT FROM CLASSROOM
        self.shift_name = self.data.get("shift_name")

        self.status = self.data.get("status", True)

        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")
        

class ClassRoom:
    def __init__(self, data):
        self.data = data or {}
        self.id = str(self.data.get("_id"))
        self.class_name = self.data.get("class_name") # Tusaale: 12-A
        # Shift name: Morning, Afternoon, Evening
        self.shift_name = self.data.get("shift_name")

        # Optional description
        self.description = self.data.get("description")
        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")

class Section:
    def __init__(self, data):
        self.data = data or {}
        self.id = str(self.data.get("_id"))
        self.section_name = self.data.get("section_name") # Tusaale: "A" ama "Subax"
        self.class_id = str(self.data.get("class_id"))    # Waxay ku xiran tahay fasalka
        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")

class Subject:
    def __init__(self, data):
        self.data = data or {}
        self.id = str(self.data.get("_id"))
        self.subject_name = self.data.get("subject_name") # Tusaale: Xisaab
        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")

class StudentStatistics:
    def __init__(self, data):
        self.data = data or {}

        self.id = str(self.data.get("_id"))

        self.student_id = str(self.data.get("student_id"))

        self.total_score = self.data.get("total_score", 0)
        self.average = self.data.get("average", 0)
        self.grade = self.data.get("grade")

        self.class_position = self.data.get("class_position")
        self.total_class_students = self.data.get("total_class_students")

        self.school_position = self.data.get("school_position")
        self.total_school_students = self.data.get("total_school_students")

        # haddii score la beddelo waxaad ka dhigi kartaa True
        self.need_recalculate = self.data.get("need_recalculate", False)

        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")

        

class Result:
    def __init__(self, data):
        self.data = data or {}
        self.id = str(self.data.get("_id"))
        self.student_id = self.data.get("student_id")
        self.subject_id = self.data.get("subject_id")
        self.teacher_id = self.data.get("teacher_id") # Si macalinka loo shaandheeyo
        self.score = self.data.get("score", 0)
        self.exam_date = self.data.get("exam_date")
        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")

        



class ResultImportBatch:
    def __init__(self, data):
        self.data = data or {}

        self.id = str(self.data.get("_id"))

        # Academic Info
        self.academic_year = self.data.get("academic_year")
        self.exam_type = self.data.get("exam_type")      # Mid, Final
        self.class_id = str(self.data.get("class_id"))
        self.section_id = str(self.data.get("section_id"))

        # Excel Info
        self.file_name = self.data.get("file_name")
        self.sheet_name = self.data.get("sheet_name")

        # Subject headers extracted from Excel
        self.subjects = self.data.get("subjects", [])

        # Imported students
        self.students = self.data.get("students", [])

        # Import Status
        self.status = self.data.get("status", "Pending")
        self.imported_by = self.data.get("imported_by")

        self.created_at = self.data.get("created_at")
        self.updated_at = self.data.get("updated_at")


class Session:
    def __init__(self, data):
        self.data = data or {}

        self.id = str(self.data.get("_id"))
        self.user_id = str(self.data.get("user_id"))

        self.session_token = self.data.get("session_token")
        self.ip = self.data.get("ip")
        self.device = self.data.get("device")

        self.created_at = self.data.get("created_at", datetime.utcnow())
        self.expires_at = self.data.get(
            "expires_at",
            datetime.utcnow() + timedelta(days=7)
        )

    def is_expired(self):
        return datetime.utcnow() > self.expires_at

    def is_active(self):
        return not self.is_expired()

    def to_dict(self):
        return {
            "_id": self.id,
            "user_id": self.user_id,
            "session_token": self.session_token,
            "ip": self.ip,
            "device": self.device,
            "created_at": self.created_at,
            "expires_at": self.expires_at
        }

    def __repr__(self):
        return f"<Session {self.session_token}>"


