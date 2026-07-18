from collections import defaultdict
import csv
import datetime
import io
import math
import os
from pyclbr import Class
import random
import secrets
import traceback
import uuid
import re

from bson import ObjectId
from flask import Blueprint, Response, abort, current_app, flash, make_response, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from openpyxl import Workbook
import pytz
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from app import ALLOWED_EXTENSIONS
from app.extensions import mongo
from datetime import datetime
from datetime import timedelta
from app.modal import ClassRoom, Subject, User, UserRole


bp = Blueprint('main', __name__)

#------------------------------------------
#---- Function: 1 | Func Allowed Files  ---
#------------------------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
 
def create_guest_session(mongo):
    if not session.get("guest_token"):

        token = secrets.token_hex(24)

        session["guest_token"] = token

        mongo.db.sessions.insert_one({
            "session_token": token,
            "user_id": None,   # guest
            "ip": request.remote_addr,
            "device": request.user_agent.string,
            "created_at": datetime.utcnow(),
            "expires_at": None,
            "routes": []   # store visited pages
        })



# 1. Index route: Wuxuu soo bandhigayaa page-ka iyo data-da projects-ka
#=====================================================
#--------------- Forntend Section
#-======================================


@bp.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':

        teacher_role_id = request.form.get('teacher_role_id', '').strip()

        teacher = mongo.db.teachers.find_one({
            "teacher_role_id": teacher_role_id
        })

        if not teacher:
            flash("Teacher ID lama helin!", "danger")
            return redirect(url_for('main.index'))

        assignment = mongo.db.teacher_assignments.find_one({
            "teacher_id": teacher["_id"]
        })

        if not assignment:
            flash("Teacher assignment lama helin!", "warning")
            return redirect(url_for('main.index'))

        start_time = assignment.get("start_time")
        end_time = assignment.get("end_time")

        # Deadline lama dejin
        if not start_time or not end_time:
            flash("⚠️ Exam-ka wali lama diyaarin!", "warning")
            return redirect(url_for('main.index'))

        # Somalia Time (UTC+3)
        now = datetime.utcnow() + timedelta(hours=3)

        # Wali ma bilaaban
        if now < start_time:

            diff = start_time - now

            days = diff.days
            hours = diff.seconds // 3600
            minutes = (diff.seconds % 3600) // 60
            seconds = diff.seconds % 60

            flash(
                f"⏳ Exam-ku wali ma bilaaban. Waxa harsan: "
                f"{days}d : {hours}h : {minutes}m : {seconds}s",
                "warning"
            )

            return redirect(url_for('main.index'))

        # Deadline dhacay
        if now > end_time:

            flash(
                f"⛔ Waqtiga gelinta natiijada wuu dhammaaday! Deadline-ku wuxuu ku ekaa {end_time}",
                "danger"
            )

            return redirect(url_for('main.index'))

        # Gudaha u gal
        return redirect(
            url_for(
                'main.teacher_dashboard',
                teacher_id=str(teacher["_id"])
            )
        )

    return render_template("frontend/home/index.html")




@bp.route('/teacher-dashboard/<teacher_id>')
def teacher_dashboard(teacher_id):

    # =========================
    # CHECK DEADLINE FIRST
    # =========================
    deadline_assignment = mongo.db.teacher_assignments.find_one({
    "teacher_id": ObjectId(teacher_id),
    "end_time": {"$ne": None}
    })

    if deadline_assignment:
        end_time = deadline_assignment.get("end_time")

        if end_time:

            now = datetime.utcnow() + timedelta(hours=3)

            if now >= end_time:

                flash(
                    "⛔ Waqtiga gelinta natiijada wuu dhammaaday.",
                    "danger"
                )

                return redirect(url_for("main.index"))



    # =========================
    # TEACHER
    # =========================
    teacher = mongo.db.teachers.find_one({
        "_id": ObjectId(teacher_id)
    })

    if not teacher:
        return abort(404)

    # =========================
    # ASSIGNMENTS
    # =========================
    assignments_db = list(
        mongo.db.teacher_assignments.find({
            "teacher_id": ObjectId(teacher_id)
        })
    )

    assignments = []

    class_ids = set()
    subject_ids = set()

    total_students = 0

    # =========================
    # CLASS STATS
    # =========================
    class_stats_map = {}

    for a in assignments_db:

        # SAFE OBJECT IDS
        class_id = a.get("class_id")
        subject_id = a.get("subject_id")
        section_id = a.get("section_id")

        class_doc = mongo.db.classrooms.find_one({"_id": class_id})
        subject_doc = mongo.db.subjects.find_one({"_id": subject_id})

        section_doc = None
        if section_id:
            section_doc = mongo.db.sections.find_one({"_id": section_id})

        # =========================
        # STUDENT COUNT
        # =========================
        student_query = {"class_id": class_id}

        if section_id:
            student_query["section_id"] = section_id

        count_students = mongo.db.students.count_documents(student_query)
        total_students += count_students

        # =========================
        # CLASS NAME
        # =========================
        class_name = class_doc.get("class_name") if class_doc else "N/A"

        # =========================
        # CLASS STATS MAP (FIXED)
        # =========================
        if class_name not in class_stats_map:
            class_stats_map[class_name] = {
                "students": 0,
                "sections": set(),
                "subjects": set()
            }

        class_stats_map[class_name]["students"] += count_students

        if section_doc:
            class_stats_map[class_name]["sections"].add(
                section_doc.get("section_name", "N/A")
            )

        if subject_doc:
            class_stats_map[class_name]["subjects"].add(
                subject_doc.get("subject_name", "N/A")
            )

        # =========================
        # TRACK GLOBALS
        # =========================
        if class_id:
            class_ids.add(str(class_id))

        if subject_id:
            subject_ids.add(str(subject_id))

        # =========================
        # DEADLINE (IMPORTANT ADDITION)
        # =========================
        start_time = a.get("start_time")
        end_time = a.get("end_time")

        # =========================
        # BUILD ASSIGNMENT
        # =========================
        assignments.append({
            "assignment_id": str(a["_id"]),
            "class_name": class_name,
            "section_name": section_doc.get("section_name") if section_doc else "No Section",
            "subject_name": subject_doc.get("subject_name") if subject_doc else "N/A",
            "student_count": count_students,

    
        })

        # GET GLOBAL DEADLINE (from first assignment that has it)
        deadline_assignment = mongo.db.teacher_assignments.find_one({
            "teacher_id": ObjectId(teacher_id),
            "start_time": {"$ne": None},
            "end_time": {"$ne": None}
        })

        start_time = deadline_assignment.get("start_time") if deadline_assignment else None
        end_time = deadline_assignment.get("end_time") if deadline_assignment else None


    return render_template(
        "frontend/pages/teacher/dashboard.html",
        teacher={
            "id": str(teacher["_id"]),
            "full_name": teacher.get("full_name"),
            "teacher_role_id": teacher.get("teacher_role_id")
        },
        assignments=assignments,
        total_classes=len(class_ids),
        total_subjects=len(subject_ids),
        total_students=total_students,
        class_stats=class_stats_map,
         start_time=start_time,
        end_time=end_time
    )



@bp.route('/class-students/<assignment_id>', methods=['GET'])
def class_students(assignment_id):

    # =========================
    # ASSIGNMENT
    # =========================
    try:
        assignment = mongo.db.teacher_assignments.find_one({
            "_id": ObjectId(assignment_id)
        })
    except:
        return abort(404)

    if not assignment:
        return abort(404)

    # =========================
    # CHECK DEADLINE FIRST
    # =========================
    teacher_id = assignment["teacher_id"]

    deadline_assignment = mongo.db.teacher_assignments.find_one({
    "teacher_id": teacher_id,
    "end_time": {"$ne": None}
    })

    if deadline_assignment:

        end_time = deadline_assignment.get("end_time")

        if end_time:

            now = datetime.utcnow() + timedelta(hours=3)

            if now >= end_time:

                flash(
                    "⛔ Waqtiga gelinta natiijada wuu dhammaaday.",
                    "danger"
                )

                return redirect(url_for("main.index"))


    # =========================
    # STUDENTS
    # =========================
    query = {
        "class_id": assignment["class_id"]
    }

    if assignment.get("section_id"):
        query["section_id"] = assignment["section_id"]

    students = list(mongo.db.students.find(query))

    # convert ids for frontend safety
    for s in students:
        s["id_str"] = str(s["_id"])

    # =========================
    # SUBJECT
    # =========================
    subject = mongo.db.subjects.find_one({
        "_id": assignment["subject_id"]
    })

    subject_name = subject.get("subject_name") if subject else "N/A"

    # =========================
    # TEACHER
    # =========================
    teacher = mongo.db.teachers.find_one({
        "_id": assignment["teacher_id"]
    })


    # =========================
    # RESULTS (🔥 FIXED PROPERLY)
    # =========================
     # subject + teacher
    subject = mongo.db.subjects.find_one({"_id": assignment["subject_id"]})
    teacher = mongo.db.teachers.find_one({"_id": assignment["teacher_id"]})

    # 🔥 LOAD EXISTING RESULTS (IMPORTANT FIX)
    results = mongo.db.results.find({
        "teacher_id": assignment["teacher_id"],
        "subject_id": assignment["subject_id"]
    })


    # GET GLOBAL DEADLINE (from first assignment that has it)
    deadline_assignment = mongo.db.teacher_assignments.find_one({
        "teacher_id": ObjectId(teacher_id),
        "start_time": {"$ne": None},
        "end_time": {"$ne": None}
    })

    start_time = deadline_assignment.get("start_time") if deadline_assignment else None
    end_time = deadline_assignment.get("end_time") if deadline_assignment else None

    # convert to map for fast lookup
    result_map = {}
    for r in results:
        result_map[str(r["student_id"])] = r["score"]

    return render_template(
        "frontend/pages/teacher/class_students.html",
        students=students,
        subject_name=subject_name,
        assignment=assignment,
        subject=subject,
        teacher=teacher,
        class_name=mongo.db.classrooms.find_one(
            {"_id": assignment["class_id"]}
        )["class_name"],
        result_map=result_map,
          start_time=start_time,
        end_time=end_time
    )



@bp.route('/save-bulk-results', methods=['POST'])
def save_bulk_results():

    assignment_id = request.form.get('assignment_id')

    assignment = mongo.db.teacher_assignments.find_one({
        "_id": ObjectId(assignment_id)
    })

    if not assignment:
        return abort(404)

    created = 0
    updated = 0
    errors = []

    for key, value in request.form.items():

        if not key.startswith("scores["):
            continue

        student_id = key.replace("scores[", "").replace("]", "").strip()
        score = value.strip()

        # =========================
        # VALIDATION
        # =========================
        if score == "":
            continue  # ignore empty (DO NOT ERROR)

        try:
            score = int(score)
        except:
            errors.append(f"Student {student_id}: invalid number")
            continue

        if score < 0 or score > 50:
            errors.append(f"Student {student_id}: out of range")
            continue

        # =========================
        # CHECK EXISTING RESULT
        # =========================
        existing = mongo.db.results.find_one({
            "student_id": ObjectId(student_id),
            "assignment_id": assignment["_id"]
        })

        # =========================
        # UPDATE OR INSERT
        # =========================
        if existing:

            mongo.db.results.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "score": score,
                    "updated_at": datetime.utcnow()
                }}
            )
            updated += 1

        else:

            mongo.db.results.insert_one({
                "student_id": ObjectId(student_id),
                "teacher_id": assignment["teacher_id"],
                "subject_id": assignment["subject_id"],
                "class_id": assignment["class_id"],
                "section_id": assignment.get("section_id"),
                "assignment_id": assignment["_id"],
                "score": score,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })

            created += 1

    # =========================
    # FLASH MESSAGE
    # =========================
    if errors:
        flash(f"Saved with {len(errors)} errors!", "warning")
    else:
        flash(f"{created} created, {updated} updated successfully!", "success")

    return redirect(url_for('main.class_students', assignment_id=assignment_id))



@bp.route('/student-login', methods=['GET','POST'])
def student_login():

    if request.method == "POST":

        role_no = request.form.get(
            "role_no",
            ""
        ).strip()


        student = mongo.db.students.find_one({

            "role_no": role_no

        })


        if not student:

            flash(
                "Student ID lama helin!",
                "danger"
            )

            return redirect(
                url_for(
                    "main.student_login"
                )
            )



        return redirect(

            url_for(

                "main.student_dashboard",

                student_id=str(student["_id"])

            )

        )



    return render_template(
        "frontend/pages/student/login.html"
    )


