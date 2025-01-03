from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import random
import time  # Add this import at the top
from werkzeug.utils import secure_filename
import os
from datetime import timedelta
from functools import wraps

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
app.secret_key = 'your-secure-secret-key-here'  # Change this to a secure key

# Create uploads directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'html'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def format_headers(raw_headers):
    """Process raw header input and return a properly formatted dictionary."""
    headers = {}
    for line in raw_headers.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
    return headers

def send_payload(nv_number, raw_headers):
    url = "https://sis.nvtc.edu.bh/courseActivityStudent/progress_current_semester/"
    payload = {
        "sid": f"+{nv_number}",
        "yt0": "Show Progress report",
        "type_op": "2"
    }
    headers = format_headers(raw_headers)

    try:
        response = requests.post(url, data=payload, headers=headers)
        if response.status_code == 200:
            return response.text
        else:
            return f"Error: Received status code {response.status_code}"
    except requests.RequestException as e:
        return f"An error occurred: {e}"

def extract_table_data(html):
    soup = BeautifulSoup(html, "html.parser")
    tbody = soup.find("tbody")

    if not tbody:
        return []

    data = []
    rows = tbody.find_all("tr")
    for row in rows:
        columns = row.find_all("td")
        if len(columns) >= 4:
            data.append({
                "code": columns[0].text.strip(),
                "name": columns[1].text.strip(),
                "mark": columns[2].text.strip(),
                "percentage": columns[3].text.strip()
            })

    return data

def calculate_gpa(grades_data):
    total_weighted_grades = 0
    total_courses = 0
    for grade in grades_data:
        mark_percent = grade['percentage']
        try:
            mark = float(mark_percent)
            weighted_grade = mark
            total_weighted_grades += weighted_grade
            total_courses += 1
        except (ValueError, TypeError):
            continue
    
    if total_courses == 0:
        return 0
    return total_weighted_grades / total_courses

def calculate_potential_gpa(grades_data):
    total_weighted_grades = 0
    total_courses = 0
    for grade in grades_data:
        mark_string = grade['mark']
        match = re.match(r'(\d+)/(50|60|30)', mark_string)
        if match:
            mark = int(match.group(1))
            max_grade = int(match.group(2))
            
            if max_grade == 50:
                adjusted_grade = mark + 50
            elif max_grade == 60:
                adjusted_grade = mark + 40
            elif max_grade == 30:
                adjusted_grade = mark + 70
            else:
                continue
                
            total_weighted_grades += adjusted_grade
            total_courses += 1
            
    if total_courses == 0:
        return 0
    return total_weighted_grades / total_courses

def final_exam_mark_estimation(start, finish, mark):
    if start > finish:
        raise ValueError("Start should be less than or equal to finish.")
    range_size = finish - start + 1
    weights = []
    for i in range(start, finish + 1):
        weight = 1 / (abs(i - start) + 1)
        weights.append(weight)
    total_weight = sum(weights)
    normalized_weights = [w / total_weight for w in weights]
    selected_number = random.choices(range(start, finish + 1), weights=normalized_weights, k=1)[0]
    return selected_number

def calculate_predictive_gpa(grades_data, final_exam_min=0, final_exam_max=1):
    total_weighted_grades = 0
    total_courses = 0
    for grade in grades_data:
        mark_string = grade['mark']
        match = re.match(r'(\d+)/(50|60)', mark_string)
        if match:
            mark = int(match.group(1))
            max_grade = int(match.group(2))
            estimated_mark = final_exam_mark_estimation(final_exam_min, final_exam_max, mark)
            if max_grade == 50:
                adjusted_grade = mark - estimated_mark + 50
            elif max_grade == 60:
                adjusted_grade = mark - estimated_mark + 40
            else:
                continue
            weighted_grade = adjusted_grade
            total_weighted_grades += weighted_grade
            total_courses += 1
    if total_courses == 0:
        return 0
    return total_weighted_grades / total_courses

