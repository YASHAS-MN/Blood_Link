# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

# Ensure your .env matches this or update manually
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv('SECRET_KEY') or 'blood_save_life_2026'

db = SQLAlchemy(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        user_type = request.form.get('user_type')
        blood_group = request.form.get('blood_group')

        if not all([full_name, email, phone, password, user_type]):
            flash("All fields are required", "error")
            return redirect(url_for('signup'))

        # [FIX] Check if email exists BEFORE creating user
        existing_user = db.session.execute(
            text("SELECT 1 FROM users WHERE email = :email"), 
            {'email': email}
        ).fetchone()
        
        if existing_user:
            flash("This email is already registered. Please Login.", "error")
            return redirect(url_for('signup'))

        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')

        try:
            # 1. Create User
            query = """
            INSERT INTO users (full_name, email, password_hash, phone_number, user_type, registration_timestamp)
            VALUES (:name, :email, :pw, :phone, :type, :ts) RETURNING user_id
            """
            result = db.session.execute(text(query), {
                'name': full_name, 'email': email, 'pw': hashed_pw,
                'phone': phone, 'type': user_type, 'ts': datetime.utcnow()
            })
            user_id = result.fetchone()[0]
            db.session.commit()

            # 2. If Donor, Create Profile
            if user_type == 'donor':
                db.session.execute(text("""
                    INSERT INTO donor_profiles (user_id, blood_group, current_location, is_available)
                    VALUES (:uid, :bg, 'Location Not Set', TRUE)
                """), {'uid': user_id, 'bg': blood_group})
                db.session.commit()

            session['user_id'] = user_id
            session['user_type'] = user_type

            # 3. Route to Portal
            if user_type == 'donor':
                return redirect(url_for('donor_portal', user_id=user_id))
            elif user_type == 'receiver':
                return redirect(url_for('receiver_portal', user_id=user_id))

        except Exception as e:
            db.session.rollback()
            flash(f"System Error: {str(e)}", "error")
            return redirect(url_for('signup'))

    return render_template('signup.html')

@app.route('/ngo_signup', methods=['GET', 'POST'])
def ngo_signup():
    # [FIX] SMART REDIRECT: If already logged in, go straight to Dashboard
    if 'user_id' in session and session.get('user_type') == 'ngo':
        return redirect(url_for('ngo_portal', user_id=session['user_id']))
    
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        ngo_id = request.form.get('ngo_id')
        full_name = request.form.get('full_name')
        email = request.form.get('email')

        # [FIX] Check for existing email first
        existing_user = db.session.execute(
            text("SELECT 1 FROM users WHERE email = :email"), 
            {'email': email}
        ).fetchone()

        if existing_user:
            flash("This email is already registered. Please Login.", "error")
            return redirect(url_for('ngo_signup'))

        combined_name = f"{full_name} [{ngo_id}]"
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')

        try:
            query = """
            INSERT INTO users (full_name, email, password_hash, phone_number, user_type, registration_timestamp)
            VALUES (:name, :email, :pw, :phone, 'ngo', :ts) RETURNING user_id
            """
            result = db.session.execute(text(query), {
                'name': combined_name, 'email': email, 'pw': hashed_pw,
                'phone': phone, 'ts': datetime.utcnow()
            })
            user_id = result.fetchone()[0]
            db.session.commit()

            session['user_id'] = user_id
            session['user_type'] = 'ngo'

            return redirect(url_for('ngo_portal', user_id=user_id))

        except Exception as e:
            db.session.rollback()
            flash(f"Registration Failed: {str(e)}", "error")
            return redirect(url_for('ngo_signup'))

    return render_template('ngo_signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            query = """
            SELECT user_id, password_hash, user_type FROM users WHERE email = :email
            """
            result = db.session.execute(text(query), {'email': email}).fetchone()

            if result:
                # User Found, Check Password
                if check_password_hash(result[1], password):
                    session['user_id'] = result[0]
                    session['user_type'] = result[2]

                    if result[2] == 'donor':
                        return redirect(url_for('donor_portal', user_id=result[0]))
                    elif result[2] == 'receiver':
                        return redirect(url_for('receiver_portal', user_id=result[0]))
                    elif result[2] == 'ngo':
                        return redirect(url_for('ngo_portal', user_id=result[0]))
                else:
                    flash("Incorrect password. Please try again.", "error")
            else:
                # User Not Found
                flash("No account registered with this email. Please Sign Up.", "error")

        except Exception as e:
            flash(f"Login failed: {str(e)}", "error")

        return redirect(url_for('login'))

    return render_template('login.html')

# --- DONOR PORTAL (Shows peers with same blood group) ---
@app.route('/donor_portal/<user_id>')
def donor_portal(user_id):
    if str(session.get('user_id')) != str(user_id) or session.get('user_type') != 'donor':
        flash("Unauthorized access", "error")
        return redirect(url_for('login'))

    # Get Current Donor's Info
    my_profile = db.session.execute(text(
        "SELECT blood_group, current_location FROM donor_profiles WHERE user_id = :uid"
    ), {'uid': user_id}).fetchone()
    
    my_bg = my_profile[0] if my_profile else 'Unknown'

    # Get list of OTHER donors with SAME Blood Group (Irrespective of location)
    query = """
    SELECT u.full_name, d.blood_group, d.current_location, u.phone_number
    FROM users u
    JOIN donor_profiles d ON u.user_id = d.user_id
    WHERE d.blood_group = :bg AND u.user_id != :uid
    """
    peers = db.session.execute(text(query), {'bg': my_bg, 'uid': user_id}).fetchall()

    return render_template('donor_portal.html', user_id=user_id, blood_group=my_bg, peers=peers)

# --- NGO PORTAL ---
# --- NGO PORTAL & MANAGEMENT ---
@app.route('/ngo_portal/<user_id>')
def ngo_portal(user_id):
    if str(session.get('user_id')) != str(user_id) or session.get('user_type') != 'ngo':
        flash("Login as NGO first", "error")
        return redirect(url_for('login'))

    # 1. Fetch Active Donors
    donors = db.session.execute(text("""
        SELECT u.user_id, u.full_name, d.blood_group, d.current_location, u.phone_number 
        FROM users u JOIN donor_profiles d ON u.user_id = d.user_id
    """)).fetchall()

    # 2. Fetch COMPLETE Donation History (Joined with User Names)
    # This replaces the raw IDs with actual names for the NGO admin
    history_query = """
        SELECT 
            d.donation_id, 
            d.donation_date, 
            d.location, 
            d.verified,
            u_donor.full_name AS donor_name,
            u_receiver.full_name AS receiver_name,
            d.donor_id,
            d.receiver_id
        FROM donations d
        JOIN users u_donor ON d.donor_id = u_donor.user_id
        LEFT JOIN users u_receiver ON d.receiver_id = u_receiver.user_id
        ORDER BY d.donation_date DESC
    """
    donations = db.session.execute(text(history_query)).fetchall()

    return render_template('ngo_portal.html', 
                         donors=donors, 
                         donations=donations, 
                         user_id=user_id)

# --- EDIT DONATION ROUTE ---
@app.route('/edit_donation/<user_id>', methods=['POST'])
def edit_donation(user_id):
    donation_id = request.form.get('donation_id')
    location = request.form.get('location')
    date = request.form.get('donation_date')
    status = request.form.get('verified') # 'on' if checked, None if not

    is_verified = True if status else False

    try:
        query = """
            UPDATE donations 
            SET location = :loc, donation_date = :date, verified = :ver
            WHERE donation_id = :did
        """
        db.session.execute(text(query), {
            'loc': location, 
            'date': date, 
            'ver': is_verified, 
            'did': donation_id
        })
        db.session.commit()
        flash("Record updated successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Update failed: {str(e)}", "error")

    return redirect(url_for('ngo_portal', user_id=user_id))

# --- DELETE DONATION ROUTE ---
@app.route('/delete_donation/<user_id>/<int:donation_id>')
def delete_donation(user_id, donation_id):
    try:
        db.session.execute(text("DELETE FROM donations WHERE donation_id = :did"), {'did': donation_id})
        db.session.commit()
        flash("Record deleted permanently", "success")
    except Exception as e:
        db.session.rollback()
        flash("Could not delete record", "error")
    
    return redirect(url_for('ngo_portal', user_id=user_id))

# --- RECEIVER PORTAL (Search by Blood Group AND Location) ---
@app.route('/receiver_portal/<user_id>')
def receiver_portal(user_id):
    if str(session.get('user_id')) != str(user_id) or session.get('user_type') != 'receiver':
        flash("Unauthorized", "error")
        return redirect(url_for('login'))
    return render_template('receiver_portal.html', user_id=user_id)

@app.route('/search_blood/<user_id>', methods=['POST'])
def search_blood(user_id):
    # Search logic: Match Blood Group AND Location
    required_blood = request.form.get('required_blood')
    required_location = request.form.get('location') # Capture location from form
    
    try:
        # Case insensitive location search
        query = """
        SELECT u.full_name, d.blood_group, d.current_location, u.phone_number 
        FROM users u 
        JOIN donor_profiles d ON u.user_id = d.user_id
        WHERE d.blood_group = :bg 
        AND LOWER(d.current_location) = LOWER(:loc)
        AND d.is_available = TRUE
        """
        donors = db.session.execute(text(query), {'bg': required_blood, 'loc': required_location}).fetchall()
        
        return render_template('receiver_portal.html', user_id=user_id, donors=donors, searched=True)
    except Exception as e:
        flash(f"Search failed: {str(e)}", "error")
        return redirect(url_for('receiver_portal', user_id=user_id))

@app.route('/update_donor/<user_id>', methods=['POST'])
def update_donor(user_id):
    location = request.form.get('location')
    try:
        db.session.execute(text("UPDATE donor_profiles SET current_location = :loc WHERE user_id = :uid"), 
                           {'loc': location, 'uid': user_id})
        db.session.commit()
        flash("Location updated!", "success")
    except:
        db.session.rollback()
    return redirect(url_for('donor_portal', user_id=user_id))

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)