@bp.route('/student-dashboard/<student_id>')
def student_dashboard(student_id):


    student = mongo.db.students.find_one({

        "_id": ObjectId(student_id)

    })


    if not student:

        abort(404)



    # ======================
    # CLASS
    # ======================

    classroom = None


    if student.get("class_id"):

        classroom = mongo.db.classrooms.find_one({

            "_id": ObjectId(
                student["class_id"]
            )

        })



    class_name = (

        classroom.get("class_name")

        if classroom

        else "N/A"

    )



    # ======================
    # SECTION OPTIONAL
    # ======================

    section_name = "N/A"


    if student.get("section_id"):


        section = mongo.db.sections.find_one({

            "_id": ObjectId(
                student["section_id"]
            )

        })


        if section:

            section_name = section.get(
                "section_name"
            )



    return render_template(

        "frontend/pages/student/dashboard.html",

        student=student,

        class_name=class_name,

        section_name=section_name

    )



@bp.route('/student-results/<student_id>')
def student_results(student_id):

    student = mongo.db.students.find_one({
        "_id": ObjectId(student_id)
    })

    if not student:
        return "Student Not Found", 404

    results = {}

    cursor = mongo.db.student_results.find({
        "student_id": student_id
    }).sort("created_at", -1)

    # ============================================
    # SUBJECT RESULTS
    # ============================================
    for r in cursor:

        subject = mongo.db.subjects.find_one({
            "_id": ObjectId(r["subject_id"])
        })

        if not subject:
            continue

        subject_name = subject.get("subject_name", "N/A")

        if subject_name not in results:
            results[subject_name] = {
                "subject": subject_name,
                "exams": [],
                "total": 0
            }

        score = r.get("score", 0)

        results[subject_name]["exams"].append({
            "type": r.get("exam_type"),
            "score": score
        })

        results[subject_name]["total"] += score

    # ============================================
    # TOTAL SCORE
    # ============================================
    grand_total = sum(item["total"] for item in results.values())

    # ============================================
    # SUBJECT COUNT
    # ============================================
    total_subjects = len(results)

    # ============================================
    # AVERAGE
    # ============================================
    average = round(
        grand_total / total_subjects,
        2
    ) if total_subjects else 0

    # ============================================
    # GRADE
    # ============================================
    if average >= 90:
        grade = "A+"
    elif average >= 80:
        grade = "A"
    elif average >= 70:
        grade = "B+"
    elif average >= 60:
        grade = "B"
    elif average >= 50:
        grade = "C"
    elif average >= 40:
        grade = "D"
    else:
        grade = "F"

    # ============================================
    # CLASS RANKING
    # ============================================

    classmates = list(
        mongo.db.students.find({
            "class_id": student["class_id"],
            "section_id": student["section_id"]
        })
    )

    class_ranking = []

    for s in classmates:

        total = 0

        marks = mongo.db.student_results.find({
            "student_id": str(s["_id"])
        })

        for mark in marks:
            total += mark.get("score", 0)

        class_ranking.append({
            "student_id": str(s["_id"]),
            "total": total
        })

    class_ranking.sort(
        key=lambda x: x["total"],
        reverse=True
    )

    class_position = "-"

    for index, item in enumerate(class_ranking, start=1):
        if item["student_id"] == student_id:
            class_position = index
            break

    total_class_students = len(class_ranking)

    # ============================================
    # SCHOOL RANKING
    # ============================================

    all_students = list(
        mongo.db.students.find()
    )

    school_ranking = []

    for s in all_students:

        total = 0

        marks = mongo.db.student_results.find({
            "student_id": str(s["_id"])
        })

        for mark in marks:
            total += mark.get("score", 0)

        school_ranking.append({
            "student_id": str(s["_id"]),
            "total": total
        })

    school_ranking.sort(
        key=lambda x: x["total"],
        reverse=True
    )

    school_position = "-"

    for index, item in enumerate(school_ranking, start=1):
        if item["student_id"] == student_id:
            school_position = index
            break

    total_school_students = len(school_ranking)

    # ============================================
    # RENDER
    # ============================================

    return render_template(
        "frontend/pages/student/results.html",

        student=student,
        student_id=student_id,

        results=list(results.values()),

        grand_total=grand_total,
        average=average,
        grade=grade,

        total_subjects=total_subjects,

        class_position=class_position,
        total_class_students=total_class_students,

        school_position=school_position,
        total_school_students=total_school_students
    )

    

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        fullname = request.form.get('fullname')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('password_confirmation')

        # 1. Hubi haddii passwords-ku isku mid yihiin
        if password != confirm_password:
            flash("Passwords-ka isma laha!", "danger")
            return redirect(url_for('main.register'))

        # 2. Hubi haddii user-ku horey u jiray
        if mongo.db.users.find_one({"email": email}):
            flash("Email-kan horey ayaa loo isticmaalay!", "danger")
            return redirect(url_for('main.register'))

        # 3. Role Logic
        user_count = mongo.db.users.count_documents({})
        role = UserRole.SUPERADMIN.value if user_count == 0 else UserRole.USER.value

        # 4. Save
        new_user = {
            "fullname": fullname,
            "username": username,
            "email": email,
            "password": generate_password_hash(password),
            "role": role,
            "status": False,
            "created_at": datetime.utcnow()
        }
        mongo.db.users.insert_one(new_user)
        
        flash("Diiwaangelinta way guulaysatay!", "success")
        return redirect(url_for('main.login'))

    # Wadada saxda ah ee faylkaaga:
    return render_template("backend/auth/auth-register.html")


@bp.route('/login', methods=['GET', 'POST'])
def login():
    # Haddi uu user-ku horay u soo galay, u dir dashboard-ka
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remembr_me') else False

        # 1. Ka raadi user-ka database-ka
        user_data = mongo.db.users.find_one({"email": email})

        # 2. Hubi haddii password-ku sax yahay
        if user_data and check_password_hash(user_data.get('password'), password):
            # Samee User object
            user = User(user_data) 
            
            # 3. Login u samee
            login_user(user, remember=remember)
            
            flash("Si guul leh ayaad u gashay dashboard-ka!", "success")
            return redirect(url_for('main.dashboard')) 
        else:
            flash("Email ama Password khaldan!", "danger")
            # Waxaan u beddelay 'auth.login' si uu ugu laabto isla boggaas
            return redirect(url_for('main.login')) 

    return render_template("backend/auth/auth-login.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    if current_user.role != 'superadmin':
        return abort(403) # ama redirect(url_for('login'))
        
    return render_template("backend/home/dashbaord.html", user=current_user)


@bp.route('/add-user', methods=['GET', 'POST'])
@login_required
def add_user():

    if current_user.role != UserRole.SUPERADMIN.value:
        abort(403)

    countries = [
        {"code": "SO", "name": "Somalia", "flag_url": "https://flagcdn.com/so.svg"},
        {"code": "KE", "name": "Kenya", "flag_url": "https://flagcdn.com/ke.svg"},
    ]

    if request.method == 'POST':

        fullname = request.form.get('fullname', '').strip()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        role = request.form.get('role', UserRole.USER.value)

        phone = request.form.get('phone')
        country = request.form.get('country')
        state = request.form.get('state')
        city = request.form.get('city')
        address = request.form.get('address')

        status = request.form.get('status') == '1'

        # ================= VALIDATION =================

        if not fullname or not username or not email or not password:
            flash("Fadlan buuxi dhammaan xogaha muhiimka ah.", "danger")
            return redirect(url_for('main.add_user'))

        if password != confirm_password:
            flash("Passwords-ka isma laha!", "danger")
            return redirect(url_for('main.add_user'))

        if mongo.db.users.find_one({"email": email}):
            flash("Email-kan horey ayaa loo isticmaalay!", "danger")
            return redirect(url_for('main.add_user'))

        if mongo.db.users.find_one({"username": username}):
            flash("Username-kan horey ayaa loo isticmaalay!", "danger")
            return redirect(url_for('main.add_user'))

        # ================= PHOTO UPLOAD =================

        photo_path = ""

        file = request.files.get("photo")

        if file and file.filename:

            upload_dir = os.path.join(
                current_app.root_path,
                'static',
                'backend',
                'uploads',
                'users'
            )

            os.makedirs(upload_dir, exist_ok=True)

            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"

            file.save(os.path.join(upload_dir, filename))

            photo_path = f"backend/uploads/users/{filename}"

        # ================= CREATE USER =================

        now = datetime.utcnow()

        user_data = {
            "fullname": fullname,
            "username": username,
            "email": email,
            "password": generate_password_hash(password),

            # Role System
            "role": role,
            "role_id": None,

            # Basic Info
            "phone": phone,
            "country": country,
            "state": state,
            "city": city,
            "address": address,
            "photo": photo_path,
            "bio": "",
            "gender": None,
            "photo_visibility": "everyone",

            # Status
            "status": status,

            # Security
            "is_verified": False,
            "auth_status": "logout",
            "phone_verified": False,
            "two_factor_enabled": False,
            "failed_login_attempts": 0,
            "auth_provider": "local",

            # Device
            "device": None,
            "browser": None,
            "platform": None,
            "device_name": None,
            "interface_name": None,

            # Socials
            "facebook": None,
            "twitter": None,
            "google": None,
            "whatsapp": None,
            "instagram": None,
            "github": None,
            "github_id": None,

            # Relationships
            "teacher_id": None,
            "user_logs": [],
            "sessions": [],
            "user_permissions": [],

            # Timestamps
            "created_at": now,
            "updated_at": now,
            "last_active": now
        }

        result = mongo.db.users.insert_one(user_data)

        # Haddii user-ku yahay teacher
        if role == UserRole.TEACHER.value:
            teacher = {
                "user_id": str(result.inserted_id),
                "fullname": fullname,
                "email": email,
                "phone": phone,
                "status": True,
                "created_at": now
            }

            teacher_result = mongo.db.teachers.insert_one(teacher)

            mongo.db.users.update_one(
                {"_id": result.inserted_id},
                {
                    "$set": {
                        "teacher_id": str(teacher_result.inserted_id)
                    }
                }
            )

        flash(
            f"User {username} si guul leh ayaa loo diiwaangeliyey!",
            "success"
        )

        return redirect(url_for('main.add_user'))

    return render_template(
        "backend/pages/components/users/add_user.html",
        countries=countries,
        roles=[role.value for role in UserRole]
    )



@bp.route('/edit-user/<user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if current_user.role != 'superadmin':
        return abort(403)

    raw_user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not raw_user:
        flash("User-ka lama helin!", "danger")
        return redirect(url_for('main.index'))

    user = User(raw_user)

    if request.method == 'POST':

        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        updated_data = {
            "fullname": request.form.get('fullname'),
            "username": request.form.get('username'),
            "email": request.form.get('email'),
            "role": request.form.get('role'),
            "country": request.form.get('country'),
            "phone": request.form.get('phone'),
            "address": request.form.get('address'),
            "bio": request.form.get('bio'),
            "status": True if request.form.get('status') == '1' else False,
            "updated_at": datetime.utcnow()
        }

        # ================= PASSWORD FIX =================
        if password:
            if password != confirm_password:
                flash("Passwords-ka isma laha!", "danger")
                return redirect(url_for('main.edit_user', user_id=user_id))

            updated_data["password"] = generate_password_hash(password)

        file = request.files.get('photo')

        if file and file.filename:

            # ================= DELETE OLD IMAGE =================
            old_photo = raw_user.get("photo")

            if old_photo:
                old_path = os.path.join(
                    os.path.abspath(os.getcwd()),
                    'static',
                    old_photo
                )

                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception as e:
                        print(f"Error deleting old image: {e}")

            # ================= SAVE NEW IMAGE =================
            project_root = os.path.abspath(os.getcwd())

            upload_dir = os.path.join(
                project_root,
                'static',
                'backend',
                'uploads',
                'users'
            )

            os.makedirs(upload_dir, exist_ok=True)

            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file_path = os.path.join(upload_dir, filename)

            file.save(file_path)

            # DB PATH
            updated_data["photo"] = f"backend/uploads/users/{filename}"

        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": updated_data}
        )

        flash("Macluumaadka si guul leh ayaa loo cusbooneysiiyey!", "success")
        return redirect(url_for('main.edit_user', user_id=user_id))

    return render_template(
        "backend/pages/components/users/edit_user.html",
        user=user
    )



@bp.route('/delete-user/<user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'superadmin':
        return abort(403)

    # 1. Get user
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})

    # 2. Delete image file if exists
    if user and user.get('photo'):

        # correct project root
        project_root = os.path.abspath(os.getcwd())

        file_path = os.path.join(
            project_root,
            'static',
            user['photo']  # example: backend/uploads/users/xxx.jpg
        )

        if os.path.exists(file_path):
            os.remove(file_path)

    # 3. Delete user from DB
    mongo.db.users.delete_one({"_id": ObjectId(user_id)})

    flash("User-ka si guul leh ayaa loo tirtiray!", "success")
    return redirect(url_for('main.all_users'))


