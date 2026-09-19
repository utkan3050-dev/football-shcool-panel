from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, send_from_directory
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os
import csv
import io
import zipfile


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "local-development-secret"
)

DB_NAME = os.environ.get(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "school.db")
)

SUPERADMIN_USERNAME = os.environ.get(
    "SUPERADMIN_USERNAME",
    "admin"
)

SUPERADMIN_PASSWORD = os.environ.get(
    "SUPERADMIN_PASSWORD",
    "1234"
)


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()

    # FUTBOL OKULLARI
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            finance_privacy_enabled INTEGER DEFAULT 0,
            finance_pin_hash TEXT,
            created_at TEXT
        )
    """)

    # ÖĞRENCİLER
    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            birth_year INTEGER NOT NULL,
            class_group TEXT,
            parent_name TEXT,
            phone TEXT,
            monthly_fee REAL DEFAULT 0,
            active INTEGER DEFAULT 1,
            notes TEXT,
            created_at TEXT,
            FOREIGN KEY (school_id)
                REFERENCES schools(id)
                ON DELETE CASCADE
        )
    """)

    # AYLIK ÖDEMELER
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            amount REAL DEFAULT 0,
            paid INTEGER DEFAULT 0,
            paid_at TEXT,
            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE,
            UNIQUE(student_id, year, month)
        )
    """)

    # YOKLAMA
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            attendance_date TEXT NOT NULL,
            present INTEGER DEFAULT 0,
            created_at TEXT,
            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE,
            UNIQUE(student_id, attendance_date)
        )
    """)

    # GİDERLER
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            expense_date TEXT NOT NULL,
            created_at TEXT,
            FOREIGN KEY (school_id)
                REFERENCES schools(id)
                ON DELETE CASCADE
        )
    """)

    # MEVCUT VERİTABANLARI İÇİN SÜTUN GÖÇÜ
    student_columns = [
        row[1]
        for row in conn.execute("PRAGMA table_info(students)").fetchall()
    ]

    if "class_group" not in student_columns:
        conn.execute("ALTER TABLE students ADD COLUMN class_group TEXT")

    school_columns = [
        row[1]
        for row in conn.execute("PRAGMA table_info(schools)").fetchall()
    ]

    if "finance_privacy_enabled" not in school_columns:
        conn.execute(
            "ALTER TABLE schools ADD COLUMN finance_privacy_enabled INTEGER DEFAULT 0"
        )

    if "finance_pin_hash" not in school_columns:
        conn.execute(
            "ALTER TABLE schools ADD COLUMN finance_pin_hash TEXT"
        )

    conn.commit()
    conn.close()

init_db()

def school_logged_in():
    return (
        session.get("logged_in")
        and session.get("role") == "school"
        and session.get("school_id")
    )


def admin_logged_in():
    return (
        session.get("logged_in")
        and session.get("role") == "admin"
    )


def get_school_finance_settings(school_id):
    conn = get_db()
    row = conn.execute("""
        SELECT
            finance_privacy_enabled,
            finance_pin_hash
        FROM schools
        WHERE id = ?
    """, (school_id,)).fetchone()
    conn.close()
    return row


def finance_is_required(school_id):
    settings = get_school_finance_settings(school_id)
    return bool(
        settings
        and settings["finance_privacy_enabled"]
    )


def finance_is_unlocked():
    return (
        session.get("finance_unlocked") is True
        and session.get("finance_unlocked_school_id")
        == session.get("school_id")
    )


def finance_can_view(school_id):
    return (
        not finance_is_required(school_id)
        or finance_is_unlocked()
    )


def get_selected_period():
    now = datetime.now()

    try:
        year = int(request.args.get("year", now.year))
    except:
        year = now.year

    try:
        month = int(request.args.get("month", now.month))
    except:
        month = now.month

    if month < 1 or month > 12:
        month = now.month

    return year, month


MONTH_NAMES = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık"
}


# ------------------------------------------------
# GİRİŞ
# ------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def login():

    if session.get("logged_in"):

        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))

        if session.get("role") == "school":
            return redirect(url_for("dashboard"))

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # SÜPER ADMIN GİRİŞİ
        if (
            username == SUPERADMIN_USERNAME
            and password == SUPERADMIN_PASSWORD
        ):
            session.clear()

            session["logged_in"] = True
            session["role"] = "admin"

            return redirect(url_for("admin_dashboard"))

        # FUTBOL OKULU GİRİŞİ
        conn = get_db()

        school = conn.execute("""
            SELECT *
            FROM schools
            WHERE username = ?
        """, (username,)).fetchone()

        conn.close()

        if school:

            if not school["active"]:
                flash("Bu futbol okulu hesabı pasif durumda.")
                return render_template("login.html")

            if check_password_hash(
                school["password_hash"],
                password
            ):

                session.clear()

                session["logged_in"] = True
                session["role"] = "school"
                session["school_id"] = school["id"]
                session["school_name"] = school["name"]

                return redirect(url_for("dashboard"))

        flash("Kullanıcı adı veya şifre yanlış.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))



# ------------------------------------------------
# FUTBOL OKULU - ŞİFRE DEĞİŞTİR
# ------------------------------------------------

@app.route("/change-password", methods=["GET", "POST"])
def change_password():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if len(new_password) < 4:
            flash("Yeni şifre en az 4 karakter olmalı.")
            return render_template("change_password.html")

        if new_password != confirm_password:
            flash("Yeni şifreler eşleşmiyor.")
            return render_template("change_password.html")

        conn = get_db()

        school = conn.execute("""
            SELECT password_hash
            FROM schools
            WHERE id = ?
        """, (school_id,)).fetchone()

        if not school or not check_password_hash(
            school["password_hash"],
            current_password
        ):
            conn.close()
            flash("Mevcut şifreniz yanlış.")
            return render_template("change_password.html")

        if check_password_hash(
            school["password_hash"],
            new_password
        ):
            conn.close()
            flash("Yeni şifre mevcut şifrenizden farklı olmalı.")
            return render_template("change_password.html")

        conn.execute("""
            UPDATE schools
            SET password_hash = ?
            WHERE id = ?
        """, (
            generate_password_hash(new_password),
            school_id
        ))

        conn.commit()
        conn.close()

        flash("Şifreniz başarıyla değiştirildi.")
        return redirect(url_for("dashboard"))

    return render_template("change_password.html")


# ------------------------------------------------
# SÜPER ADMIN
# ------------------------------------------------

@app.route("/admin")
def admin_dashboard():

    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    schools = conn.execute("""
        SELECT
            schools.*,
            COUNT(students.id) AS student_count
        FROM schools
        LEFT JOIN students
            ON students.school_id = schools.id
            AND students.active = 1
        GROUP BY schools.id
        ORDER BY schools.id DESC
    """).fetchall()

    total_schools = conn.execute("""
        SELECT COUNT(*)
        FROM schools
    """).fetchone()[0]

    active_schools = conn.execute("""
        SELECT COUNT(*)
        FROM schools
        WHERE active = 1
    """).fetchone()[0]

    total_students = conn.execute("""
        SELECT COUNT(*)
        FROM students
        WHERE active = 1
    """).fetchone()[0]

    conn.close()

    return render_template(
        "admin_dashboard.html",
        schools=schools,
        total_schools=total_schools,
        active_schools=active_schools,
        total_students=total_students
    )


@app.route("/admin/school/add", methods=["GET", "POST"])
def admin_add_school():

    if not admin_logged_in():
        return redirect(url_for("login"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not name or not username or not password:
            flash("Tüm alanları doldurun.")
            return render_template("admin_add_school.html")

        conn = get_db()

        existing = conn.execute("""
            SELECT id
            FROM schools
            WHERE username = ?
        """, (username,)).fetchone()

        if existing:
            conn.close()

            flash("Bu kullanıcı adı zaten kullanılıyor.")
            return render_template("admin_add_school.html")

        password_hash = generate_password_hash(password)

        conn.execute("""
            INSERT INTO schools
            (
                name,
                username,
                password_hash,
                active,
                created_at
            )
            VALUES (?, ?, ?, 1, ?)
        """, (
            name,
            username,
            password_hash,
            datetime.now().strftime("%d.%m.%Y %H:%M")
        ))

        conn.commit()
        conn.close()

        flash("Futbol okulu başarıyla oluşturuldu.")

        return redirect(url_for("admin_dashboard"))

    return render_template("admin_add_school.html")


@app.route(
    "/admin/school/<int:school_id>/toggle",
    methods=["POST"]
)
def admin_toggle_school(school_id):

    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    school = conn.execute("""
        SELECT active
        FROM schools
        WHERE id = ?
    """, (school_id,)).fetchone()

    if school:

        new_status = 0 if school["active"] else 1

        conn.execute("""
            UPDATE schools
            SET active = ?
            WHERE id = ?
        """, (
            new_status,
            school_id
        ))

        conn.commit()

    conn.close()

    return redirect(url_for("admin_dashboard"))


@app.route(
    "/admin/school/<int:school_id>/delete",
    methods=["POST"]
)
def admin_delete_school(school_id):

    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    school = conn.execute("""
        SELECT name
        FROM schools
        WHERE id = ?
    """, (school_id,)).fetchone()

    if not school:
        conn.close()
        flash("Futbol okulu bulunamadı.")
        return redirect(url_for("admin_dashboard"))

    school_name = school["name"]

    conn.execute("""
        DELETE FROM schools
        WHERE id = ?
    """, (school_id,))

    conn.commit()
    conn.close()

    flash(f"{school_name} ve bağlı tüm verileri kalıcı olarak silindi.")
    return redirect(url_for("admin_dashboard"))


@app.route(
    "/admin/school/<int:school_id>/password",
    methods=["POST"]
)
def admin_change_school_password(school_id):

    if not admin_logged_in():
        return redirect(url_for("login"))

    new_password = request.form.get(
        "new_password",
        ""
    ).strip()

    if len(new_password) < 4:
        flash("Yeni şifre en az 4 karakter olmalı.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()

    conn.execute("""
        UPDATE schools
        SET password_hash = ?
        WHERE id = ?
    """, (
        generate_password_hash(new_password),
        school_id
    ))

    conn.commit()
    conn.close()

    flash("Futbol okulunun şifresi değiştirildi.")

    return redirect(url_for("admin_dashboard"))


# ------------------------------------------------
# MUHASEBE GİZLİLİĞİ - SÜPER ADMIN
# ------------------------------------------------

@app.route("/admin/finance-settings", methods=["GET", "POST"])
def admin_finance_settings():

    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    if request.method == "POST":

        school_id = request.form.get("school_id", type=int)
        enabled = 1 if request.form.get("enabled") == "on" else 0
        new_pin = request.form.get("pin", "").strip()

        school = conn.execute("""
            SELECT *
            FROM schools
            WHERE id = ?
        """, (school_id,)).fetchone()

        if not school:
            conn.close()
            flash("Futbol okulu bulunamadı.")
            return redirect(url_for("admin_finance_settings"))

        if enabled and not school["finance_pin_hash"] and len(new_pin) < 4:
            conn.close()
            flash("Muhasebe gizliliğini açmak için en az 4 haneli bir PIN girin.")
            return redirect(url_for("admin_finance_settings"))

        if new_pin:
            if len(new_pin) < 4:
                conn.close()
                flash("PIN en az 4 karakter olmalı.")
                return redirect(url_for("admin_finance_settings"))

            conn.execute("""
                UPDATE schools
                SET
                    finance_privacy_enabled = ?,
                    finance_pin_hash = ?
                WHERE id = ?
            """, (
                enabled,
                generate_password_hash(new_pin),
                school_id
            ))
        else:
            conn.execute("""
                UPDATE schools
                SET finance_privacy_enabled = ?
                WHERE id = ?
            """, (
                enabled,
                school_id
            ))

        conn.commit()
        conn.close()

        flash("Muhasebe gizliliği ayarları güncellendi.")
        return redirect(url_for("admin_finance_settings"))

    schools = conn.execute("""
        SELECT
            id,
            name,
            username,
            finance_privacy_enabled,
            CASE
                WHEN finance_pin_hash IS NOT NULL
                     AND finance_pin_hash != ''
                THEN 1
                ELSE 0
            END AS has_finance_pin
        FROM schools
        ORDER BY name ASC
    """).fetchall()

    conn.close()

    return render_template(
        "admin_finance_settings.html",
        schools=schools
    )


# ------------------------------------------------
# MUHASEBE GİZLİLİĞİ - OKUL
# ------------------------------------------------

@app.route("/finance/unlock", methods=["GET", "POST"])
def finance_unlock():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]
    settings = get_school_finance_settings(school_id)

    if not settings or not settings["finance_privacy_enabled"]:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        pin = request.form.get("pin", "").strip()

        if (
            settings["finance_pin_hash"]
            and check_password_hash(
                settings["finance_pin_hash"],
                pin
            )
        ):
            session["finance_unlocked"] = True
            session["finance_unlocked_school_id"] = school_id

            flash("Yönetici muhasebe görünümü açıldı.")

            next_url = request.form.get("next", "").strip()

            if next_url.startswith("/"):
                return redirect(next_url)

            return redirect(url_for("dashboard"))

        flash("Yönetici PIN'i yanlış.")

    return render_template(
        "finance_unlock.html"
    )


@app.route("/finance/lock", methods=["POST"])
def finance_lock():

    if not school_logged_in():
        return redirect(url_for("login"))

    session.pop("finance_unlocked", None)
    session.pop("finance_unlocked_school_id", None)

    flash("Muhasebe görünümü kilitlendi.")

    return redirect(
        request.referrer
        or url_for("dashboard")
    )


# ------------------------------------------------
# FUTBOL OKULU DASHBOARD
# ------------------------------------------------

@app.route("/dashboard")
def dashboard():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    year, month = get_selected_period()

    conn = get_db()

    total_students = conn.execute("""
        SELECT COUNT(*)
        FROM students
        WHERE school_id = ?
        AND active = 1
    """, (school_id,)).fetchone()[0]

    paid_students = conn.execute("""
        SELECT COUNT(*)
        FROM students s
        JOIN payments p
            ON p.student_id = s.id
        WHERE s.school_id = ?
        AND s.active = 1
        AND p.year = ?
        AND p.month = ?
        AND p.paid = 1
    """, (
        school_id,
        year,
        month
    )).fetchone()[0]

    unpaid_students = (
        total_students - paid_students
    )

    expected_income = conn.execute("""
        SELECT COALESCE(SUM(monthly_fee), 0)
        FROM students
        WHERE school_id = ?
        AND active = 1
    """, (school_id,)).fetchone()[0]

    total_income = conn.execute("""
        SELECT COALESCE(SUM(p.amount), 0)
        FROM payments p
        JOIN students s
            ON s.id = p.student_id
        WHERE s.school_id = ?
        AND p.year = ?
        AND p.month = ?
        AND p.paid = 1
    """, (
        school_id,
        year,
        month
    )).fetchone()[0]

    remaining_income = (
        expected_income - total_income
    )

    total_expenses = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE school_id = ?
        AND CAST(strftime('%Y', expense_date) AS INTEGER) = ?
        AND CAST(strftime('%m', expense_date) AS INTEGER) = ?
    """, (
        school_id,
        year,
        month
    )).fetchone()[0]

    net_cash = total_income - total_expenses

    unpaid_list = conn.execute("""
        SELECT
            s.*,
            COALESCE(p.paid, 0) AS paid
        FROM students s
        LEFT JOIN payments p
            ON p.student_id = s.id
            AND p.year = ?
            AND p.month = ?
        WHERE s.school_id = ?
        AND s.active = 1
        AND COALESCE(p.paid, 0) = 0
        ORDER BY
            s.birth_year DESC,
            s.name ASC
    """, (
        year,
        month,
        school_id
    )).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        total_students=total_students,
        paid_students=paid_students,
        unpaid_students=unpaid_students,
        expected_income=expected_income,
        total_income=total_income,
        remaining_income=remaining_income,
        total_expenses=total_expenses,
        net_cash=net_cash,
        unpaid_list=unpaid_list,
        selected_year=year,
        selected_month=month,
        month_name=MONTH_NAMES[month],
        months=MONTH_NAMES,
        finance_privacy_enabled=finance_is_required(school_id),
        finance_visible=finance_can_view(school_id)
    )


