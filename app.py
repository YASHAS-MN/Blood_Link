# app.py - New Architecture - Blood Link Platform
import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, bindparam
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv('SECRET_KEY') or 'blood_save_life_2026'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours

db = SQLAlchemy(app)

# Recipient blood group -> compatible donor blood groups
COMPATIBLE_DONOR_GROUPS = {
    'O-': ['O-'],
    'O+': ['O-', 'O+'],
    'A-': ['O-', 'A-'],
    'A+': ['O-', 'O+', 'A-', 'A+'],
    'B-': ['O-', 'B-'],
    'B+': ['O-', 'O+', 'B-', 'B+'],
    'AB-': ['O-', 'A-', 'B-', 'AB-'],
    'AB+': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],
}


def get_compatible_donor_groups(required_blood_group):
    """Return donor blood groups that can donate to the required recipient group."""
    if not required_blood_group:
        return []
    normalized_group = required_blood_group.strip().upper()
    return COMPATIBLE_DONOR_GROUPS.get(normalized_group, [])


def find_available_compatible_donors(required_blood_group, location):
    """Fetch available donors by compatibility and location."""
    compatible_groups = get_compatible_donor_groups(required_blood_group)
    normalized_location = (location or '').strip()

    if not compatible_groups or not normalized_location:
        return []

    query = """
    SELECT u.full_name, d.blood_group, d.current_location, u.phone_number
    FROM users u
    JOIN donor_profiles d ON u.user_id = d.user_id
    WHERE d.blood_group IN :compatible_groups
    AND LOWER(d.current_location) = LOWER(:loc)
    AND d.is_available = TRUE
    """

    stmt = text(query).bindparams(bindparam('compatible_groups', expanding=True))
    return db.session.execute(
        stmt,
        {'compatible_groups': compatible_groups, 'loc': normalized_location}
    ).fetchall()

# ========== HOME & PORTAL ROUTES ==========
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/user_portal')
def user_portal():
    return render_template('user_portal.html')

# ========== RECEIVE BLOOD (No Auth Required) ==========
@app.route('/receive_blood', methods=['GET', 'POST'])
def receive_blood():
    donors = []
    searched = False
    
    if request.method == 'POST':
        blood_group = request.form.get('blood_group')
        location = request.form.get('location')
        searched = True
        
        try:
            donors = find_available_compatible_donors(blood_group, location)
        except Exception as e:
            flash(f"Search failed: {str(e)}", "error")
    
    return render_template('receive_blood.html', donors=donors, searched=searched)

@app.route('/search_available_donors', methods=['POST'])
def search_available_donors():
    blood_group = request.form.get('blood_group')
    location = request.form.get('location')
    
    try:
        donors = find_available_compatible_donors(blood_group, location)
    except Exception as e:
        flash(f"Search failed: {str(e)}", "error")
        donors = []
    
    return render_template('receive_blood.html', donors=donors, searched=True)

# ========== DONATE BLOOD ==========
@app.route('/donate_blood')
def donate_blood():
    # Redirect to choice page
    return render_template('donate_choice.html')