@bp.route('/all-users', methods=['GET'])
@login_required
def all_users():
    if current_user.role != 'superadmin':
        return abort(403) # ama redirect(url_for('login'))
        
    # 1. Ka soo saar dhammaan users-ka database-ka
    # .sort('-created_at') waxaa loola jeedaa inuu ku kala sooco taariikhda (ugu dambeeyay ugu horreeya)
    users_cursor = mongo.db.users.find().sort('created_at', -1)
    
    # 2. U beddel document kasta (dictionary) inuu noqdo User object
    # Tani waxay isticmaaleysaa fasalkaaga User ee aan horey uga soo hadalnay
    users = [User(user_data) for user_data in users_cursor]
    
    # 3. U dir template-ka
    return render_template('backend/pages/components/users/all_users.html', users=users)





@bp.route('/add-class', methods=['GET', 'POST'])
@login_required
def add_class():

    if current_user.role not in ['superadmin', 'admin']:
        abort(403)

    if request.method == 'POST':

        class_name = request.form.get('class_name', '').strip()
        shift_name = request.form.get('shift_name', '').strip()
        description = request.form.get('description', '').strip()

        if not class_name:
            flash("Fadlan geli magaca fasalka!", "danger")
            return redirect(url_for('main.add_class'))

        if not shift_name:
            flash("Fadlan dooro shift!", "danger")
            return redirect(url_for('main.add_class'))

        # Prevent duplicate (same class + same shift)
        existing_class = mongo.db.classrooms.find_one({
            "class_name": class_name,
            "shift_name": shift_name
        })

        if existing_class:
            flash("Fasalkan iyo shift-kan hore ayey u jiraan!", "warning")
            return redirect(url_for('main.add_class'))

        africa_time = datetime.now(pytz.timezone("Africa/Nairobi"))

        mongo.db.classrooms.insert_one({
            "class_name": class_name,
            "shift_name": shift_name,
            "description": description,
            "created_at": africa_time,
            "updated_at": africa_time
        })

        flash(
            f"Fasalka {class_name} ({shift_name}) si guul leh ayaa loo diiwaangeliyey!",
            "success"
        )

        return redirect(url_for('main.add_class'))

    return render_template(
        "backend/pages/components/classes/add_class.html"
    )



@bp.route('/all-classes', methods=['GET'])
@login_required
def all_classes():

    # Permission check (haddii aad rabto admin kaliya)
    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    # 1. Get all classes from DB
    classes_cursor = mongo.db.classrooms.find().sort('created_at', -1)

    # 2. Convert to ClassRoom objects
    classes = [ClassRoom(class_data) for class_data in classes_cursor]

    # 3. Send to template
    return render_template(
        'backend/pages/components/classes/all_classes.html',
        classes=classes
    )