# ------------------------------------------------
# ÖĞRENCİLER
# ------------------------------------------------

@app.route("/students")
def students():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    year, month = get_selected_period()

    search = request.args.get("search", "").strip()
    birth_year = request.args.get("birth_year", "").strip()
    class_group = request.args.get("class_group", "").strip()
    payment = request.args.get("payment", "").strip()

    query = """
        SELECT
            s.*,
            COALESCE(p.paid, 0) AS paid,
            p.paid_at
        FROM students s
        LEFT JOIN payments p
            ON p.student_id = s.id
            AND p.year = ?
            AND p.month = ?
        WHERE s.school_id = ?
    """

    params = [year, month, school_id]

    if search:
        query += """
            AND (
                s.name LIKE ?
                OR s.parent_name LIKE ?
                OR s.phone LIKE ?
                OR s.class_group LIKE ?
            )
        """
        term = f"%{search}%"
        params.extend([term, term, term, term])

    if birth_year:
        query += " AND s.birth_year = ?"
        params.append(birth_year)

    if class_group:
        query += " AND s.class_group = ?"
        params.append(class_group)

    if payment == "paid":
        query += " AND COALESCE(p.paid, 0) = 1"
    elif payment == "unpaid":
        query += " AND COALESCE(p.paid, 0) = 0"

    query += """
        ORDER BY
            s.birth_year DESC,
            COALESCE(s.class_group, '') ASC,
            s.name ASC
    """

    conn = get_db()

    student_list = conn.execute(query, params).fetchall()

    years = conn.execute("""
        SELECT DISTINCT birth_year
        FROM students
        WHERE school_id = ?
        ORDER BY birth_year DESC
    """, (school_id,)).fetchall()

    class_groups = conn.execute("""
        SELECT DISTINCT class_group
        FROM students
        WHERE school_id = ?
        AND class_group IS NOT NULL
        AND TRIM(class_group) != ''
        ORDER BY class_group ASC
    """, (school_id,)).fetchall()

    conn.close()

    return render_template(
        "students.html",
        students=student_list,
        years=years,
        class_groups=class_groups,
        search=search,
        birth_year=birth_year,
        class_group=class_group,
        payment=payment,
        selected_year=year,
        selected_month=month,
        month_name=MONTH_NAMES[month],
        months=MONTH_NAMES,
        finance_privacy_enabled=finance_is_required(school_id),
        finance_visible=finance_can_view(school_id)
    )


