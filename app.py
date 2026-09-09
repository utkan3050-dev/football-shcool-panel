from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os


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
        months=MONTH_NAMES
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

    search = request.args.get(
        "search",
        ""
    ).strip()

    birth_year = request.args.get(
        "birth_year",
        ""
    ).strip()

    payment = request.args.get(
        "payment",
        ""
    ).strip()

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

    params = [
        year,
        month,
        school_id
    ]

    if search:

        query += """
            AND (
                s.name LIKE ?
                OR s.parent_name LIKE ?
                OR s.phone LIKE ?
            )
        """

        term = f"%{search}%"

        params.extend([
            term,
            term,
            term
        ])

    if birth_year:

        query += """
            AND s.birth_year = ?
        """

        params.append(
            birth_year
        )

    if payment == "paid":

        query += """
            AND COALESCE(p.paid, 0) = 1
        """

    elif payment == "unpaid":

        query += """
            AND COALESCE(p.paid, 0) = 0
        """

    query += """
        ORDER BY
            s.birth_year DESC,
            s.name ASC
    """

    conn = get_db()

    student_list = conn.execute(
        query,
        params
    ).fetchall()

    years = conn.execute("""
        SELECT DISTINCT birth_year
        FROM students
        WHERE school_id = ?
        ORDER BY birth_year DESC
    """, (
        school_id,
    )).fetchall()

    conn.close()

    return render_template(
        "students.html",
        students=student_list,
        years=years,
        search=search,
        birth_year=birth_year,
        payment=payment,
        selected_year=year,
        selected_month=month,
        month_name=MONTH_NAMES[month],
        months=MONTH_NAMES
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
        parent_name = request.form.get("parent_name")
        phone = request.form.get("phone")
        monthly_fee = request.form.get("monthly_fee") or 0
        notes = request.form.get("notes")

        conn = get_db()

        conn.execute("""
            INSERT INTO students
            (
                school_id,
                name,
                birth_year,
                parent_name,
                phone,
                monthly_fee,
                active,
                notes,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            school_id,
            name,
            birth_year,
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
        "add_student.html"
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
        parent_name = request.form.get("parent_name")
        phone = request.form.get("phone")
        monthly_fee = request.form.get("monthly_fee") or 0
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
        student=student
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

    if request.method == "POST":

        selected_date = request.form.get(
            "attendance_date",
            datetime.now().strftime("%Y-%m-%d")
        )

        selected_birth_year = request.form.get(
            "birth_year",
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
                birth_year=selected_birth_year
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

    query += """
        ORDER BY
            s.birth_year DESC,
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
        birth_years=birth_years,
        history=history
    )


# ------------------------------------------------
# GİDERLER
# ------------------------------------------------

@app.route("/expenses", methods=["GET", "POST"])
def expenses():

    if not school_logged_in():
        return redirect(url_for("login"))

    school_id = session["school_id"]
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


if __name__ == "__main__":
    app.run(debug=True)