def extract_history_data(html):
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract student info
        student_info = {
            'sid': '',
            'name_en': '',
            'major': '',
            'status': ''
        }
        
        info_table = soup.find('table', {'class': 'table_mo2'})
        if info_table:
            rows = info_table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if 'SID:' in text:
                        student_info['sid'] = text.split('SID:')[1].strip()
                    elif 'Student Name En:' in text:
                        student_info['name_en'] = text.split('Student Name En:')[1].strip()
                    elif 'Major:' in text:
                        student_info['major'] = text.split('Major:')[1].strip()
                    elif 'Status:' in text:
                        student_info['status'] = text.split('Status:')[1].strip()

        # Extract semesters
        semesters = []
        total_gpa = 0
        semester_count = 0
        boxes = soup.find_all('div', {'class': 'box'})
        
        # Skip the first box by starting from index 1
        for box in boxes[1:]:
            semester_data = {}
            grades_table = box.find('table', {'class': 'table table-bordered table-striped'})
            
            if grades_table and box.find('div', {'class': 'box-header'}):  # Only process if it has a header and table
                header = box.find('div', {'class': 'box-header'})
                semester_data['title'] = header.get_text(strip=True)
                
                # Extract grades
                grades = []
                tbody = grades_table.find('tbody')
                if tbody:
                    rows = tbody.find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 7:
                            grade = {
                                'code': cells[0].text.strip(),
                                'name': cells[1].text.strip(),
                                'grade': cells[2].text.strip(),
                                'crh': cells[3].text.strip(),
                                'pass_grade': cells[4].text.strip(),
                                'status': cells[5].text.strip(),
                                'note': cells[6].text.strip()
                            }
                            grades.append(grade)
                    semester_data['grades'] = grades
                
                # Extract GPA
                footer = grades_table.find('tfoot')
                if footer:
                    gpa_cell = footer.find('td', class_='grid-footer', style='text-align:center;border:none !important;')
                    if gpa_cell:
                        gpa_text = gpa_cell.get_text(strip=True)
                        first_gpa = gpa_text.split('%')[0].strip()
                        try:
                            gpa_value = float(first_gpa)
                            total_gpa += gpa_value
                            semester_count += 1
                            semester_data['gpas'] = [f"{gpa_value:.2f}%"]
                        except ValueError:
                            pass

                if semester_data.get('grades'):
                    semesters.append(semester_data)

        # Calculate cumulative GPA
        cum_gpa = f"{(total_gpa / semester_count):.2f}" if semester_count > 0 else "0.00"

        return {
            'student_info': student_info,
            'semesters': semesters,
            'cum_gpa': cum_gpa
        }
    except Exception as e:
        print(f"Error extracting history data: {str(e)}")
        return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index', error="Please login first"))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/upload')
@login_required  # Add login protection
def upload():
    return render_template('history_upload.html')

@app.route('/history', methods=['GET', 'POST'])
@login_required
def history():
    if request.method == 'GET':
        return render_template('history_upload.html')
        
    if 'file' not in request.files:
        return redirect(url_for('index', error="No file uploaded"))
    
    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('index', error="No file selected"))
        
    if file and allowed_file(file.filename):
        html_content = file.read().decode('utf-8')
        data = extract_history_data(html_content)
        if data:
            # Get current results GPA values from session
            current_gpa = session.get('current_gpa', 0)
            predictive_gpa = session.get('predictive_gpa', 0)
            
            # Calculate GPAs
            cum_gpa = float(data['cum_gpa'])
            num_semesters = len(data['semesters'])
            
            # Calculate predictive cumulative GPA
            pred_cum_gpa = ((cum_gpa * num_semesters) + float(predictive_gpa)) / (num_semesters + 1)
            
            # Calculate potential cumulative GPA
            pot_cum_gpa = ((cum_gpa * num_semesters) + 100) / (num_semesters + 1)
            
            # Add to data dictionary
            data['pred_cum_gpa'] = f"{pred_cum_gpa:.2f}"
            data['pot_cum_gpa'] = f"{pot_cum_gpa:.2f}"
            
            return render_template('history.html', data=data)
        else:
            return redirect(url_for('index', error="Could not extract history data from the file."))
            
    return redirect(url_for('index', error="Invalid file type"))

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('results'))
    return render_template('index.html', error=request.args.get('error'))

@app.route('/submit', methods=['POST'])
def submit():
    nv_number = request.form.get('nv_number')
    headers = request.form.get('headers')

    if not nv_number or not headers:
        return redirect(url_for('index', error="Please fill in all fields"))

    if not nv_number.startswith("nv") or len(nv_number) < 6:
        return redirect(url_for('index', error="Please enter a valid NV number (e.g., nvXXXXX)"))

    # Try to fetch data first before setting session
    result = send_payload(nv_number, headers)
    if result.startswith("Error") or result.startswith("An error occurred"):
        return redirect(url_for('index', error=result))

    data = extract_table_data(result)
    if not data:
        return redirect(url_for('index', error="No data found. Please check your credentials."))

    # Store both user_id and nv_number
    session['user_id'] = nv_number
    session['nv_number'] = nv_number  # Keep this for compatibility
    session['headers'] = headers
    session.permanent = True

    return redirect(url_for('results'))

@app.route('/results')
@login_required
def results():
    user_id = session.get('user_id')  # Changed from nv_number
    headers = session.get('headers')

    if not user_id or not headers:
        return redirect(url_for('index'))

    result = send_payload(user_id, headers)  # Using user_id instead of nv_number

    if result.startswith("Error") or result.startswith("An error occurred"):
        return redirect(url_for('index', error=result))

    data = extract_table_data(result)
    if data:
        current_gpa = calculate_gpa(data)
        potential_gpa = calculate_potential_gpa(data)
        predictive_gpa = calculate_predictive_gpa(data)
        
        # Store in session for history page
        session['current_gpa'] = current_gpa
        session['predictive_gpa'] = predictive_gpa
        
        return render_template('results.html', 
                             data=data, 
                             current_gpa=f"{current_gpa:.2f}", 
                             potential_gpa=f"{potential_gpa:.2f}",
                             predictive_gpa=f"{predictive_gpa:.2f}")
    else:
        return redirect(url_for('index', error="No table data found in the response."))