@app.route(
    "/student/add",
    methods=["GET", "POST"]
)
def add_student():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    if request.method == "POST":

        name = request.form.get("name")
        birth_year = request.form.get("birth_year")
        class_group = request.form.get("class_group", "").strip()
        parent_name = request.form.get("parent_name")
        phone = request.form.get("phone")
        if finance_can_view(school_id):
            monthly_fee = request.form.get("monthly_fee") or 0
        else:
            monthly_fee = 0

        notes = request.form.get("notes")

        conn = get_db()

        conn.execute("""
            INSERT INTO students
            (
                school_id,
                name,
                birth_year,
                class_group,
                parent_name,
                phone,
                monthly_fee,
                active,
                notes,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            school_id,
            name,
            birth_year,
            class_group,
            parent_name,
            phone,
            monthly_fee,
            notes,
            datetime.now().strftime(
                "%d.%m.%Y %H:%M"
            )
        ))

        conn.commit()
        conn.close()

        flash(
            "Öğrenci başarıyla eklendi."
        )

        return redirect(
            url_for("students")
        )

    return render_template(
        "add_student.html",
        finance_privacy_enabled=finance_is_required(school_id),
        finance_visible=finance_can_view(school_id)
    )


@app.route(
    "/student/<int:student_id>/edit",
    methods=["GET", "POST"]
)
def edit_student(student_id):

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    conn = get_db()

    student = conn.execute("""
        SELECT *
        FROM students
        WHERE id = ?
        AND school_id = ?
    """, (
        student_id,
        school_id
    )).fetchone()

    if not student:
        conn.close()
        return "Öğrenci bulunamadı.", 404

    if request.method == "POST":

        name = request.form.get("name")
        birth_year = request.form.get("birth_year")
        class_group = request.form.get("class_group", "").strip()
        parent_name = request.form.get("parent_name")
        phone = request.form.get("phone")
        if finance_can_view(school_id):
            monthly_fee = request.form.get("monthly_fee") or 0
        else:
            monthly_fee = student["monthly_fee"]

        notes = request.form.get("notes")

        active = (
            1
            if request.form.get("active") == "on"
            else 0
        )

        conn.execute("""
            UPDATE students
            SET
                name = ?,
                birth_year = ?,
                class_group = ?,
                parent_name = ?,
                phone = ?,
                monthly_fee = ?,
                notes = ?,
                active = ?
            WHERE id = ?
            AND school_id = ?
        """, (
            name,
            birth_year,
            class_group,
            parent_name,
            phone,
            monthly_fee,
            notes,
            active,
            student_id,
            school_id
        ))

        conn.commit()
        conn.close()

        flash(
            "Öğrenci güncellendi."
        )

        return redirect(
            url_for("students")
        )

    conn.close()

    return render_template(
        "edit_student.html",
        student=student,
        finance_privacy_enabled=finance_is_required(school_id),
        finance_visible=finance_can_view(school_id)
    )


# ------------------------------------------------
# AYLIK AİDAT
# ------------------------------------------------

@app.route(
    "/student/<int:student_id>/toggle-payment",
    methods=["POST"]
)
def toggle_payment(student_id):

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    year = request.form.get(
        "year",
        type=int
    )

    month = request.form.get(
        "month",
        type=int
    )

    now = datetime.now()

    if not year:
        year = now.year

    if not month:
        month = now.month

    conn = get_db()

    student = conn.execute("""
        SELECT *
        FROM students
        WHERE id = ?
        AND school_id = ?
    """, (
        student_id,
        school_id
    )).fetchone()

    if not student:
        conn.close()
        return "Öğrenci bulunamadı.", 404

    payment_row = conn.execute("""
        SELECT *
        FROM payments
        WHERE student_id = ?
        AND year = ?
        AND month = ?
    """, (
        student_id,
        year,
        month
    )).fetchone()

    if payment_row:

        new_value = (
            0
            if payment_row["paid"]
            else 1
        )

        paid_at = (
            datetime.now().strftime(
                "%d.%m.%Y %H:%M"
            )
            if new_value
            else None
        )

        conn.execute("""
            UPDATE payments
            SET
                paid = ?,
                amount = ?,
                paid_at = ?
            WHERE id = ?
        """, (
            new_value,
            student["monthly_fee"],
            paid_at,
            payment_row["id"]
        ))

    else:

        conn.execute("""
            INSERT INTO payments
            (
                student_id,
                year,
                month,
                amount,
                paid,
                paid_at
            )
            VALUES (?, ?, ?, ?, 1, ?)
        """, (
            student_id,
            year,
            month,
            student["monthly_fee"],
            datetime.now().strftime(
                "%d.%m.%Y %H:%M"
            )
        ))

    conn.commit()
    conn.close()

    return redirect(
        request.referrer
        or url_for(
            "students",
            year=year,
            month=month
        )
    )


# ------------------------------------------------
# EXCEL / CSV YEDEK DIŞA AKTARMA
# ------------------------------------------------

@app.route("/export-backup")
def export_backup():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    if not finance_can_view(school_id):
        flash("Dışa aktarma için yönetici PIN'i gerekli.")
        return redirect(
            url_for(
                "finance_unlock",
                next=request.path
            )
        )
    school_name = session.get("school_name", "futbol_okulu")

    conn = get_db()

    students_rows = conn.execute("""
        SELECT
            id,
            name,
            birth_year,
            class_group,
            parent_name,
            phone,
            monthly_fee,
            active,
            notes,
            created_at
        FROM students
        WHERE school_id = ?
        ORDER BY birth_year DESC, class_group ASC, name ASC
    """, (school_id,)).fetchall()

    payments_rows = conn.execute("""
        SELECT
            s.name AS student_name,
            s.birth_year,
            s.class_group,
            p.year,
            p.month,
            p.amount,
            p.paid,
            p.paid_at
        FROM payments p
        JOIN students s ON s.id = p.student_id
        WHERE s.school_id = ?
        ORDER BY p.year DESC, p.month DESC, s.name ASC
    """, (school_id,)).fetchall()

    attendance_rows = conn.execute("""
        SELECT
            s.name AS student_name,
            s.birth_year,
            s.class_group,
            a.attendance_date,
            a.present,
            a.created_at
        FROM attendance a
        JOIN students s ON s.id = a.student_id
        WHERE s.school_id = ?
        ORDER BY a.attendance_date DESC, s.name ASC
    """, (school_id,)).fetchall()

    expenses_rows = conn.execute("""
        SELECT
            description,
            amount,
            expense_date,
            created_at
        FROM expenses
        WHERE school_id = ?
        ORDER BY expense_date DESC, id DESC
    """, (school_id,)).fetchall()

    conn.close()

    def make_csv(headers, rows, transform=None):
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(headers)

        for row in rows:
            values = list(row)
            if transform:
                values = transform(values)
            writer.writerow(values)

        return ("\ufeff" + output.getvalue()).encode("utf-8")

    students_csv = make_csv(
        [
            "ID", "Öğrenci", "Doğum Yılı", "Sınıf / Grup",
            "Veli", "Telefon", "Aylık Aidat", "Aktif",
            "Not", "Kayıt Tarihi"
        ],
        students_rows,
        lambda v: v[:7] + [("Evet" if v[7] else "Hayır")] + v[8:]
    )

    payments_csv = make_csv(
        [
            "Öğrenci", "Doğum Yılı", "Sınıf / Grup",
            "Yıl", "Ay", "Tutar", "Ödeme Durumu", "Ödeme Tarihi"
        ],
        payments_rows,
        lambda v: v[:6] + [("Ödendi" if v[6] else "Ödenmedi")] + v[7:]
    )

    attendance_csv = make_csv(
        [
            "Öğrenci", "Doğum Yılı", "Sınıf / Grup",
            "Yoklama Tarihi", "Durum", "Kayıt Tarihi"
        ],
        attendance_rows,
        lambda v: v[:4] + [("Geldi" if v[4] else "Gelmedi")] + v[5:]
    )

    expenses_csv = make_csv(
        ["Açıklama", "Tutar", "Gider Tarihi", "Kayıt Tarihi"],
        expenses_rows
    )

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ogrenciler.csv", students_csv)
        archive.writestr("aidatlar.csv", payments_csv)
        archive.writestr("yoklama.csv", attendance_csv)
        archive.writestr("giderler.csv", expenses_csv)

    zip_buffer.seek(0)

    safe_school_name = "".join(
        char if char.isalnum() else "_"
        for char in school_name
    ).strip("_") or "futbol_okulu"

    filename = (
        f"{safe_school_name}_yedek_"
        f"{datetime.now().strftime('%Y-%m-%d')}.zip"
    )

    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename
    )


# ------------------------------------------------
# YOKLAMA
# ------------------------------------------------

@app.route("/attendance", methods=["GET", "POST"])
def attendance():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    selected_date = request.args.get(
        "date",
        datetime.now().strftime("%Y-%m-%d")
    )

    selected_birth_year = request.args.get(
        "birth_year",
        ""
    ).strip()

    selected_class_group = request.args.get(
        "class_group",
        ""
    ).strip()

    if request.method == "POST":

        selected_date = request.form.get(
            "attendance_date",
            datetime.now().strftime("%Y-%m-%d")
        )

        selected_birth_year = request.form.get(
            "birth_year",
            ""
        ).strip()

        selected_class_group = request.form.get(
            "class_group",
            ""
        ).strip()

        conn = get_db()

        query = """
            SELECT id
            FROM students
            WHERE school_id = ?
            AND active = 1
        """

        params = [school_id]

        if selected_birth_year:
            query += " AND birth_year = ?"
            params.append(selected_birth_year)

        if selected_class_group:
            query += " AND class_group = ?"
            params.append(selected_class_group)

        students_list = conn.execute(
            query,
            params
        ).fetchall()

        for student in students_list:

            student_id = student["id"]

            status = request.form.get(
                f"attendance_{student_id}"
            )

            # Seçilmemiş öğrenciyi değiştirme.
            if status not in ("present", "absent"):
                continue

            present = 1 if status == "present" else 0

            conn.execute("""
                INSERT INTO attendance
                (
                    student_id,
                    attendance_date,
                    present,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(student_id, attendance_date)
                DO UPDATE SET
                    present = excluded.present,
                    created_at = excluded.created_at
            """, (
                student_id,
                selected_date,
                present,
                datetime.now().strftime(
                    "%d.%m.%Y %H:%M"
                )
            ))

        conn.commit()
        conn.close()

        flash("Yoklama başarıyla kaydedildi.")

        return redirect(
            url_for(
                "attendance",
                date=selected_date,
                birth_year=selected_birth_year,
                class_group=selected_class_group
            )
        )

    conn = get_db()

    query = """
        SELECT
            s.*,
            a.present AS present,
            CASE
                WHEN a.id IS NULL THEN 0
                ELSE 1
            END AS attendance_saved
        FROM students s
        LEFT JOIN attendance a
            ON a.student_id = s.id
            AND a.attendance_date = ?
        WHERE s.school_id = ?
        AND s.active = 1
    """

    params = [
        selected_date,
        school_id
    ]

    if selected_birth_year:
        query += " AND s.birth_year = ?"
        params.append(selected_birth_year)

    if selected_class_group:
        query += " AND s.class_group = ?"
        params.append(selected_class_group)

    query += """
        ORDER BY
            s.birth_year DESC,
            COALESCE(s.class_group, '') ASC,
            s.name ASC
    """

    student_list = conn.execute(
        query,
        params
    ).fetchall()

    birth_years = conn.execute("""
        SELECT DISTINCT birth_year
        FROM students
        WHERE school_id = ?
        AND active = 1
        ORDER BY birth_year DESC
    """, (
        school_id,
    )).fetchall()

    class_groups = conn.execute("""
        SELECT DISTINCT class_group
        FROM students
        WHERE school_id = ?
        AND active = 1
        AND class_group IS NOT NULL
        AND TRIM(class_group) != ''
        ORDER BY class_group ASC
    """, (
        school_id,
    )).fetchall()

    history = conn.execute("""
        SELECT
            a.attendance_date,
            SUM(
                CASE
                    WHEN a.present = 1 THEN 1
                    ELSE 0
                END
            ) AS present_count,
            SUM(
                CASE
                    WHEN a.present = 0 THEN 1
                    ELSE 0
                END
            ) AS absent_count
        FROM attendance a
        JOIN students s
            ON s.id = a.student_id
        WHERE s.school_id = ?
        GROUP BY a.attendance_date
        ORDER BY a.attendance_date DESC
        LIMIT 15
    """, (
        school_id,
    )).fetchall()

    conn.close()

    return render_template(
        "attendance.html",
        students=student_list,
        selected_date=selected_date,
        selected_birth_year=selected_birth_year,
        selected_class_group=selected_class_group,
        birth_years=birth_years,
        class_groups=class_groups,
        history=history,
        finance_privacy_enabled=finance_is_required(school_id),
        finance_visible=finance_can_view(school_id)
    )


# ------------------------------------------------
# GİDERLER
# ------------------------------------------------

@app.route("/expenses", methods=["GET", "POST"])
def expenses():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    if not finance_can_view(school_id):
        flash("Gider ve kasa bilgileri için yönetici PIN'i gerekli.")
        return redirect(
            url_for(
                "finance_unlock",
                next=request.path
            )
        )

    year, month = get_selected_period()

    if request.method == "POST":
        description = request.form.get("description", "").strip()
        amount = request.form.get("amount", type=float)
        expense_date = request.form.get(
            "expense_date",
            datetime.now().strftime("%Y-%m-%d")
        )

        if not description:
            flash("Gider açıklaması boş bırakılamaz.")
            return redirect(url_for("expenses", year=year, month=month))

        if amount is None or amount <= 0:
            flash("Geçerli bir gider tutarı girin.")
            return redirect(url_for("expenses", year=year, month=month))

        try:
            expense_dt = datetime.strptime(expense_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            flash("Geçerli bir gider tarihi seçin.")
            return redirect(url_for("expenses", year=year, month=month))

        conn = get_db()

        conn.execute("""
            INSERT INTO expenses
            (school_id, description, amount, expense_date, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            school_id,
            description,
            amount,
            expense_date,
            datetime.now().strftime("%d.%m.%Y %H:%M")
        ))

        conn.commit()
        conn.close()

        flash("Gider başarıyla eklendi.")
        return redirect(url_for(
            "expenses",
            year=expense_dt.year,
            month=expense_dt.month
        ))

    conn = get_db()

    expense_list = conn.execute("""
        SELECT *
        FROM expenses
        WHERE school_id = ?
        AND CAST(strftime('%Y', expense_date) AS INTEGER) = ?
        AND CAST(strftime('%m', expense_date) AS INTEGER) = ?
        ORDER BY expense_date DESC, id DESC
    """, (
        school_id,
        year,
        month
    )).fetchall()

    total_expenses = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE school_id = ?
        AND CAST(strftime('%Y', expense_date) AS INTEGER) = ?
        AND CAST(strftime('%m', expense_date) AS INTEGER) = ?
    """, (
        school_id,
        year,
        month
    )).fetchone()[0]

    conn.close()

    return render_template(
        "expenses.html",
        expenses=expense_list,
        total_expenses=total_expenses,
        selected_year=year,
        selected_month=month,
        month_name=MONTH_NAMES[month],
        months=MONTH_NAMES
    )


@app.route("/expense/<int:expense_id>/delete", methods=["POST"])
def delete_expense(expense_id):

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    if not finance_can_view(school_id):
        flash("Bu işlem için yönetici PIN'i gerekli.")
        return redirect(url_for("finance_unlock"))

    conn = get_db()

    conn.execute("""
        DELETE FROM expenses
        WHERE id = ?
        AND school_id = ?
    """, (
        expense_id,
        school_id
    ))

    conn.commit()
    conn.close()

    flash("Gider silindi.")
    return redirect(request.referrer or url_for("expenses"))


@app.route(
    "/student/<int:student_id>/delete",
    methods=["POST"]
)
def delete_student(student_id):

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]

    conn = get_db()

    conn.execute("""
        DELETE FROM students
        WHERE id = ?
        AND school_id = ?
    """, (
        student_id,
        school_id
    ))

    conn.commit()
    conn.close()

    flash(
        "Öğrenci silindi."
    )

    return redirect(
        url_for("students")
    )



# ------------------------------------------------
# PWA
# ------------------------------------------------

@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "manifest.webmanifest",
        mimetype="application/manifest+json"
    )


@app.route("/service-worker.js")
def service_worker():
    response = send_from_directory(
        os.path.join(app.root_path, "static"),
        "service-worker.js",
        mimetype="application/javascript"
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


if __name__ == "__main__":
    app.run(debug=True)