@bp.route('/edit-class/<class_id>', methods=['GET', 'POST'])
@login_required
def edit_class(class_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    classroom = mongo.db.classrooms.find_one({
        "_id": ObjectId(class_id)
    })

    if not classroom:
        abort(404)

    if request.method == 'POST':

        class_name = request.form.get('class_name')
        shift_name = request.form.get('shift_name')
        description = request.form.get('description')

        if not class_name:
            flash("Class name waa mandatory!", "danger")
            return redirect(url_for('main.edit_class', class_id=class_id))

        africa_time = datetime.now(pytz.timezone("Africa/Nairobi"))

        mongo.db.classrooms.update_one(
            {"_id": ObjectId(class_id)},
            {
                "$set": {
                    "class_name": class_name,
                    "shift_name": shift_name,
                    "description": description,
                    "updated_at": africa_time
                }
            }
        )

        flash("Class si guul leh ayaa loo update gareeyay!", "success")
        return redirect(url_for('main.all_classes'))

    return render_template(
        "backend/pages/components/classes/edit_class.html",
        classroom=ClassRoom(classroom)
    )



@bp.route('/delete-class/<class_id>', methods=['POST'])
@login_required
def delete_class(class_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    result = mongo.db.classrooms.delete_one({
        "_id": ObjectId(class_id)
    })

    if result.deleted_count == 0:
        flash("Class lama helin!", "danger")
    else:
        flash("Class si guul leh ayaa loo tirtiray!", "success")

    return redirect(url_for('main.all_classes'))





@bp.route('/add-section', methods=['GET', 'POST'])
@login_required
def add_section():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    if request.method == 'POST':

        section_name = request.form.get('section_name')
        class_id = request.form.get('class_id')

        # VALIDATION
        if not section_name or not class_id:
            flash("Fadlan buuxi section iyo class!", "danger")
            return redirect(url_for('main.add_section'))

        # CHECK CLASS EXISTS
        classroom = mongo.db.classrooms.find_one({
            "_id": ObjectId(class_id)
        })

        if not classroom:
            flash("Class lama helin!", "danger")
            return redirect(url_for('main.add_section'))

        # CHECK DUPLICATE SECTION
        existing = mongo.db.sections.find_one({
            "section_name": section_name,
            "class_id": class_id
        })

        if existing:
            flash("Section-kan hore ayuu u jiraa!", "warning")
            return redirect(url_for('main.add_section'))

        # INSERT
        mongo.db.sections.insert_one({
            "section_name": section_name,
            "class_id": class_id,
            "created_at": datetime.utcnow()
        })

        flash("Section si guul leh ayaa loo daray!", "success")
        return redirect(url_for('main.all_sections'))

    # GET CLASSES FOR DROPDOWN
    classes = mongo.db.classrooms.find().sort("class_name", 1)

    return render_template(
        "backend/pages/components/sections/add_section.html",
        classes=classes
    )




@bp.route('/all-sections')
@login_required
def all_sections():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    # Get sections (newest first)
    sections_cursor = mongo.db.sections.find().sort('created_at', -1)

    sections = []

    for section in sections_cursor:

        # get class info for each section
        classroom = mongo.db.classrooms.find_one({
            "_id": ObjectId(section.get("class_id"))
        })

        sections.append({
            "id": str(section.get("_id")),
            "section_name": section.get("section_name"),
            "class_name": classroom.get("class_name") if classroom else "Unknown",
            "created_at": section.get("created_at")
        })

    return render_template(
        "backend/pages/components/sections/all_sections.html",
        sections=sections
    )



@bp.route('/edit-section/<section_id>', methods=['GET', 'POST'])
@login_required
def edit_section(section_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    section = mongo.db.sections.find_one({
        "_id": ObjectId(section_id)
    })

    if not section:
        abort(404)

    if request.method == 'POST':

        section_name = request.form.get('section_name')
        class_id = request.form.get('class_id')

        if not section_name or not class_id:
            flash("Fadlan buuxi dhammaan xogta!", "danger")
            return redirect(url_for('main.edit_section', section_id=section_id))

        mongo.db.sections.update_one(
            {"_id": ObjectId(section_id)},
            {
                "$set": {
                    "section_name": section_name,
                    "class_id": class_id
                }
            }
        )

        flash("Section si guul leh ayaa loo update gareeyay!", "success")
        return redirect(url_for('main.all_sections'))

    classes = mongo.db.classrooms.find()

    return render_template(
        "backend/pages/components/sections/edit_section.html",
        section=section,
        classes=classes
    )


@bp.route('/delete-section/<section_id>', methods=['POST'])
@login_required
def delete_section(section_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    result = mongo.db.sections.delete_one({
        "_id": ObjectId(section_id)
    })

    if result.deleted_count == 0:
        flash("Section lama helin!", "danger")
    else:
        flash("Section si guul leh ayaa loo tirtiray!", "success")

    return redirect(url_for('main.all_sections'))




@bp.route('/add-subject', methods=['GET', 'POST'])
@login_required
def add_subject():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    if request.method == 'POST':

        subject_name = request.form.get('subject_name')

        if not subject_name:
            flash("Fadlan geli magaca subject-ka!", "danger")
            return redirect(url_for('main.add_subject'))

        # check duplicate
        existing = mongo.db.subjects.find_one({
            "subject_name": subject_name
        })

        if existing:
            flash("Subject-kan hore ayuu u jiraa!", "warning")
            return redirect(url_for('main.add_subject'))

        mongo.db.subjects.insert_one({
            "subject_name": subject_name,
            "created_at": datetime.utcnow()
        })

        flash("Subject si guul leh ayaa loo daray!", "success")
        return redirect(url_for('main.all_subjects'))

    return render_template(
        "backend/pages/components/subjects/add_subject.html"
    )


    
@bp.route('/all-subjects')
@login_required
def all_subjects():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    subjects_cursor = mongo.db.subjects.find().sort('created_at', -1)

    subjects = [Subject(s) for s in subjects_cursor]

    return render_template(
        "backend/pages/components/subjects/all_subjects.html",
        subjects=subjects
    )

@bp.route('/edit-subject/<subject_id>', methods=['GET', 'POST'])
@login_required
def edit_subject(subject_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    subject = mongo.db.subjects.find_one({
        "_id": ObjectId(subject_id)
    })

    if not subject:
        abort(404)

    if request.method == 'POST':

        subject_name = request.form.get('subject_name')

        mongo.db.subjects.update_one(
            {"_id": ObjectId(subject_id)},
            {"$set": {"subject_name": subject_name}}
        )

        flash("Subject waa la update gareeyay!", "success")
        return redirect(url_for('main.all_subjects'))

    return render_template(
        "backend/pages/components/subjects/edit_subject.html",
        subject=Subject(subject)
    )

@bp.route('/delete-subject/<subject_id>', methods=['POST'])
@login_required
def delete_subject(subject_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    mongo.db.subjects.delete_one({
        "_id": ObjectId(subject_id)
    })

    flash("Subject waa la tirtiray!", "success")
    return redirect(url_for('main.all_subjects'))





def generate_teacher_role_id():
    while True:
        code = random.randint(1000000, 9999999)

        full_code = f"TCH-{code}"

        existing = mongo.db.teachers.find_one({
            "teacher_role_id": full_code
        })

        if not existing:
            return full_code


@bp.route('/add-teacher', methods=['GET', 'POST'])
@login_required
def add_teacher():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    if request.method == 'POST':

        full_name = request.form.get('full_name')

        if not full_name:
            flash("Fadlan geli magaca macallinka!", "danger")
            return redirect(url_for('main.add_teacher'))

        teacher_role_id = generate_teacher_role_id()

        mongo.db.teachers.insert_one({
            "teacher_role_id": teacher_role_id,
            "full_name": full_name,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        flash(f"Macallin la diiwaangeliyey: {teacher_role_id}", "success")
        return redirect(url_for('main.all_teachers'))

    classes = mongo.db.classrooms.find()
    sections = mongo.db.sections.find()
    subjects = mongo.db.subjects.find()

    return render_template(
        "backend/pages/components/teachers/add_teacher.html",
        classes=classes,
        sections=sections,
        subjects=subjects
    )




@bp.route('/all-teachers')
@login_required
def all_teachers():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    teachers_cursor = mongo.db.teachers.find().sort('created_at', -1)

    teachers = []

    for t in teachers_cursor:

        # Get related data
        class_names = []
        section_names = []
        subject_names = []

        if t.get("class_ids"):
            classes = mongo.db.classrooms.find({
                "_id": {"$in": t["class_ids"]}
            })
            class_names = [c["class_name"] for c in classes]

        if t.get("section_ids"):
            sections = mongo.db.sections.find({
                "_id": {"$in": t["section_ids"]}
            })
            section_names = [s["section_name"] for s in sections]

        if t.get("subject_ids"):
            subjects = mongo.db.subjects.find({
                "_id": {"$in": t["subject_ids"]}
            })
            subject_names = [s["subject_name"] for s in subjects]

        teachers.append({
            "id": str(t["_id"]),
            "teacher_role_id": t.get("teacher_role_id"),
            "full_name": t.get("full_name"),
            "class_names": class_names,
            "section_names": section_names,
            "subject_names": subject_names,
            "created_at": t.get("created_at")
        })

    return render_template(
        "backend/pages/components/teachers/all_teachers.html",
        teachers=teachers
    )




@bp.route('/edit-teacher/<teacher_id>', methods=['GET', 'POST'])
@login_required
def edit_teacher(teacher_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    teacher = mongo.db.teachers.find_one({
        "_id": ObjectId(teacher_id)
    })

    if not teacher:
        return abort(404)

    if request.method == 'POST':

        full_name = request.form.get('full_name')

        if not full_name:
            flash("Magaca macallinka waa mandatory!", "danger")
            return redirect(url_for('main.edit_teacher', teacher_id=teacher_id))

        # SAFE conversion (avoid empty values)
        class_ids = [
            ObjectId(cid) for cid in request.form.getlist('class_ids[]') if cid
        ]

        section_ids = [
            ObjectId(sid) for sid in request.form.getlist('section_ids[]') if sid
        ]

        subject_ids = [
            ObjectId(sub) for sub in request.form.getlist('subject_ids[]') if sub
        ]

        mongo.db.teachers.update_one(
            {"_id": ObjectId(teacher_id)},
            {
                "$set": {
                    "full_name": full_name,

                    # ⚠️ KEEP ONLY IF YOU STILL USE OLD STRUCTURE
                    "class_ids": class_ids,
                    "section_ids": section_ids,
                    "subject_ids": subject_ids,

                    "updated_at": datetime.utcnow()
                }
            }
        )

        flash("Macallin si guul leh ayaa loo update gareeyay!", "success")
        return redirect(url_for('main.all_teachers'))

    classes = mongo.db.classrooms.find()
    sections = mongo.db.sections.find()
    subjects = mongo.db.subjects.find()

    return render_template(
        "backend/pages/components/teachers/edit_teacher.html",
        teacher=teacher,
        classes=classes,
        sections=sections,
        subjects=subjects
    )




@bp.route('/delete-teacher/<teacher_id>', methods=['POST'])
@login_required
def delete_teacher(teacher_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    result = mongo.db.teachers.delete_one({
        "_id": ObjectId(teacher_id)
    })

    if result.deleted_count == 0:
        flash("Macallin lama helin!", "danger")
    else:
        flash("Macallin si guul leh ayaa loo tirtiray!", "success")

    return redirect(url_for('main.all_teachers'))



@bp.route('/bulk-assign-teacher', methods=['GET', 'POST'])
@login_required
def bulk_assign_teacher():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    if request.method == 'POST':

        teacher_id = request.form.get('teacher_id')

        class_ids = request.form.getlist('class_ids')
        section_ids = request.form.getlist('section_ids')
        subject_ids = request.form.getlist('subject_ids')

        if not teacher_id:
            flash("Fadlan dooro macallinka!", "danger")
            return redirect(url_for('main.bulk_assign_teacher'))

        created_count = 0
        skipped_count = 0

        rows_count = max(
            len(class_ids),
            len(section_ids),
            len(subject_ids)
        )

        for i in range(rows_count):

            class_id = class_ids[i] if i < len(class_ids) else ""
            section_id = section_ids[i] if i < len(section_ids) else ""
            subject_id = subject_ids[i] if i < len(subject_ids) else ""

            if not class_id or not subject_id:
                continue

            query = {
                "teacher_id": ObjectId(teacher_id),
                "class_id": ObjectId(class_id),
                "subject_id": ObjectId(subject_id)
            }

            if section_id:
                query["section_id"] = ObjectId(section_id)
            else:
                query["section_id"] = None

            existing = mongo.db.teacher_assignments.find_one(query)

            if existing:
                skipped_count += 1
                continue

            mongo.db.teacher_assignments.insert_one({
                "teacher_id": ObjectId(teacher_id),
                "class_id": ObjectId(class_id),
                "section_id": ObjectId(section_id) if section_id else None,
                "subject_id": ObjectId(subject_id),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })

            created_count += 1

        flash(
            f"{created_count} assignments created, {skipped_count} duplicates skipped.",
            "success"
        )

        return redirect(url_for('main.all_teacher_assignments'))

    teachers = list(mongo.db.teachers.find())
    classes = list(mongo.db.classrooms.find())
    sections = list(mongo.db.sections.find())
    subjects = list(mongo.db.subjects.find())

    return render_template(
        "backend/pages/components/teachers/assign_teacher.html",
        teachers=teachers,
        classes=classes,
        sections=sections,
        subjects=subjects
    )


    
@bp.route('/edit-assignment/<assignment_id>', methods=['GET', 'POST'])
@login_required
def edit_assignment(assignment_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    assignment = mongo.db.teacher_assignments.find_one({
        "_id": ObjectId(assignment_id)
    })

    if not assignment:
        return abort(404)

    if request.method == 'POST':

        teacher_id = request.form.get('teacher_id')
        class_id = request.form.get('class_id')
        section_id = request.form.get('section_id')
        subject_id = request.form.get('subject_id')

        update_data = {
            "teacher_id": ObjectId(teacher_id),
            "class_id": ObjectId(class_id),
            "subject_id": ObjectId(subject_id),
            "updated_at": datetime.utcnow()
        }

        # section optional
        if section_id:
            update_data["section_id"] = ObjectId(section_id)
        else:
            update_data["section_id"] = None

        mongo.db.teacher_assignments.update_one(
            {"_id": ObjectId(assignment_id)},
            {"$set": update_data}
        )

        flash("Assignment updated successfully!", "success")
        return redirect(url_for('main.all_teacher_assignments'))

    teachers = list(mongo.db.teachers.find())
    classes = list(mongo.db.classrooms.find())
    sections = list(mongo.db.sections.find())
    subjects = list(mongo.db.subjects.find())

    return render_template(
        "backend/pages/components/teachers/edit_assignment.html",
        assignment=assignment,
        teachers=teachers,
        classes=classes,
        sections=sections,
        subjects=subjects
    )


@bp.route('/delete-assignment/<assignment_id>', methods=['POST'])
@login_required
def delete_assignment(assignment_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    mongo.db.teacher_assignments.delete_one({
        "_id": ObjectId(assignment_id)
    })

    flash("Assignment deleted successfully!", "success")

    return redirect(url_for('main.all_teacher_assignments'))





# ALL TEACHERS DEADLINE
@bp.route('/add-result-deadline', methods=['POST'])
@login_required
def add_result_deadline_all():

    start_time_str = request.form.get("start_time")
    end_time_str = request.form.get("end_time")


    if not start_time_str or not end_time_str:
        flash("Start and End time required", "danger")
        return redirect(request.referrer)


    try:
        start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M")
        end_time = datetime.strptime(end_time_str, "%Y-%m-%dT%H:%M")

    except ValueError:
        flash("Invalid datetime format", "danger")
        return redirect(request.referrer)


    if end_time <= start_time:
        flash("End time must be after start time", "danger")
        return redirect(request.referrer)



    mongo.db.teacher_assignments.update_many(
        {},
        {
            "$set": {
                "start_time": start_time,
                "end_time": end_time,
                "updated_at": datetime.utcnow()
            }
        }
    )


    flash("Deadline assigned to all teachers successfully!", "success")

    return redirect(request.referrer)




# SINGLE ASSIGNMENT DEADLINE
@bp.route('/add-result-deadline/<assignment_id>', methods=['POST'])
@login_required
def add_result_deadline_single(assignment_id):

    start_time_str = request.form.get("start_time")
    end_time_str = request.form.get("end_time")


    if not start_time_str or not end_time_str:
        flash("Start and End time required", "danger")
        return redirect(request.referrer)


    try:

        start_time = datetime.strptime(
            start_time_str,
            "%Y-%m-%dT%H:%M"
        )

        end_time = datetime.strptime(
            end_time_str,
            "%Y-%m-%dT%H:%M"
        )


    except ValueError:

        flash("Invalid datetime format", "danger")
        return redirect(request.referrer)



    if end_time <= start_time:

        flash(
            "End time must be after start time",
            "danger"
        )

        return redirect(request.referrer)




    # GET ASSIGNMENT
    assignment = mongo.db.teacher_assignments.find_one(
        {
            "_id": ObjectId(assignment_id)
        }
    )


    if not assignment:

        flash(
            "Assignment not found!",
            "danger"
        )

        return redirect(request.referrer)



    # GET CLASS ID
    class_id = assignment.get("class_id")


    if not class_id:

        flash(
            "Class ID missing!",
            "danger"
        )

        return redirect(request.referrer)



    # REMOVE OLD DEADLINE FOR SAME CLASS
    mongo.db.teacher_assignments.update_many(
        {
            "class_id": class_id
        },
        {
            "$unset": {
                "start_time": "",
                "end_time": ""
            }
        }
    )



    # ADD NEW DEADLINE FOR SAME CLASS
    result = mongo.db.teacher_assignments.update_many(
        {
            "class_id": class_id
        },
        {
            "$set": {

                "start_time": start_time,

                "end_time": end_time,

                "updated_at": datetime.utcnow()

            }
        }
    )



    if result.modified_count:

        flash(
            "Deadline updated successfully for this class!",
            "success"
        )

    else:

        flash(
            "Deadline update failed!",
            "danger"
        )


    return redirect(request.referrer)

@bp.route('/remove-result-deadline', methods=['POST'])
@login_required
def remove_result_deadline():

    # =========================
    # REMOVE DEADLINE FIELDS
    # =========================
    mongo.db.teacher_assignments.update_many(
        {},
        {
            "$unset": {
                "start_time": "",
                "end_time": ""
            },
            "$set": {
                "updated_at": datetime.utcnow()
            }
        }
    )

    flash("⛔ Deadline successfully removed from all assignments!", "success")
    return redirect(request.referrer or url_for('main.index'))



@bp.route('/remove-result-deadline/<teacher_id>', methods=['POST'])
@login_required
def remove_teacher_deadline(teacher_id):

    mongo.db.teacher_assignments.update_many(
        {"teacher_id": ObjectId(teacher_id)},
        {
            "$unset": {
                "start_time": "",
                "end_time": ""
            },
            "$set": {
                "updated_at": datetime.utcnow()
            }
        }
    )

    flash("Deadline removed for this teacher!", "success")
    return redirect(request.referrer)



@bp.route('/all-teacher-assignments')
@login_required
def all_teacher_assignments():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    assignments = mongo.db.teacher_assignments.find()

    data = []

    for a in assignments:

        teacher = mongo.db.teachers.find_one({"_id": a["teacher_id"]})
        class_ = mongo.db.classrooms.find_one({"_id": a["class_id"]})
        section = mongo.db.sections.find_one({"_id": a["section_id"]})
        subject = mongo.db.subjects.find_one({"_id": a["subject_id"]})

        data.append({
            "id": str(a["_id"]),
            "teacher": teacher["full_name"] if teacher else "",
            "class": class_["class_name"] if class_ else "",
            "section": section["section_name"] if section else "",
            "subject": subject["subject_name"] if subject else "",
            "created_at": a.get("created_at")
        })

    # GET CURRENT DEADLINE
    deadline = mongo.db.teacher_assignments.find_one({
        "start_time": {"$exists": True},
        "end_time": {"$exists": True}
    })

    start_time = deadline.get("start_time") if deadline else None
    end_time = deadline.get("end_time") if deadline else None

    return render_template(
        "backend/pages/components/teachers/all_teacher_assignments.html",
        assignments=data,
        start_time=start_time,
        end_time=end_time
    )



@bp.route('/admin/export-teacher-assignments')
@login_required
def export_teacher_assignments():

    assignments = list(mongo.db.teacher_assignments.find())

    wb = Workbook()

    # =========================
    # SHEET 1: DETAILS
    # =========================
    ws = wb.active
    ws.title = "Assignments"

    ws.append([
        "Teacher Role ID",
        "Teacher Name",
        "Class Name",
        "Section Name",
        "Subject Name",
        "Start Time",
        "End Time",
        "Created At"
    ])

    # =========================
    # SUMMARY DATA MAP
    # =========================
    summary_map = {}

    for a in assignments:

        # teacher
        teacher = mongo.db.teachers.find_one({
            "_id": a.get("teacher_id")
        })

        teacher_name = teacher.get("full_name") if teacher else "N/A"
        teacher_role = teacher.get("teacher_role_id") if teacher else "N/A"

        # class
        classroom = mongo.db.classrooms.find_one({"_id": a.get("class_id")})
        class_name = classroom.get("class_name") if classroom else "N/A"

        # section
        section = None
        section_name = "No Section"
        if a.get("section_id"):
            section = mongo.db.sections.find_one({"_id": a.get("section_id")})
            section_name = section.get("section_name") if section else "No Section"

        # subject
        subject = mongo.db.subjects.find_one({"_id": a.get("subject_id")})
        subject_name = subject.get("subject_name") if subject else "N/A"

        # =========================
        # WRITE MAIN ROW
        # =========================
        ws.append([
            teacher_role,
            teacher_name,
            class_name,
            section_name,
            subject_name,
            a.get("start_time"),
            a.get("end_time"),
            a.get("created_at")
        ])

        # =========================
        # SUMMARY BUILD
        # =========================
        if teacher_role not in summary_map:
            summary_map[teacher_role] = {
                "teacher_name": teacher_name,
                "classes": set(),
                "sections": set(),
                "subjects": set(),
                "assignments": 0
            }

        summary_map[teacher_role]["classes"].add(class_name)
        summary_map[teacher_role]["sections"].add(section_name)
        summary_map[teacher_role]["subjects"].add(subject_name)
        summary_map[teacher_role]["assignments"] += 1

    # =========================
    # SHEET 2: SUMMARY REPORT
    # =========================
    ws2 = wb.create_sheet("Summary Report")

    ws2.append([
        "Teacher Role ID",
        "Teacher Name",
        "Total Classes",
        "Total Sections",
        "Total Subjects",
        "Total Assignments"
    ])

    for role_id, data in summary_map.items():

        ws2.append([
            role_id,
            data["teacher_name"],
            len(data["classes"]),
            len(data["sections"]),
            len(data["subjects"]),
            data["assignments"]
        ])

    # =========================
    # EXPORT FILE
    # =========================
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        download_name="teacher_assignments_report.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def generate_student_role_no():
    counter = mongo.db.counters.find_one_and_update(
        {"_id": "student_role"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )

    seq = counter.get("seq", 1)
    return f"STD-{seq:04d}"


@bp.route('/add-student', methods=['GET', 'POST'])
@login_required
def add_student():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    if request.method == 'POST':

        full_name = request.form.get('full_name', '').strip()
        class_id = request.form.get('class_id')
        section_id = request.form.get('section_id')  # optional
        status = request.form.get('status')

        if not full_name or not class_id:
            flash("Fadlan geli magaca ardayga iyo fasalka!", "danger")
            return redirect(url_for('main.add_student'))

        # 🔥 GET CLASS + SHIFT AUTO
        selected_class = mongo.db.classrooms.find_one({
            "_id": ObjectId(class_id)
        })

        shift_name = selected_class.get("shift_name") if selected_class else None

        role_no = generate_student_role_no()

        student_data = {
            "role_no": role_no,
            "full_name": full_name,
            "class_id": ObjectId(class_id),
            "section_id": ObjectId(section_id) if section_id else None,

            # 🔥 AUTO SHIFT FROM CLASS
            "shift_name": shift_name,

            "status": True if status == "on" else False,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        mongo.db.students.insert_one(student_data)

        flash(f"Arday la diiwaangeliyey: {role_no}", "success")
        return redirect(url_for('main.all_students'))

    classes = list(mongo.db.classrooms.find())
    sections = list(mongo.db.sections.find())

    return render_template(
        "backend/pages/components/students/add_student.html",
        classes=classes,
        sections=sections
    )


@bp.route('/all-students')
@login_required
def all_students():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    students_cursor = mongo.db.students.find().sort('created_at', -1)

    students = []

    for s in students_cursor:

        # Get class
        class_name = None
        if s.get("class_id"):
            c = mongo.db.classrooms.find_one({
                "_id": ObjectId(s["class_id"])
            })
            class_name = c["class_name"] if c else "N/A"

        # Get section
        section_name = None
        if s.get("section_id"):
            sec = mongo.db.sections.find_one({
                "_id": ObjectId(s["section_id"])
            })
            section_name = sec["section_name"] if sec else "N/A"

        # 🔥 SHIFT (from student or fallback from class)
        shift_name = s.get("shift_name")

        if not shift_name and s.get("class_id"):
            c = mongo.db.classrooms.find_one({
                "_id": ObjectId(s["class_id"])
            })
            shift_name = c.get("shift_name") if c else None

        students.append({
            "id": str(s["_id"]),
            "role_no": s.get("role_no"),
            "full_name": s.get("full_name"),
            "class_name": class_name,
            "section_name": section_name,

            # 🔥 NEW SHIFT FIELD
            "shift_name": shift_name,

            "status": s.get("status", True),
            "created_at": s.get("created_at")
        })

    return render_template(
        "backend/pages/components/students/all_students.html",
        students=students
    )

@bp.route('/edit-student/<student_id>', methods=['GET', 'POST'])
@login_required
def edit_student(student_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    student = mongo.db.students.find_one({
        "_id": ObjectId(student_id)
    })

    if not student:
        return abort(404)

    if request.method == 'POST':

        full_name = request.form.get('full_name', '').strip()
        class_id = request.form.get('class_id')
        section_id = request.form.get('section_id')
        status = request.form.get('status')

        if not full_name or not class_id:
            flash("Magaca ardayga iyo fasalka waa mandatory!", "danger")
            return redirect(url_for('main.edit_student', student_id=student_id))

        # 🔥 GET CLASS FOR SHIFT AUTO UPDATE
        selected_class = mongo.db.classrooms.find_one({
            "_id": ObjectId(class_id)
        })

        shift_name = selected_class.get("shift_name") if selected_class else None

        update_data = {
            "full_name": full_name,
            "class_id": ObjectId(class_id),

            # 🔥 AUTO SHIFT UPDATE
            "shift_name": shift_name,

            "status": True if status == "on" else False,
            "updated_at": datetime.utcnow()
        }

        # SECTION OPTIONAL
        if section_id:
            update_data["section_id"] = ObjectId(section_id)
        else:
            update_data["section_id"] = None

        mongo.db.students.update_one(
            {"_id": ObjectId(student_id)},
            {"$set": update_data}
        )

        flash("Arday si guul leh ayaa loo update gareeyay!", "success")
        return redirect(url_for('main.all_students'))

    classes = list(mongo.db.classrooms.find())
    sections = list(mongo.db.sections.find())

    return render_template(
        "backend/pages/components/students/edit_student.html",
        student=student,
        classes=classes,
        sections=sections
    )

@bp.route('/delete-student/<student_id>', methods=['POST'])
@login_required
def delete_student(student_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    result = mongo.db.students.delete_one({
        "_id": ObjectId(student_id)
    })

    if result.deleted_count == 0:
        flash("Arday lama helin!", "danger")
    else:
        flash("Arday si guul leh ayaa loo tirtiray!", "success")

    return redirect(url_for('main.all_students'))



@bp.route('/export-students')
@login_required
def export_students():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    students = mongo.db.students.find()

    output = io.StringIO()
    writer = csv.writer(output)

    # HEADER
    writer.writerow([
        "Role No",
        "Full Name",
        "Class Name",
        "Section Name",
        "Shift",
        "Status",
        "Created At"
    ])

    for s in students:

        # CLASS NAME
        class_name = ""
        shift_name = ""

        if s.get("class_id"):
            c = mongo.db.classrooms.find_one({
                "_id": ObjectId(s["class_id"])
            })
            if c:
                class_name = c.get("class_name", "")
                
                # fallback shift from class if student has none
                shift_name = s.get("shift_name") or c.get("shift_name", "")

        # SECTION NAME
        section_name = ""
        if s.get("section_id"):
            sec = mongo.db.sections.find_one({
                "_id": ObjectId(s["section_id"])
            })
            section_name = sec["section_name"] if sec else ""

        writer.writerow([
            s.get("role_no"),
            s.get("full_name"),
            class_name,
            section_name,

            # 🔥 SHIFT ADDED
            shift_name,

            s.get("status"),
            s.get("created_at")
        ])

    output.seek(0)

    return Response(
        output,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment;filename=students.csv"
        }
    )



@bp.route('/import-students', methods=['POST'])
@login_required
def import_students():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    file = request.files.get('file')

    if not file:
        flash("Fadlan upload file CSV!", "danger")
        return redirect(url_for('main.all_students'))

    stream = io.StringIO(
        file.stream.read().decode("UTF8"),
        newline=None
    )

    reader = csv.DictReader(stream)

    imported_count = 0

    for row in reader:

        # FULL NAME REQUIRED
        full_name = row.get("Full Name", "").strip()
        if not full_name:
            continue

        # CLASS REQUIRED
        class_name = row.get("Class Name", "").strip()

        class_doc = mongo.db.classrooms.find_one({
            "class_name": class_name
        })

        if not class_doc:
            continue

        # SECTION OPTIONAL
        section_name = row.get("Section Name", "").strip()
        section_doc = None

        if section_name:
            section_doc = mongo.db.sections.find_one({
                "section_name": section_name
            })

        # 🔥 SHIFT (NEW)
        shift_name = row.get("Shift", "").strip()
        if not shift_name:
            shift_name = class_doc.get("shift_name")  # fallback

        # ROLE NO
        role_no = row.get("Role No", "").strip()
        if not role_no:
            role_no = generate_student_role_no()

        # PREVENT DUPLICATE ROLE NO
        existing_student = mongo.db.students.find_one({
            "role_no": role_no
        })

        if existing_student:
            role_no = generate_student_role_no()

        mongo.db.students.insert_one({
            "role_no": role_no,
            "full_name": full_name,

            "class_id": class_doc["_id"],
            "section_id": section_doc["_id"] if section_doc else None,

            # 🔥 SHIFT ADDED
            "shift_name": shift_name,

            "status": str(row.get("Status", "True")).lower() == "true",

            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        imported_count += 1

    flash(
        f"{imported_count} students imported successfully!",
        "success"
    )

    return redirect(url_for('main.all_students'))




@bp.route('/admin/students/delete-all', methods=['POST'])
@login_required
def delete_all_students():

    # =========================
    # SECURITY CHECK
    # =========================
    if current_user.role not in ["admin", "superadmin"]:
        return abort(403)

    try:
        # =========================
        # DELETE ALL STUDENTS
        # =========================
        result = mongo.db.students.delete_many({})

        deleted_count = result.deleted_count

        flash(f"Successfully deleted {deleted_count} students.", "success")

    except Exception as e:
        flash(f"Error deleting students: {str(e)}", "danger")

    return redirect(url_for('main.all_students'))



def to_objectid(value):
    if isinstance(value, ObjectId):
        return value

    try:
        return ObjectId(str(value))
    except Exception:
        return None


@bp.route("/admin/results-overview")
@login_required
def admin_results_overview():

    if current_user.role not in ["admin", "superadmin"]:
        abort(403)


    teacher_map = {}
    unique_teachers = set()

    total_students = 0
    total_results = 0


    assignments = mongo.db.teacher_assignments.find()


    for assignment in assignments:


        teacher_oid = to_objectid(assignment.get("teacher_id"))
        class_oid = to_objectid(assignment.get("class_id"))
        subject_oid = to_objectid(assignment.get("subject_id"))
        section_oid = to_objectid(assignment.get("section_id"))


        if not teacher_oid or not class_oid or not subject_oid:
            continue



        teacher = mongo.db.teachers.find_one({
            "_id": teacher_oid
        })


        classroom = mongo.db.classrooms.find_one({
            "_id": class_oid
        })


        subject = mongo.db.subjects.find_one({
            "_id": subject_oid
        })


        section = None

        if section_oid:
            section = mongo.db.sections.find_one({
                "_id": section_oid
            })


        if not teacher:
            continue



        teacher_key = str(teacher_oid)

        unique_teachers.add(teacher_key)



        if teacher_key not in teacher_map:

            teacher_map[teacher_key] = {

                "teacher_id": teacher_key,

                "teacher_name": teacher.get("full_name"),

                "total_classes":0,

                "total_students":0,

                "total_results":0,

                "classes":{}

            }



        # ======================
        # STUDENTS
        # ======================


        student_query = {

            "class_id":{
                "$in":[
                    class_oid,
                    str(class_oid)
                ]
            }

        }


        if section_oid:

            student_query["section_id"] = {

                "$in":[
                    section_oid,
                    str(section_oid)
                ]

            }



        students=list(
            mongo.db.students.find(
                student_query
            )
        )


        student_ids=[

            s["_id"]

            for s in students

        ]


        total_class_students=len(student_ids)



        # ======================
        # RESULTS
        # ======================


        result_count=len(

            mongo.db.results.distinct(

                "student_id",

                {

                "teacher_id":{
                    "$in":[
                        teacher_oid,
                        str(teacher_oid)
                    ]
                },

                "subject_id":{
                    "$in":[
                        subject_oid,
                        str(subject_oid)
                    ]
                },

                "student_id":{
                    "$in":
                    student_ids +
                    [
                        str(x)
                        for x in student_ids
                    ]
                }

                }

            )

        )



        pending=max(
            total_class_students-result_count,
            0
        )


        progress=0

        if total_class_students:

            progress=round(
                (result_count/total_class_students)*100,
                1
            )



        group_key=f"{class_oid}_{section_oid}"



        if group_key not in teacher_map[teacher_key]["classes"]:


            teacher_map[teacher_key]["classes"][group_key]={

                "class_id":str(class_oid),

                "class_name":
                classroom.get("class_name")
                if classroom else "N/A",


                "section_id":
                str(section_oid)
                if section_oid else None,


                "section_name":
                section.get("section_name")
                if section else "No Section",


                "subjects":[]

            }



            teacher_map[teacher_key]["total_classes"] +=1




        teacher_map[teacher_key]["classes"][group_key]["subjects"].append({

            "subject_id":str(subject_oid),

            "subject_name":
            subject.get("subject_name")
            if subject else "Unknown",

            "total_students":total_class_students,

            "submitted_results":result_count,

            "remaining_results":pending,

            "progress":progress

        })



        teacher_map[teacher_key]["total_students"] += total_class_students

        teacher_map[teacher_key]["total_results"] += result_count



        total_students += total_class_students

        total_results += result_count




    teachers=[]


    for t in teacher_map.values():

        t["classes"]=list(
            t["classes"].values()
        )

        teachers.append(t)



    return render_template(

        "backend/pages/components/results/admin_results_overview.html",

        teachers=teachers,

        stats={

            "total_teachers":len(unique_teachers),

            "total_classes":
            sum(
                x["total_classes"]
                for x in teachers
            ),

            "total_students":total_students,

            "total_results":total_results

        }

    )


@bp.route(
    "/admin-class-results/<teacher_id>/<class_id>/<subject_id>",
    defaults={"section_id": None}
)
@bp.route(
    "/admin-class-results/<teacher_id>/<class_id>/<subject_id>/<section_id>"
)
@login_required
def admin_class_results(
    teacher_id,
    class_id,
    subject_id,
    section_id=None
):

    # ============================
    # PERMISSION
    # ============================

    if current_user.role not in ["admin", "superadmin"]:
        abort(403)



    # ============================
    # CONVERT IDS
    # ============================

    teacher_obj = to_objectid(teacher_id)
    class_obj = to_objectid(class_id)
    subject_obj = to_objectid(subject_id)
    section_obj = to_objectid(section_id) if section_id else None


    if not teacher_obj or not class_obj or not subject_obj:
        abort(404)



    # ============================
    # FIND ASSIGNMENT
    # ============================


    assignment_query = {

        "teacher_id":{
            "$in":[
                teacher_obj,
                str(teacher_obj)
            ]
        },

        "class_id":{
            "$in":[
                class_obj,
                str(class_obj)
            ]
        },

        "subject_id":{
            "$in":[
                subject_obj,
                str(subject_obj)
            ]
        }

    }



    if section_obj:

        assignment_query["section_id"]={

            "$in":[
                section_obj,
                str(section_obj)
            ]

        }



    assignment = mongo.db.teacher_assignments.find_one(
        assignment_query
    )


    if not assignment:
        abort(404)



    # ============================
    # LOAD INFORMATION
    # ============================


    teacher = mongo.db.teachers.find_one({

        "_id":teacher_obj

    })


    classroom = mongo.db.classrooms.find_one({

        "_id":class_obj

    })


    subject = mongo.db.subjects.find_one({

        "_id":subject_obj

    })


    section=None


    if section_obj:

        section=mongo.db.sections.find_one({

            "_id":section_obj

        })



    if not teacher or not classroom or not subject:
        abort(404)




    # ============================
    # GET STUDENTS
    # ============================


    student_query={

        "class_id":{

            "$in":[

                class_obj,
                str(class_obj)

            ]

        }

    }



    if section_obj:

        student_query["section_id"]={

            "$in":[

                section_obj,
                str(section_obj)

            ]

        }



    students=list(

        mongo.db.students.find(
            student_query
        )
        .sort(
            "full_name",
            1
        )

    )



    # ============================
    # GET RESULTS
    # ============================


    student_ids=[]


    for student in students:

        student_ids.append(
            student["_id"]
        )

        student_ids.append(
            str(student["_id"])
        )



    db_results=list(

        mongo.db.results.find({

            "teacher_id":{

                "$in":[

                    teacher_obj,
                    str(teacher_obj)

                ]

            },


            "subject_id":{

                "$in":[

                    subject_obj,
                    str(subject_obj)

                ]

            },


            "student_id":{

                "$in":student_ids

            }

        })

    )




    # map results

    result_map={}


    for result in db_results:

        result_map[
            str(result.get("student_id"))
        ]=result





    # ============================
    # BUILD TABLE
    # ============================


    results=[]


    submitted_results=0

    pending_results=0

    total_score=0



    for student in students:


        student_key=str(
            student["_id"]
        )


        result=result_map.get(
            student_key
        )



        if result:


            score=result.get(
                "score",
                0
            )


            submitted_results +=1


            try:

                total_score += float(score)

            except:

                pass



            status="Submitted"



        else:


            score=None

            pending_results +=1

            status="Pending"




        results.append({

            "student_id":student_key,

            "role_no":
            student.get(
                "role_no",
                "-"
            ),

            "full_name":
            student.get(
                "full_name",
                "Unknown"
            ),

            "score":score,

            "status":status

        })





    # ============================
    # STATISTICS
    # ============================


    total_students=len(
        students
    )


    completion_percentage=0


    if total_students:

        completion_percentage=round(

            (
                submitted_results /
                total_students
            )
            *
            100,

            1

        )



    average_score=0


    if submitted_results:

        average_score=round(

            total_score /
            submitted_results,

            2

        )





    # ============================
    # DEBUG
    # ============================


    print("==============================")

    print(
        "Teacher:",
        teacher.get("full_name")
    )

    print(
        "Class:",
        classroom.get("class_name")
    )

    print(
        "Subject:",
        subject.get("subject_name")
    )

    print(
        "Section:",
        section.get("section_name")
        if section else "No Section"
    )

    print(
        "Students:",
        total_students
    )

    print(
        "Submitted:",
        submitted_results
    )

    print(
        "Pending:",
        pending_results
    )

    print("==============================")





    return render_template(

        "backend/pages/components/results/admin_class_results.html",

        teacher=teacher,

        classroom=classroom,

        subject=subject,

        section=section,

        results=results,


        total_students=total_students,

        submitted_results=submitted_results,

        pending_results=pending_results,

        completion_percentage=completion_percentage,

        average_score=average_score

    )


@bp.route("/admin/teacher-progress-report")
@login_required
def admin_teacher_progress_report():

    if current_user.role not in ["admin", "superadmin"]:
        abort(403)



    teacher_data = {}

    total_students = 0
    total_submitted = 0



    assignments = mongo.db.teacher_assignments.find()



    for assignment in assignments:


        teacher_id = to_objectid(
            assignment.get("teacher_id")
        )

        class_id = to_objectid(
            assignment.get("class_id")
        )

        subject_id = to_objectid(
            assignment.get("subject_id")
        )

        section_id = to_objectid(
            assignment.get("section_id")
        )


        if not teacher_id or not class_id or not subject_id:
            continue



        teacher = mongo.db.teachers.find_one({
            "_id": teacher_id
        })


        classroom = mongo.db.classrooms.find_one({
            "_id": class_id
        })


        subject = mongo.db.subjects.find_one({
            "_id": subject_id
        })


        section = None

        if section_id:

            section = mongo.db.sections.find_one({
                "_id": section_id
            })



        if not teacher:
            continue



        teacher_key = str(teacher_id)



        if teacher_key not in teacher_data:

            teacher_data[teacher_key]={

                "teacher_id":teacher_key,

                "teacher_name":
                teacher.get("full_name"),

                "total_students":0,

                "total_submitted":0,

                "total_pending":0,

                "classes":[]

            }





        # ======================
        # STUDENTS
        # ======================


        student_query={

            "class_id":{

                "$in":[
                    class_id,
                    str(class_id)
                ]

            }

        }



        if section_id:

            student_query["section_id"]={

                "$in":[
                    section_id,
                    str(section_id)
                ]

            }



        students=list(

            mongo.db.students.find(
                student_query
            )

        )



        student_ids=[

            s["_id"]

            for s in students

        ]



        total=len(student_ids)



        # ======================
        # RESULTS
        # ======================


        submitted=len(

            mongo.db.results.distinct(

                "student_id",

                {

                "teacher_id":{

                    "$in":[
                        teacher_id,
                        str(teacher_id)
                    ]

                },

                "subject_id":{

                    "$in":[
                        subject_id,
                        str(subject_id)
                    ]

                },

                "student_id":{

                    "$in":
                    student_ids +
                    [
                        str(x)
                        for x in student_ids
                    ]

                }

                }

            )

        )



        pending=max(
            total-submitted,
            0
        )



        progress=0

        if total:

            progress=round(
                (submitted/total)*100,
                1
            )





        teacher_data[teacher_key]["classes"].append({

            "class_id":str(class_id),

            "class_name":
            classroom.get("class_name")
            if classroom else "N/A",


            "section_id":
            str(section_id)
            if section_id else None,


            "section_name":
            section.get("section_name")
            if section else "No Section",


            "subject_id":
            str(subject_id),


            "subject_name":
            subject.get("subject_name")
            if subject else "Unknown",


            "students":total,

            "submitted":submitted,

            "pending":pending,

            "progress":progress

        })



        teacher_data[teacher_key]["total_students"] += total

        teacher_data[teacher_key]["total_submitted"] += submitted

        teacher_data[teacher_key]["total_pending"] += pending



        total_students += total

        total_submitted += submitted





    # ======================
    # SORT SUBJECTS
    # ======================

    report=[]


    for teacher in teacher_data.values():


        teacher["classes"].sort(

            key=lambda x:
            (
                x["progress"],
                x["submitted"]
            ),

            reverse=True

        )



        teacher["teacher_progress"]=0


        if teacher["total_students"]:

            teacher["teacher_progress"]=round(

                (
                    teacher["total_submitted"]
                    /
                    teacher["total_students"]

                )
                *
                100,

                1

            )


        report.append(teacher)





    # ======================
    # SORT TEACHERS
    # ======================

    report.sort(

        key=lambda x:
        (

            x["total_submitted"],

            x["teacher_progress"]

        ),

        reverse=True

    )




    return render_template(

        "backend/pages/components/results/admin_teacher_progress_report.html",

        report=report,


        stats={

            "teachers":len(report),

            "students":total_students,

            "submitted":total_submitted

        }

    )


@bp.route("/admin/class-progress-report")
@login_required
def admin_class_progress_report():

    if current_user.role not in ["admin", "superadmin"]:
        abort(403)

    assignments = list(mongo.db.teacher_assignments.find())

    report = {}
    total_classes = 0
    total_students = 0
    total_submitted = 0
    total_pending = 0

    for assignment in assignments:

        teacher_id = to_objectid(assignment.get("teacher_id"))
        class_id = to_objectid(assignment.get("class_id"))
        subject_id = to_objectid(assignment.get("subject_id"))
        section_id = to_objectid(assignment.get("section_id"))

        if not teacher_id or not class_id or not subject_id:
            continue

        teacher = mongo.db.teachers.find_one({"_id": teacher_id})
        classroom = mongo.db.classrooms.find_one({"_id": class_id})
        subject = mongo.db.subjects.find_one({"_id": subject_id})

        section = None
        if section_id:
            section = mongo.db.sections.find_one({"_id": section_id})

        if not classroom:
            continue

        # ==========================
        # REAL STUDENTS
        # ==========================

        student_query = {
            "class_id": {
                "$in": [
                    class_id,
                    str(class_id)
                ]
            }
        }

        if section_id:
            student_query["section_id"] = {
                "$in": [
                    section_id,
                    str(section_id)
                ]
            }

        # Haddii aad leedahay status/is_active ku dar halkan
        # student_query["status"] = True

        students = list(
            mongo.db.students.find(
                student_query,
                {
                    "_id": 1
                }
            )
        )

        student_ids = []

        for student in students:
            student_ids.append(student["_id"])
            student_ids.append(str(student["_id"]))

        total_class_students = len(students)

        # ==========================
        # RESULTS
        # ==========================

        submitted = len(

            mongo.db.results.distinct(

                "student_id",

                {

                    "teacher_id": {
                        "$in": [
                            teacher_id,
                            str(teacher_id)
                        ]
                    },

                    "subject_id": {
                        "$in": [
                            subject_id,
                            str(subject_id)
                        ]
                    },

                    "student_id": {
                        "$in": student_ids
                    }

                }

            )

        )

        pending = max(total_class_students - submitted, 0)

        progress = (
            round(submitted * 100 / total_class_students, 1)
            if total_class_students
            else 0
        )

        group_key = f"{class_id}_{section_id if section_id else 'nosection'}"

        if group_key not in report:

            report[group_key] = {

                "class_id": str(class_id),

                "class_name": classroom.get(
                    "class_name",
                    "N/A"
                ),

                "section_id": (
                    str(section_id)
                    if section_id
                    else None
                ),

                "section_name": (
                    section.get("section_name")
                    if section
                    else "No Section"
                ),

                "students": total_class_students,

                "submitted": 0,

                "pending": 0,

                "subjects": []

            }

            total_classes += 1

        report[group_key]["subjects"].append({

            "teacher_id": str(teacher_id),

            "teacher_name": (
                teacher.get("full_name")
                if teacher
                else "Unknown"
            ),

            "subject_id": str(subject_id),

            "subject_name": (
                subject.get("subject_name")
                if subject
                else "Unknown"
            ),

            "students": total_class_students,

            "submitted": submitted,

            "pending": pending,

            "progress": progress

        })

        report[group_key]["submitted"] += submitted
        report[group_key]["pending"] += pending

        total_students += total_class_students
        total_submitted += submitted
        total_pending += pending

    report = sorted(
        report.values(),
        key=lambda item: (
            item["class_name"],
            item["section_name"]
        )
    )

    return render_template(
        "backend/pages/components/results/admin_class_progress_report.html",
        report=report,
        stats={
            "classes": total_classes,
            "students": total_students,
            "submitted": total_submitted,
            "pending": total_pending
        }
    )





@bp.route('/edit-result/<student_id>/<subject_id>', methods=['GET', 'POST'])
@login_required
def edit_result(student_id, subject_id):

    # =========================
    # VALIDATE IDS
    # =========================
    try:
        student_obj = ObjectId(student_id)
        subject_obj = ObjectId(subject_id)
    except:
        return abort(404)

    # =========================
    # GET STUDENT
    # =========================
    student = mongo.db.students.find_one({"_id": student_obj})
    subject = mongo.db.subjects.find_one({"_id": subject_obj})

    if not student or not subject:
        return abort(404)

    # =========================
    # FIND EXISTING RESULT
    # =========================
    result = mongo.db.results.find_one({
        "student_id": student_obj,
        "subject_id": subject_obj
    })

    # =========================
    # POST (UPDATE / CREATE)
    # =========================
    if request.method == 'POST':

        score = request.form.get("score")

        if score is None or score == "":
            flash("Score is required!", "danger")
            return redirect(request.url)

        try:
            score_value = float(score)
        except:
            flash("Invalid score value!", "danger")
            return redirect(request.url)

        if result:

            # UPDATE EXISTING
            mongo.db.results.update_one(
                {"_id": result["_id"]},
                {
                    "$set": {
                        "score": score_value,
                        "updated_at": datetime.utcnow()
                    }
                }
            )

            flash("Result updated successfully!", "success")

        else:

            # CREATE NEW RESULT
            mongo.db.results.insert_one({
                "student_id": student_obj,
                "subject_id": subject_obj,
                "teacher_id": None,  # optional haddii aad rabto later fill
                "score": score_value,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })

            flash("Result created successfully!", "success")

        return redirect(url_for('main.admin_results_overview'))

    # =========================
    # GET VIEW
    # =========================
    return render_template(
        "backend/pages/components/results/edit_result.html",
        student=student,
        subject=subject,
        result=result
    )



@bp.route('/delete-result/<student_id>/<subject_id>', methods=['POST'])
@login_required
def delete_result(student_id, subject_id):
    mongo.db.results.delete_one({
        "student_id": ObjectId(student_id),
        "subject_id": ObjectId(subject_id)
    })

    flash("Result deleted successfully", "success")
    return redirect(request.referrer)





@bp.route('/export-class-results/<teacher_id>/<class_id>/<subject_id>',defaults={'section_id': None})
@bp.route('/export-class-results/<teacher_id>/<class_id>/<subject_id>/<section_id>')
@login_required
def export_class_results(
    teacher_id,
    class_id,
    subject_id,
    section_id=None
):

    if current_user.role not in ["admin", "superadmin"]:
        return abort(403)

    try:
        teacher_obj = ObjectId(teacher_id)
        class_obj = ObjectId(class_id)
        subject_obj = ObjectId(subject_id)

        section_obj = (
            ObjectId(section_id)
            if section_id else None
        )

    except:
        return abort(404)

    # =========================
    # META DATA
    # =========================

    classroom = mongo.db.classrooms.find_one({
        "_id": class_obj
    })

    subject = mongo.db.subjects.find_one({
        "_id": subject_obj
    })

    section = None

    if section_obj:
        section = mongo.db.sections.find_one({
            "_id": section_obj
        })

    class_name = (
        classroom.get("class_name")
        if classroom else "Class"
    )

    subject_name = (
        subject.get("subject_name")
        if subject else "Subject"
    )

    section_name = (
        section.get("section_name")
        if section else "All Sections"
    )

    # =========================
    # STUDENTS QUERY
    # =========================

    student_query = {
        "class_id": class_obj
    }

    # ONLY FILTER SECTION IF EXISTS
    if section_obj:
        student_query["section_id"] = section_obj

    students = list(
        mongo.db.students.find(student_query)
        .sort("full_name", 1)
    )

    # =========================
    # CSV GENERATOR
    # =========================

    def generate():

        yield f"Class,{class_name}\n"
        yield f"Section,{section_name}\n"
        yield f"Subject,{subject_name}\n"
        yield f"Generated,{datetime.utcnow()}\n"
        yield "\n"

        yield "Role No,Student Name,Score,Status\n"

        for student in students:

            result = mongo.db.results.find_one({

                "student_id": student["_id"],
                "teacher_id": teacher_obj,
                "subject_id": subject_obj

            })

            if result:

                score = result.get("score", "")
                status = "Submitted"

            else:

                score = ""
                status = "Pending"

            role_no = student.get("role_no", "")
            full_name = student.get("full_name", "")

            yield (
                f'"{role_no}","{full_name}",'
                f'"{score}","{status}"\n'
            )

    # =========================
    # FILE NAME
    # =========================

    if section_obj:

        filename = (
            f"{class_name}_"
            f"{section_name}_"
            f"{subject_name}_results.csv"
        )

    else:

        filename = (
            f"{class_name}_"
            f"ALL_SECTIONS_"
            f"{subject_name}_results.csv"
        )

    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            f'attachment; filename="{filename}"'
        }
    )



@bp.route('/admin/results-report')
@login_required
def admin_results_report():

    if current_user.role not in ['admin', 'superadmin']:
        return abort(403)


    classes = list(
        mongo.db.classrooms.find().sort("class_name", 1)
    )


    class_id = request.args.get("class_id", "").strip()
    section_id = request.args.get("section_id", "").strip()


    report = []
    subjects = []
    sections = []

    selected_class = None
    selected_section = None



    # =========================
    # CLASS SELECTED
    # =========================
    if class_id:


        try:
            class_obj = ObjectId(class_id)

        except Exception:
            return abort(404)



        selected_class = mongo.db.classrooms.find_one({
            "_id": class_obj
        })


        if not selected_class:
            return abort(404)



        # =========================
        # GET SECTIONS FROM STUDENTS
        # =========================

        section_ids = mongo.db.students.distinct(
            "section_id",
            {
                "class_id": class_obj,
                "section_id": {
                    "$exists": True,
                    "$ne": None
                }
            }
        )


        if section_ids:

            sections = list(
                mongo.db.sections.find({
                    "_id": {
                        "$in": section_ids
                    }
                }).sort(
                    "section_name",
                    1
                )
            )



        # =========================
        # STUDENTS FILTER
        # =========================

        student_query = {
            "class_id": class_obj
        }


        section_obj = None



        if section_id:


            try:

                section_obj = ObjectId(section_id)


                selected_section = mongo.db.sections.find_one({
                    "_id": section_obj
                })


                if selected_section:

                    student_query["section_id"] = section_obj



            except Exception:

                section_obj = None




        students = list(
            mongo.db.students.find(
                student_query
            ).sort(
                "role_no",
                1
            )
        )



        # =========================
        # GET SUBJECTS
        # CLASS BASED ONLY
        # =========================

        assignments = list(
            mongo.db.teacher_assignments.find({
                "class_id": class_obj
            })
        )



        subject_ids = list(set(
            a.get("subject_id")
            for a in assignments
            if a.get("subject_id")
        ))



        if subject_ids:


            subjects = list(
                mongo.db.subjects.find({
                    "_id": {
                        "$in": subject_ids
                    }
                })
            )


            subjects.sort(
                key=lambda x:
                x.get(
                    "subject_name",
                    ""
                ).lower()
            )




        # =========================
        # BUILD REPORT
        # =========================

        for student in students:


            row = {

                "student_id": str(student["_id"]),

                "role_no": student.get(
                    "role_no",
                    ""
                ),

                "full_name": student.get(
                    "full_name",
                    ""
                ),

                "scores": []

            }



            for subject in subjects:


                result = mongo.db.results.find_one({

                    "student_id": student["_id"],

                    "subject_id": subject["_id"]

                })


                row["scores"].append(

                    result.get(
                        "score",
                        ""
                    )

                    if result

                    else ""

                )



            report.append(row)



    return render_template(

        "backend/pages/components/results/admin_results_report.html",

        classes=classes,

        sections=sections,

        subjects=subjects,

        report=report,

        selected_class=selected_class,

        selected_section=selected_section

    )


@bp.route('/export-results-report')
@login_required
def export_results_report():

    if current_user.role not in ['admin', 'superadmin']:
        return abort(403)


    class_id = request.args.get("class_id", "").strip()
    section_id = request.args.get("section_id", "").strip()


    if not class_id:
        return abort(404)


    try:
        class_obj = ObjectId(class_id)

    except Exception:
        return abort(404)



    section_obj = None


    if section_id:

        try:
            section_obj = ObjectId(section_id)

        except Exception:
            section_obj = None



    classroom = mongo.db.classrooms.find_one({
        "_id": class_obj
    })


    if not classroom:
        return abort(404)



    section = None


    if section_obj:

        section = mongo.db.sections.find_one({
            "_id": section_obj
        })



    # =========================
    # STUDENTS
    # CLASS + OPTIONAL SECTION
    # =========================

    student_query = {

        "class_id": class_obj

    }


    if section_obj:

        student_query["section_id"] = section_obj



    students = list(

        mongo.db.students.find(
            student_query
        ).sort(
            "role_no",
            1
        )

    )



    # =========================
    # SUBJECTS
    # CLASS BASED ONLY
    # =========================

    assignments = list(

        mongo.db.teacher_assignments.find({

            "class_id": class_obj

        })

    )



    subject_ids = []


    for assignment in assignments:


        sid = assignment.get(
            "subject_id"
        )


        if sid and sid not in subject_ids:

            subject_ids.append(sid)




    subjects = []


    if subject_ids:

        subjects = list(

            mongo.db.subjects.find({

                "_id": {

                    "$in": subject_ids

                }

            })

        )



        subjects.sort(

            key=lambda x:
            x.get(
                "subject_name",
                ""
            ).lower()

        )



    # =========================
    # CSV GENERATOR
    # =========================

    def generate():


        headers = [

            "Role No",

            "Student Name"

        ]



        for subject in subjects:

            headers.append(

                subject.get(
                    "subject_name",
                    ""
                )

            )



        yield ",".join(headers) + "\n"




        for student in students:


            row = [

                str(
                    student.get(
                        "role_no",
                        ""
                    )
                ),

                '"' + str(

                    student.get(
                        "full_name",
                        ""
                    )

                ) + '"'

            ]



            for subject in subjects:


                result = mongo.db.results.find_one({

                    "student_id":
                    student["_id"],


                    "subject_id":
                    subject["_id"]

                })



                score = ""


                if result:

                    score = str(

                        result.get(
                            "score",
                            ""
                        )

                    )



                row.append(score)



            yield ",".join(row) + "\n"




    # =========================
    # FILE NAME
    # =========================

    filename = classroom.get(
        "class_name",
        "Results"
    )


    if section:

        filename += "_" + section.get(
            "section_name",
            ""
        )


    filename += "_Report.csv"



    return Response(

        generate(),

        mimetype="text/csv",

        headers={

            "Content-Disposition":

            f"attachment; filename={filename}"

        }

    )


@bp.route("/all-student-results")
@login_required
def all_student_results():

    if current_user.role not in ["superadmin", "admin"]:
        return abort(403)


    results = []


    for r in mongo.db.student_results.find().sort(
        "created_at",
        -1
    ):


        # ==============================
        # STUDENT
        # ==============================

        student = None

        if r.get("student_id"):

            try:
                student = mongo.db.students.find_one({
                    "_id": ObjectId(r["student_id"])
                })
            except:
                pass



        # ==============================
        # SUBJECT
        # ==============================

        subject = None

        if r.get("subject_id"):

            try:
                subject = mongo.db.subjects.find_one({
                    "_id": ObjectId(r["subject_id"])
                })
            except:
                pass



        class_name = "N/A"
        section_name = "N/A"

        teacher_name = "No Teacher"


        class_id = None
        section_id = None



        # ==============================
        # STUDENT CLASS
        # ==============================

        if student:


            class_id = student.get("class_id")

            section_id = student.get("section_id")



            classroom = None


            if class_id:

                try:

                    classroom = mongo.db.classrooms.find_one({
                        "_id": ObjectId(class_id)
                    })

                except:

                    pass



            if classroom:

                class_name = classroom.get(
                    "class_name",
                    "N/A"
                )



            # SECTION OPTIONAL

            if section_id:

                try:

                    section = mongo.db.sections.find_one({
                        "_id": ObjectId(section_id)
                    })

                    if section:

                        section_name = section.get(
                            "section_name",
                            "N/A"
                        )

                except:

                    pass





        # ==============================
        # FIND TEACHER
        # ==============================


        if subject and class_name != "N/A":



            # Get all possible classes with same name

            classes = list(
                mongo.db.classrooms.find({
                    "class_name": class_name
                })
            )



            class_ids = [
                c["_id"]
                for c in classes
            ]



            assignment = None



            # With section first

            if section_id:


                assignment = mongo.db.teacher_assignments.find_one({

                    "class_id":{
                        "$in": class_ids
                    },

                    "section_id":
                    ObjectId(section_id),

                    "subject_id":
                    subject["_id"]

                })




            # Without section

            if not assignment:


                assignment = mongo.db.teacher_assignments.find_one({

                    "class_id":{
                        "$in": class_ids
                    },

                    "subject_id":
                    subject["_id"]

                })





            if assignment:


                teacher_id = assignment.get(
                    "teacher_id"
                )



                if teacher_id:


                    teacher = mongo.db.teachers.find_one({

                        "_id": teacher_id

                    })


                    if teacher:

                        teacher_name = teacher.get(
                            "full_name",
                            "No Teacher"
                        )






        # ==============================
        # RESULT DATA
        # ==============================

        results.append({


            "id":
            str(r["_id"]),


            "role_no":

            student.get("role_no")
            if student else "N/A",


            "student_name":

            student.get("full_name")
            if student else "N/A",


            "class_name":

            class_name,


            "section_name":

            section_name,


            "subject_name":

            subject.get("subject_name")
            if subject else "N/A",


            "teacher_name":

            teacher_name,


            "exam_type":

            r.get("exam_type","N/A"),


            "score":

            r.get("score",0),


            "exam_date":

            r.get("exam_date","N/A"),


            "created_at":

            r.get("created_at")

        })



    return render_template(

        "backend/pages/components/results/all_student_results.html",

        results=results

    )


@bp.route('/export-student-results')
@login_required
def export_student_results():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    output = io.StringIO()
    writer = csv.writer(output)

    # HEADER
    writer.writerow([
        "Student ID",
        "Student Name",
        "Subject",
        "Exam Type",
        "Score",
        "Exam Date"
    ])

    results = list(mongo.db.student_results.find())

    # --------------------------------------------------
    # IF EMPTY -> DOWNLOAD SAMPLE TEMPLATE
    # --------------------------------------------------
    if len(results) == 0:

        writer.writerow([
            "STD-0001",
            "Ahmed Ali",
            "English",
            "monthly_1",
            "8",
            "2026-01-10"
        ])

        writer.writerow([
            "STD-0001",
            "Ahmed Ali",
            "English",
            "midterm",
            "22",
            "2026-02-15"
        ])

        writer.writerow([
            "STD-0001",
            "Ahmed Ali",
            "English",
            "monthly_2",
            "7",
            "2026-03-20"
        ])

        writer.writerow([
            "STD-0001",
            "Ahmed Ali",
            "English",
            "final",
            "40",
            "2026-05-01"
        ])

        writer.writerow([
            "STD-0001",
            "Ahmed Ali",
            "Technology",
            "monthly_1",
            "9",
            "2026-01-10"
        ])

        writer.writerow([
            "STD-0001",
            "Ahmed Ali",
            "Technology",
            "midterm",
            "25",
            "2026-02-15"
        ])

        writer.writerow([
            "STD-0001",
            "Ahmed Ali",
            "Technology",
            "monthly_2",
            "6",
            "2026-03-20"
        ])

        writer.writerow([
            "STD-0001",
            "Ahmed Ali",
            "Technology",
            "final",
            "42",
            "2026-05-01"
        ])

    # --------------------------------------------------
    # EXPORT REAL DATA
    # --------------------------------------------------
    else:

        for r in results:

            student = mongo.db.students.find_one({
                "_id": ObjectId(r["student_id"])
            })

            subject = mongo.db.subjects.find_one({
                "_id": ObjectId(r["subject_id"])
            })

            writer.writerow([

                student.get("role_no") if student else "",

                student.get("full_name") if student else "",

                subject.get("subject_name") if subject else "",

                r.get("exam_type"),

                r.get("score"),

                r.get("exam_date")

            ])

    output.seek(0)

    return Response(
        output,
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=student_results_template.csv"
        }
    )



@bp.route('/import-student-results', methods=['POST'])
@login_required
def import_student_results():

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    file = request.files.get("file")

    if not file:
        flash("Please select a CSV file.", "danger")
        return redirect(url_for("main.all_student_results"))

    stream = io.StringIO(
        file.stream.read().decode("UTF8"),
        newline=None
    )

    reader = csv.DictReader(stream)

    imported = 0
    skipped = 0

    for row in reader:

        student_role = row.get("Student ID", "").strip()
        subject_name = row.get("Subject", "").strip()
        exam_type = row.get("Exam Type", "").strip().lower()
        score = row.get("Score", "").strip()
        exam_date = row.get("Exam Date", "").strip()

        # Required Fields
        if not student_role or not subject_name or not exam_type:
            skipped += 1
            continue

        # Student
        student = mongo.db.students.find_one({
            "role_no": student_role
        })

        if not student:
            skipped += 1
            continue

        # Subject
        subject = mongo.db.subjects.find_one({
            "subject_name": subject_name
        })

        if not subject:
            skipped += 1
            continue

        # Exam Type Validation
        valid_exam_types = [
            "monthly_1",
            "midterm",
            "monthly_2",
            "final"
        ]

        if exam_type not in valid_exam_types:
            skipped += 1
            continue

        # Teacher (optional)
        assignment = mongo.db.teacher_assignments.find_one({
            "class_id": str(student.get("class_id")),
            "section_id": str(student.get("section_id")),
            "subject_id": str(subject["_id"])
        })

        teacher_id = None

        if assignment:
            teacher_id = assignment.get("teacher_id")

        # Prevent Duplicate Result
        exists = mongo.db.student_results.find_one({
            "student_id": str(student["_id"]),
            "subject_id": str(subject["_id"]),
            "exam_type": exam_type
        })

        if exists:
            skipped += 1
            continue

        try:
            score = float(score)
        except:
            score = 0

        mongo.db.student_results.insert_one({

            "student_id": str(student["_id"]),

            "subject_id": str(subject["_id"]),

            "teacher_id": teacher_id,

            "exam_type": exam_type,

            "score": score,

            "exam_date": exam_date,

            "created_at": datetime.utcnow(),

            "updated_at": datetime.utcnow()

        })

        imported += 1

    flash(
        f"{imported} results imported successfully. {skipped} rows skipped.",
        "success"
    )

    return redirect(url_for("main.all_student_results"))



@bp.route('/delete-student-result/<result_id>', methods=['POST'])
@login_required
def delete_student_result(result_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    result = mongo.db.student_results.find_one({
        "_id": ObjectId(result_id)
    })

    if not result:
        flash("Student result not found.", "danger")
        return redirect(url_for("main.all_student_results"))

    mongo.db.student_results.delete_one({
        "_id": ObjectId(result_id)
    })

    flash("Student result deleted successfully.", "success")

    return redirect(url_for("main.all_student_results"))



@bp.route('/edit-student-result/<result_id>', methods=['GET', 'POST'])
@login_required
def edit_student_result(result_id):

    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    result = mongo.db.student_results.find_one({
        "_id": ObjectId(result_id)
    })

    if not result:
        flash("Student result not found.", "danger")
        return redirect(url_for("main.all_student_results"))

    if request.method == "POST":

        subject_id = request.form.get("subject_id")
        exam_type = request.form.get("exam_type")
        score = request.form.get("score")
        exam_date = request.form.get("exam_date")

        # Validation
        if not subject_id or not exam_type:
            flash("Please fill all required fields.", "danger")
            return redirect(request.url)

        try:
            score = float(score)
        except:
            score = 0

        # Duplicate check
        duplicate = mongo.db.student_results.find_one({
            "_id": {"$ne": ObjectId(result_id)},
            "student_id": result["student_id"],
            "subject_id": subject_id,
            "exam_type": exam_type
        })

        if duplicate:
            flash(
                "This student already has this exam result for the selected subject.",
                "warning"
            )
            return redirect(request.url)

        # Find Teacher Assignment
        student = mongo.db.students.find_one({
            "_id": ObjectId(result["student_id"])
        })

        teacher_id = result.get("teacher_id")

        if student:

            assignment = mongo.db.teacher_assignments.find_one({
                "class_id": str(student.get("class_id")),
                "section_id": str(student.get("section_id")),
                "subject_id": subject_id
            })

            if assignment:
                teacher_id = assignment.get("teacher_id")

        mongo.db.student_results.update_one(
            {"_id": ObjectId(result_id)},
            {
                "$set": {

                    "subject_id": subject_id,

                    "teacher_id": teacher_id,

                    "exam_type": exam_type,

                    "score": score,

                    "exam_date": exam_date,

                    "updated_at": datetime.utcnow()

                }
            }
        )

        flash("Student result updated successfully.", "success")

        return redirect(url_for("main.all_student_results"))

    # -----------------------------
    # GET DATA
    # -----------------------------

    student = mongo.db.students.find_one({
        "_id": ObjectId(result["student_id"])
    })

    subjects = list(
        mongo.db.subjects.find().sort("subject_name", 1)
    )

    return render_template(

        "backend/pages/components/results/edit_student_result.html",

        result=result,

        student=student,

        subjects=subjects

    )


@bp.route('/delete-all-student-results', methods=['POST'])
@login_required
def delete_all_student_results():

    # Only Super Admin & Admin
    if current_user.role not in ['superadmin', 'admin']:
        return abort(403)

    try:

        result = mongo.db.student_results.delete_many({})

        flash(
            f"{result.deleted_count} student result(s) deleted successfully!",
            "success"
        )

    except Exception as e:

        flash(
            f"Error deleting student results: {str(e)}",
            "danger"
        )

    return redirect(url_for("main.all_student_results"))



#---------------------------------------------------
#---- Route: 70 | Dashboard - Backend Template -----
#---------------------------------------------------
@bp.route("/logout")
def logout():
    if current_user.is_authenticated:

        # Log the logout action
       

        # Only log out from Flask-Login
        logout_user()

        # ✅ Do NOT clear session or delete DB session yet
        # session.clear()  <-- remove this
        # db.session.delete(user_session)  <-- remove this

        # Flash message
        flash("You have been logged out! Your session record remains for inspection.", "success")

    # Clear remember_token cookie to prevent auto-login
    resp = make_response(redirect(url_for("main.index")))
    resp.set_cookie("remember_token", "", expires=0)
    return resp