@app.route('/donor_signup', methods=['GET', 'POST'])
def donor_signup():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone_number = request.form.get('phone_number')
        password = request.form.get('password')
        blood_group = request.form.get('blood_group')
        location = request.form.get('location')
        
        if not all([full_name, email, phone_number, password, blood_group, location]):
            flash("All fields are required", "error")
            return redirect(url_for('donor_signup'))
        
        try:
            # Check if email already exists
            existing = db.session.execute(
                text("SELECT user_id FROM users WHERE email = :email AND user_type = 'donor'"),
                {'email': email}
            ).fetchone()
            
            if existing:
                # Email already registered
                flash("Account already exists with this email. Please login instead.", "error")
                return redirect(url_for('donor_login'))
            
            # Create new donor user
            hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
            query = """
            INSERT INTO users (full_name, email, password_hash, phone_number, user_type, registration_timestamp)
            VALUES (:name, :email, :pw, :phone, 'donor', :ts) RETURNING user_id
            """
            result = db.session.execute(text(query), {
                'name': full_name,
                'email': email,
                'pw': hashed_pw,
                'phone': phone_number,
                'ts': datetime.utcnow()
            })
            user_id = result.fetchone()[0]
            
            # Create donor profile
            db.session.execute(text("""
                INSERT INTO donor_profiles (user_id, blood_group, current_location, is_available)
                VALUES (:uid, :bg, :loc, TRUE)
            """), {'uid': user_id, 'bg': blood_group, 'loc': location})
            
            db.session.commit()
            
            # Auto-login the donor
            session['donor_id'] = user_id
            session['user_type'] = 'donor'
            session.permanent = True
            session.modified = True
            
            flash("Registration successful! Welcome!", "success")
            return redirect(url_for('donor_dashboard', donor_id=user_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Registration failed: {str(e)}", "error")
            return redirect(url_for('donor_signup'))

    return render_template('donor_signup.html')

@app.route('/donor_login', methods=['GET', 'POST'])
def donor_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash("Email and password are required", "error")
            return redirect(url_for('donor_login'))
        
        try:
            query = """
            SELECT u.user_id, u.password_hash FROM users u 
            WHERE u.email = :email AND u.user_type = 'donor'
            """
            result = db.session.execute(text(query), {'email': email}).fetchone()
            
            if result:
                user_id = result[0]
                hashed_pw = result[1]
                
                if check_password_hash(hashed_pw, password):
                    session['donor_id'] = user_id
                    session['user_type'] = 'donor'
                    session.permanent = True
                    session.modified = True
                    flash("Login successful!", "success")
                    return redirect(url_for('donor_dashboard', donor_id=user_id))
                else:
                    flash("Invalid password", "error")
            else:
                flash("No account found with this email", "error")
        except Exception as e:
            flash(f"Login failed: {str(e)}", "error")
    
    return render_template('donor_login.html')

@app.route('/donor_dashboard/<donor_id>')
def donor_dashboard(donor_id):
    # Get donor_id from session (more reliable than URL parameter)
    session_donor_id = session.get('donor_id')
    
    print(f"\n[DASHBOARD] Loading for URL param: {donor_id}")
    print(f"[DASHBOARD] Session donor_id: {session_donor_id}")
    
    # If no session, redirect to login
    if not session_donor_id:
        print(f"[DASHBOARD] No session - redirecting to login")
        flash("Please login first", "error")
        return redirect(url_for('donor_login'))
    
    try:
        # Clear session cache to get fresh data from database
        db.session.expunge_all()
        
        # Use session donor_id for security
        query = """
        SELECT u.user_id, u.full_name, u.email, u.phone_number, d.blood_group, d.current_location, d.is_available
        FROM users u
        JOIN donor_profiles d ON u.user_id = d.user_id
        WHERE u.user_id = :uid AND u.user_type = 'donor'
        """
        donor_info = db.session.execute(text(query), {'uid': session_donor_id}).fetchone()
        
        if not donor_info:
            print(f"[DASHBOARD] Donor profile not found - redirecting to login")
            flash("Donor profile not found", "error")
            return redirect(url_for('donor_login'))
        
        print(f"[DASHBOARD] Loaded: {donor_info[1]} - is_available: {donor_info[6]}")
        
        response = make_response(render_template('donor_dashboard.html',
                             donor_id=session_donor_id,
                             donor_name=donor_info[1],
                             donor_email=donor_info[2],
                             donor_phone=donor_info[3],
                             donor_blood_group=donor_info[4],
                             donor_location=donor_info[5],
                             donor_available=donor_info[6]))
        
        # Prevent browser caching
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
    except Exception as e:
        print(f"[DASHBOARD] ERROR: {str(e)}")
        flash(f"Error loading profile: {str(e)}", "error")
        return redirect(url_for('donor_login'))

@app.route('/update_donor_availability_self/<donor_id>', methods=['POST'])
def update_donor_availability_self(donor_id):
    print(f"\n{'='*60}")
    print(f"[ENDPOINT CALLED] /update_donor_availability_self/{donor_id}")
    print(f"{'='*60}")
    
    # Check if user is logged in
    session_donor_id = session.get('donor_id')
    print(f"[LOG] Session donor_id: {session_donor_id}")
    print(f"[LOG] URL donor_id: {donor_id}")
    
    if not session_donor_id:
        print(f"[LOG] ERROR: No session donor_id")
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        print(f"[LOG] Clearing session cache...")
        db.session.expunge_all()
        
        print(f"[LOG] Querying current status...")
        result = db.session.execute(
            text("SELECT is_available FROM donor_profiles WHERE user_id = :uid"),
            {'uid': session_donor_id}
        ).fetchone()
        
        if not result:
            print(f"[LOG] ERROR: Donor profile not found")
            return jsonify({'success': False, 'message': 'Donor profile not found'})
        
        current_status = result[0]
        print(f"[LOG] Current status: {current_status}")
        
        new_status = not current_status
        print(f"[LOG] New status: {new_status}")
        
        print(f"[LOG] Executing UPDATE...")
        db.session.execute(
            text("UPDATE donor_profiles SET is_available = :status WHERE user_id = :uid"),
            {'status': new_status, 'uid': session_donor_id}
        )
        
        print(f"[LOG] Committing...")
        db.session.commit()
        print(f"[LOG] ✅ Commit successful")
        
        status_text = "Available" if new_status else "Not Available"
        print(f"[LOG] Returning success: {status_text}")
        print(f"{'='*60}\n")
        
        return jsonify({
            'success': True, 
            'message': f'Status updated to: {status_text}',
            'new_status': new_status,
            'status_text': status_text
        })
        
    except Exception as e:
        print(f"[LOG] ❌ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())
        db.session.rollback()
        print(f"{'='*60}\n")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/donor_logout')
def donor_logout():
    session.pop('donor_id', None)
    session.pop('user_type', None)
    flash("Logged out successfully", "success")
    return redirect(url_for('donate_blood'))

# ========== NGO PORTAL LOGIN CHECK ==========
@app.route('/ngo_portal_check', methods=['GET'])
def ngo_portal_check():
    # Redirect to NGO signup/login if not authenticated
    if session.get('user_type') == 'ngo':
        return redirect(url_for('ngo_portal', user_id=session['user_id']))
    return redirect(url_for('ngo_login'))

@app.route('/ngo_login', methods=['GET', 'POST'])
def ngo_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            query = """
            SELECT user_id, password_hash FROM users WHERE email = :email AND user_type = 'ngo'
            """
            result = db.session.execute(text(query), {'email': email}).fetchone()
            
            if result and check_password_hash(result[1], password):
                session['user_id'] = result[0]
                session['user_type'] = 'ngo'
                return redirect(url_for('ngo_portal', user_id=result[0]))
            else:
                flash("Invalid credentials", "error")
        except Exception as e:
            flash(f"Login failed: {str(e)}", "error")
    
    return render_template('ngo_login.html')

@app.route('/ngo_signup', methods=['GET', 'POST'])
def ngo_signup():
    if 'user_id' in session and session.get('user_type') == 'ngo':
        return redirect(url_for('ngo_portal', user_id=session['user_id']))
    
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        ngo_id = request.form.get('ngo_id')

        # Check for existing email
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

# ========== BLOOD REQUEST HANDLING ==========
@app.route('/create_blood_request', methods=['POST'])
def create_blood_request():
    # 1. Get data from the form (Hidden inputs in your HTML)
    patient_name = (request.form.get('patient_name') or 'Emergency Request').strip()
    required_blood_group = request.form.get('blood_group')
    hospital_location = request.form.get('location')
    
    # 2. Check if user is logged in (Optional: If you want anonymous requests, skip this)
    user_id = session.get('user_id') 
    donors = []
    
    try:
        # 3. Insert into blood_requests table
        query = """
        INSERT INTO blood_requests 
        (user_id, patient_name, required_blood_group, hospital_location, status, requested_at)
        VALUES (:uid, :pname, :bg, :loc, 'open', :ts)
        """
        db.session.execute(text(query), {
            'uid': user_id, # Can be None if anonymous
            'pname': patient_name,
            'bg': required_blood_group,
            'loc': hospital_location,
            'ts': datetime.utcnow()
        })
        db.session.commit()
        donors = find_available_compatible_donors(required_blood_group, hospital_location)
        if donors:
            flash(f"{len(donors)} compatible donor(s) found in your area.", "success")
        else:
            flash("Request posted! Donors in your area will be notified.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error creating request: {str(e)}", "error")
    
    return render_template('receive_blood.html', donors=donors, searched=True)

@app.route('/log_donation', methods=['POST'])
def log_donation():
    # Only NGOs or the Receiver should probably be able to do this, 
    # but for now, let's allow it to be triggered by the system.
    
    donor_id = request.form.get('donor_id')
    receiver_id = session.get('user_id') # The person logged in receiving blood
    location = request.form.get('location')
    
    if not receiver_id:
        flash("You must be logged in to confirm a donation received.", "error")
        return redirect(url_for('user_portal')) # Or login page

    try:
        # 1. Create the donation record
        query = """
        INSERT INTO donations (donor_id, receiver_id, donation_date, location, verified)
        VALUES (:did, :rid, :date, :loc, FALSE)
        """
        db.session.execute(text(query), {
            'did': donor_id,
            'rid': receiver_id,
            'date': datetime.utcnow().date(),
            'loc': location
        })
        
        # 2. Mark donor as unavailable (Optional: 3 month cooling period)
        update_query = "UPDATE donor_profiles SET is_available = FALSE WHERE user_id = :did"
        db.session.execute(text(update_query), {'did': donor_id})
        
        db.session.commit()
        flash("Donation recorded! Waiting for NGO verification.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error logging donation: {str(e)}", "error")
        
    return redirect(url_for('index'))

@app.route('/verify_donation/<int:donation_id>', methods=['POST'])
def verify_donation(donation_id):
    if session.get('user_type') != 'ngo':
        flash("Unauthorized", "error")
        return redirect(url_for('ngo_login'))
        
    ngo_id = session.get('user_id')
    
    try:
        query = """
        UPDATE donations 
        SET verified = TRUE, ngo_id = :nid 
        WHERE donation_id = :did
        """
        db.session.execute(text(query), {'nid': ngo_id, 'did': donation_id})
        db.session.commit()
        
        flash("Donation verified successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Verification failed: {str(e)}", "error")
        
    return redirect(url_for('ngo_portal', user_id=ngo_id))

# ========== NGO PORTAL ==========
@app.route('/ngo_portal/<user_id>')
def ngo_portal(user_id):
    if str(session.get('user_id')) != str(user_id) or session.get('user_type') != 'ngo':
        flash("Login as NGO first", "error")
        return redirect(url_for('ngo_login'))
    
    # Clear SQLAlchemy session cache to get fresh data from database
    db.session.expunge_all()
    
    # Fetch all donors with their complete donation history
    donors = []
    donations = []
    search_query = None
    
    try:
        # Get all donors with latest info - force fresh query
        donors_query = """
        SELECT u.user_id, u.full_name, u.email, d.blood_group, d.current_location, u.phone_number, d.is_available
        FROM users u 
        JOIN donor_profiles d ON u.user_id = d.user_id
        WHERE u.user_type = 'donor'
        ORDER BY u.full_name
        """
        donors = db.session.execute(text(donors_query)).fetchall()
        
        # Try to get all donations with donor info (donations table may not exist)
        try:
            donations_query = """
            SELECT 
                d.donation_id, 
                d.donation_date, 
                d.location, 
                d.verified,
                u.full_name AS donor_name,
                u.email AS donor_email,
                u.phone_number AS donor_phone,
                dp.blood_group
            FROM donations d
            JOIN users u ON d.donor_id = u.user_id
            JOIN donor_profiles dp ON u.user_id = dp.user_id
            ORDER BY d.donation_date DESC
            """
            donations = db.session.execute(text(donations_query)).fetchall()
        except Exception as donation_error:
            # If donations table doesn't exist, continue without it
            donations = []
    except Exception as e:
        flash(f"Error loading data: {str(e)}", "error")
    
    response = make_response(render_template('ngo_portal_new.html', 
                         donors=donors, 
                         donations=donations, 
                         user_id=user_id,
                         search_query=search_query))
    
    # Prevent caching to always get fresh data
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response

@app.route('/search_donors_ngo/<user_id>', methods=['POST'])
def search_donors_ngo(user_id):
    if str(session.get('user_id')) != str(user_id) or session.get('user_type') != 'ngo':
        flash("Unauthorized", "error")
        return redirect(url_for('ngo_login'))
    
    # Clear SQLAlchemy session cache to get fresh data from database
    db.session.expunge_all()
    
    search_query = request.form.get('search_query', '').strip()
    donors = []
    donations = []
    
    try:
        if search_query:
            # Search donors by name or email
            donors_query = """
            SELECT u.user_id, u.full_name, u.email, d.blood_group, d.current_location, u.phone_number, d.is_available
            FROM users u 
            JOIN donor_profiles d ON u.user_id = d.user_id
            WHERE (LOWER(u.full_name) LIKE LOWER(:query) OR LOWER(u.email) LIKE LOWER(:query))
            AND u.user_type = 'donor'
            ORDER BY u.full_name
            """
            donors = db.session.execute(text(donors_query), {'query': f"%{search_query}%"}).fetchall()
            
            # Try to get donations for searched donors (donations table may not exist)
            if donors:
                try:
                    donor_ids = [d[0] for d in donors]
                    placeholders = ','.join([str(did) for did in donor_ids])
                    donations_query = f"""
                    SELECT 
                        d.donation_id, 
                        d.donation_date, 
                        d.location, 
                        d.verified,
                        u.full_name AS donor_name,
                        u.email AS donor_email,
                        u.phone_number AS donor_phone,
                        dp.blood_group
                    FROM donations d
                    JOIN users u ON d.donor_id = u.user_id
                    JOIN donor_profiles dp ON u.user_id = dp.user_id
                    WHERE d.donor_id IN ({placeholders})
                    ORDER BY d.donation_date DESC
                    """
                    donations = db.session.execute(text(donations_query)).fetchall()
                except Exception as donation_error:
                    # If donations table doesn't exist, continue without it
                    donations = []
        else:
            # Get all if no search
            donors_query = """
            SELECT u.user_id, u.full_name, u.email, d.blood_group, d.current_location, u.phone_number, d.is_available
            FROM users u 
            JOIN donor_profiles d ON u.user_id = d.user_id
            WHERE u.user_type = 'donor'
            ORDER BY u.full_name
            """
            donors = db.session.execute(text(donors_query)).fetchall()
            
            # Try to get all donations (donations table may not exist)
            try:
                donations_query = """
                SELECT 
                    d.donation_id, 
                    d.donation_date, 
                    d.location, 
                    d.verified,
                    u.full_name AS donor_name,
                    u.email AS donor_email,
                    u.phone_number AS donor_phone,
                    dp.blood_group
                FROM donations d
                JOIN users u ON d.donor_id = u.user_id
                JOIN donor_profiles dp ON u.user_id = dp.user_id
                ORDER BY d.donation_date DESC
                """
                donations = db.session.execute(text(donations_query)).fetchall()
            except Exception as donation_error:
                # If donations table doesn't exist, continue without it
                donations = []
    except Exception as e:
        flash(f"Search failed: {str(e)}", "error")
    
    response = make_response(render_template('ngo_portal_new.html', 
                         donors=donors, 
                         donations=donations, 
                         user_id=user_id,
                         search_query=search_query))
    
    # Prevent caching to always get fresh data
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
