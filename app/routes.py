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

from bson import ObjectId
from flask import Blueprint, Response, abort, current_app, flash, make_response, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from app import ALLOWED_EXTENSIONS
from app.extensions import mongo
from datetime import datetime, timedelta

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

from datetime import datetime, timedelta

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
        result_map=result_map
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
        role = UserRole.superadmin.value if user_count == 0 else UserRole.user.value

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

        if not class_name:
            flash("Fadlan geli magaca fasalka!", "danger")
            return redirect(url_for('main.add_class'))

        existing_class = mongo.db.classrooms.find_one({
            "class_name": class_name
        })

        if existing_class:
            flash("Fasalkan hore ayuu u jiraa!", "warning")
            return redirect(url_for('main.add_class'))

        mongo.db.classrooms.insert_one({
            "class_name": class_name,
            "created_at": datetime.utcnow()
        })

        flash(
            f"Fasalka {class_name} si guul leh ayaa loo diiwaangeliyey!",
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

        if not class_name:
            flash("Class name waa mandatory!", "danger")
            return redirect(url_for('main.edit_class', class_id=class_id))

        mongo.db.classrooms.update_one(
            {"_id": ObjectId(class_id)},
            {
                "$set": {
                    "class_name": class_name
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




@bp.route('/add-result-deadline', methods=['POST'])
@login_required
def add_result_deadline():

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

    flash("Deadline assigned successfully!", "success")
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

    return render_template(
        "backend/pages/components/teachers/all_teacher_assignments.html",
        assignments=data
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

        full_name = request.form.get('full_name')
        class_id = request.form.get('class_id')
        section_id = request.form.get('section_id')  # optional
        status = request.form.get('status')

        # Section ma aha required
        if not full_name or not class_id:
            flash("Fadlan geli magaca ardayga iyo fasalka!", "danger")
            return redirect(url_for('main.add_student'))

        role_no = generate_student_role_no()

        student_data = {
            "role_no": role_no,
            "full_name": full_name,
            "class_id": ObjectId(class_id),
            "section_id": ObjectId(section_id) if section_id else None,
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

        # Get class name
        class_name = None
        if s.get("class_id"):
            c = mongo.db.classrooms.find_one({"_id": ObjectId(s["class_id"])})
            class_name = c["class_name"] if c else "N/A"

        # Get section name
        section_name = None
        if s.get("section_id"):
            sec = mongo.db.sections.find_one({"_id": ObjectId(s["section_id"])})
            section_name = sec["section_name"] if sec else "N/A"

        students.append({
            "id": str(s["_id"]),
            "role_no": s.get("role_no"),
            "full_name": s.get("full_name"),
            "class_name": class_name,
            "section_name": section_name,
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

        full_name = request.form.get('full_name')
        class_id = request.form.get('class_id')
        section_id = request.form.get('section_id')
        status = request.form.get('status')

        if not full_name:
            flash("Magaca ardayga waa mandatory!", "danger")
            return redirect(
                url_for(
                    'main.edit_student',
                    student_id=student_id
                )
            )

        update_data = {
            "full_name": full_name,
            "class_id": ObjectId(class_id),
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

        flash(
            "Arday si guul leh ayaa loo update gareeyay!",
            "success"
        )

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

    # HEADER (use names instead of IDs)
    writer.writerow([
        "Role No",
        "Full Name",
        "Class Name",
        "Section Name",
        "Status",
        "Created At"
    ])

    for s in students:

        # GET CLASS NAME
        class_name = ""
        if s.get("class_id"):
            c = mongo.db.classrooms.find_one({"_id": ObjectId(s["class_id"])})
            class_name = c["class_name"] if c else ""

        # GET SECTION NAME
        section_name = ""
        if s.get("section_id"):
            sec = mongo.db.sections.find_one({"_id": ObjectId(s["section_id"])})
            section_name = sec["section_name"] if sec else ""

        writer.writerow([
            s.get("role_no"),
            s.get("full_name"),
            class_name,
            section_name,
            s.get("status"),
            s.get("created_at")
        ])

    output.seek(0)

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=students.csv"}
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

        # AUTO GENERATE ROLE NO
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

            # OPTIONAL SECTION
            "section_id": (
                section_doc["_id"]
                if section_doc
                else None
            ),

            "status": str(
                row.get("Status", "True")
            ).lower() == "true",

            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        imported_count += 1

    flash(
        f"{imported_count} students imported successfully!",
        "success"
    )

    return redirect(url_for('main.all_students'))






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