@app.route('/recalculate', methods=['POST'])
@login_required
def recalculate():
    """Handle GPA recalculations based on edited marks"""
    try:
        data = request.get_json()
        grades_data = []
        
        for grade in data['grades']:
            grades_data.append({
                'code': grade['code'],
                'name': grade['name'],
                'mark': grade['mark'],
                'percentage': calculate_mark_percentage(grade['mark'])
            })

        current_gpa = calculate_gpa(grades_data)
        potential_gpa = calculate_potential_gpa(grades_data)
        predictive_gpa = calculate_predictive_gpa(grades_data)

        return jsonify({
            'current_gpa': f"{current_gpa:.2f}",
            'potential_gpa': f"{potential_gpa:.2f}",
            'predictive_gpa': f"{predictive_gpa:.2f}",
            'percentages': {grade['code']: grade['percentage'] for grade in grades_data}
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

def calculate_mark_percentage(mark_str):
    """Calculate percentage from mark string"""
    match = re.match(r'(\d+)/(50|60|30)', mark_str)
    if match:
        mark = int(match.group(1))
        max_grade = int(match.group(2))
        
        if max_grade == 50:
            percentage = ((mark + 50) / 100) * 100
        elif max_grade == 60:
            percentage = ((mark + 40) / 100) * 100
        elif max_grade == 30:
            percentage = ((mark + 70) / 100) * 100
        else:
            return "0"
            
        return f"{percentage:.2f}"
    return "0"

@app.route('/logout')
def logout():
    # Properly handle logout
    if 'user_id' in session:
        session.clear()
    return redirect(url_for('index'))

@app.before_request
def make_session_permanent():
    session.permanent = True

# Don't forget to add a secret key for session management
app.secret_key = 'your-secret-key-here'  # Change this to a secure secret key

@app.route('/finals')
@login_required
def finals():
    user_id = session.get('user_id')
    headers = session.get('headers')

    if not user_id or not headers:
        return redirect(url_for('index'))

    result = send_payload(user_id, headers)

    if result.startswith("Error") or result.startswith("An error occurred"):
        return redirect(url_for('index', error=result))

    data = extract_table_data(result)
    if data:
        return render_template('finals.html', data=data)
    else:
        return redirect(url_for('index', error="No table data found in the response."))

def calculate_finals_gpa(grades_data):
    """Calculate GPA based on total marks out of 100"""
    total_marks = 0
    total_courses = 0
    for grade in grades_data:
        try:
            total = int(grade['total'])
            if 0 <= total <= 100:  # Validate total is in valid range
                total_marks += total
                total_courses += 1
        except (ValueError, KeyError):
            continue
    
    if total_courses == 0:
        return 0
    return total_marks / total_courses

def calculate_finals_current_gpa(grades_data):
    """Calculate current GPA from finals totals"""
    total_marks = 0
    total_courses = 0
    for grade in grades_data:
        try:
            total = int(grade['total'])
            if 0 <= total <= 100:
                total_marks += total
                total_courses += 1
        except (ValueError, KeyError):
            continue
    
    if total_courses == 0:
        return 0
    return total_marks / total_courses

def calculate_finals_predictive_gpa(grades_data, error_min, error_max):
    """Calculate predictive GPA with error range"""
    total_marks = 0
    total_courses = 0
    for grade in grades_data:
        try:
            total = int(grade['total'])
            if 0 <= total <= 100:
                error = random.randint(error_min, error_max)
                adjusted_total = max(0, total - error)
                total_marks += adjusted_total
                total_courses += 1
        except (ValueError, KeyError):
            continue
    
    if total_courses == 0:
        return 0
    return total_marks / total_courses

def calculate_finals_potential_gpa(grades_data):
    """Calculate potential GPA assuming maximum remaining marks"""
    total_marks = 0
    total_courses = 0
    for grade in grades_data:
        try:
            coursework = int(grade['coursework'])
            finals_max = int(grade['finals_max'])
            total = coursework + finals_max
            if 0 <= total <= 100:
                total_marks += total
                total_courses += 1
        except (ValueError, KeyError):
            continue
    
    if total_courses == 0:
        return 0
    return total_marks / total_courses

@app.route('/calculate_finals_gpas', methods=['POST'])
@login_required
def calculate_finals_gpas_route():
    try:
        data = request.get_json()
        error_min = int(data.get('error_min', 0))
        error_max = int(data.get('error_max', 5))
        
        current = calculate_finals_current_gpa(data['grades'])
        predictive = calculate_finals_predictive_gpa(data['grades'], error_min, error_max)
        potential = calculate_finals_potential_gpa(data['grades'])
        
        return jsonify({
            'current_gpa': f"{current:.2f}",
            'predictive_gpa': f"{predictive:.2f}",
            'potential_gpa': f"{potential:.2f}"
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)