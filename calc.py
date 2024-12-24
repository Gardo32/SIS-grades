import requests
import tkinter as tk
from tkinter import messagebox, ttk, PhotoImage
from bs4 import BeautifulSoup
import re
import psycopg2
import random
import sv_ttk  # Add this import
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

class ProgressCalculator:
    def __init__(self):
        self.session = requests.Session()
        db_url = os.getenv("DATABASE_URL")
        self.conn = psycopg2.connect(db_url)
        self.cursor = self.conn.cursor()

    def login_to_nvtc(self, username, password):
        url = "https://sis.nvtc.edu.bh/site/login"
        payload = {
            "username": username,
            "password": password,
            "LoginForm[rememberMe]": "0",
            "yt0": "Login"
        }
        response = self.session.post(url, data=payload)
        response.raise_for_status()

    def fetch_progress_data(self, nv_number):
        url = "https://sis.nvtc.edu.bh/courseActivityStudent/progress_current_semester/"
        payload = {
            "sid": f"+{nv_number}",
            "yt0": "Show Progress report",
            "type_op": "2"
        }
        response = self.session.post(url, data=payload)
        response.raise_for_status()
        return response.text

    def fetch_points_and_absents(self):
        url = "https://sis.nvtc.edu.bh/site/index"
        response = self.session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        points = soup.find('div', class_='small-box bg-green').find('h3').get_text(strip=True).split()[0]
        points = points[:-5] + " " + points[-5:]
        absents = soup.find('div', class_='small-box bg-red').find('h3').get_text(strip=True).split()[0]
        absents = absents[:-3] + " " + absents[-3:]
        return {'points': points, 'absents': absents}

    def parse_progress_data(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        student_info = {}
        info_table = soup.find('table', {'class': 'table_mo2'})
        if info_table:
            for row in info_table.find_all('tr'):
                for cell in row.find_all('td'):
                    text = cell.get_text(strip=True)
                    if ':' in text:
                        key, value = text.split(':', 1)
                        student_info[key.strip()] = value.strip()
        grades_data = []
        grades_table = soup.find('table', {'class': 'table table-bordered table-striped'})
        if grades_table:
            for row in grades_table.find_all('tr')[1:]:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    grades_data.append({
                        'Course Code': cells[0].text.strip(),
                        'Course Name': cells[1].text.strip(),
                        'Mark': cells[2].text.strip(),
                        'Mark in %': cells[3].text.strip()
                    })
        return {'student_info': student_info, 'grades': grades_data}

    def final_exam_mark_estimation(self, start, finish, mark):
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

    def calculate_gpa(self, grades_data):
        total_weighted_grades = 0
        total_hours = 0
        for grade in grades_data:
            course_code = grade['Course Code']
            mark_in_percent = grade['Mark in %']
            try:
                mark = float(mark_in_percent)
            except (ValueError, TypeError):
                continue
            hours = self.get_course_hours(course_code)
            if hours is None:
                continue
            weighted_grade = mark * hours
            total_weighted_grades += weighted_grade
            total_hours += hours
        if total_hours == 0:
            return 0
        return total_weighted_grades / total_hours

    def calculate_predictive_gpa(self, grades_data, final_exam_min, final_exam_max):
        total_weighted_grades = 0
        total_courses = 0
        for grade in grades_data:
            course_code = grade['Course Code']
            mark_string = grade['Mark']
            match = re.match(r'(\d+)/(50|60)', mark_string)
            if match:
                mark = int(match.group(1))
                max_grade = int(match.group(2))
            else:
                continue
            estimated_mark = self.final_exam_mark_estimation(final_exam_min, final_exam_max, mark)
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

    def calculate_potential_gpa(self, grades_data):
        total_weighted_grades = 0
        total_hours = 0
        for grade in grades_data:
            course_code = grade['Course Code']
            mark_string = grade['Mark']
            match = re.match(r'(\d+)/(50|60|30)', mark_string)
            if match:
                mark = int(match.group(1))
                max_grade = int(match.group(2))
            else:
                continue
            if max_grade == 50:
                adjusted_grade = mark + 50
            elif max_grade == 60:
                adjusted_grade = mark + 40
            elif max_grade == 30:
                adjusted_grade = mark + 70
            else:
                continue
            hours = self.get_course_hours(course_code)
            if hours is None:
                continue
            weighted_grade = adjusted_grade * hours
            total_weighted_grades += weighted_grade
            total_hours += hours
        if total_hours == 0:
            return 0
        return total_weighted_grades / total_hours

    def get_course_hours(self, course_code):
        query = "SELECT hours FROM subject_hours WHERE subject = %s"
        self.cursor.execute(query, (course_code,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def clear_session(self):
        self.session.cookies.clear()

class ProgressViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("NCST SIS Grades Calculator")
        self.root.geometry("900x800")
        self.root.minsize(800, 600)  # Set minimum window size
        
        # Set application icon
        try:
            icon = PhotoImage(file='images.png')
            self.root.iconphoto(True, icon)
        except Exception as e:
            print(f"Could not load icon: {e}")
            
        # Apply the dark theme
        sv_ttk.set_theme("dark")
        
        # Configure root grid
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        
        self.calculator = ProgressCalculator()
        self.setup_ui()

    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        # Configure main frame grid
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(2, weight=1)  # Make results area expandable

        # Login area
        login_frame = ttk.LabelFrame(main_frame, text="Login", padding="5")
        login_frame.grid(row=0, column=0, sticky="new", padx=5, pady=5)
        
        ttk.Label(login_frame, text="Username (NV Number):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.username_entry = ttk.Entry(login_frame, width=30)
        self.username_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        
        ttk.Label(login_frame, text="Password:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.password_entry = ttk.Entry(login_frame, show="*", width=30)
        self.password_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        
        ttk.Button(login_frame, text="Login to SIS", command=self.login_to_nvtc).grid(row=2, column=0, columnspan=2, pady=10)

        # GPA Settings area
        gpa_frame = ttk.LabelFrame(main_frame, text="GPA Settings", padding="5")
        gpa_frame.grid(row=0, column=1, sticky="new", padx=5, pady=5)
        
        ttk.Label(gpa_frame, text="Final Exam Min Error:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.final_exam_min_entry = ttk.Entry(gpa_frame, width=10)
        self.final_exam_min_entry.insert(0, "0")
        self.final_exam_min_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        ttk.Label(gpa_frame, text="Final Exam Max Error:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.final_exam_max_entry = ttk.Entry(gpa_frame, width=10)
        self.final_exam_max_entry.insert(0, "1")
        self.final_exam_max_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        ttk.Button(gpa_frame, text="Fetch Results", command=self.fetch_results).grid(row=2, column=0, columnspan=2, pady=10)

        # Results area
        self.results_frame = ttk.Frame(main_frame)
        self.results_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=10)
        self.results_frame.grid_columnconfigure(0, weight=1)
        self.results_frame.grid_rowconfigure(2, weight=1)  # Make treeview expandable

        # Configure all frames to be expandable
        for frame in [login_frame, gpa_frame]:
            frame.grid_columnconfigure(1, weight=1)

    def login_to_nvtc(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            messagebox.showerror("Input Error", "Please provide both username and password")
            return

        try:
            self.calculator.login_to_nvtc(username, password)
            messagebox.showinfo("Success", "Logged in successfully")
        except requests.RequestException as e:
            messagebox.showerror("Error", f"Failed to login: {str(e)}")

    def fetch_results(self):
        nv_number = self.username_entry.get().strip()

        if not self.validate_nv_number(nv_number):
            messagebox.showerror("Input Error", "Please enter a valid NV number (e.g., nv22084)")
            return

        try:
            html_content = self.calculator.fetch_progress_data(nv_number)
            if html_content:
                progress_data = self.calculator.parse_progress_data(html_content)
                additional_data = self.calculator.fetch_points_and_absents()
                progress_data.update(additional_data)

                # Use the new method for GPA
                gpa = self.calculator.calculate_gpa(progress_data['grades'])
                progress_data['GPA'] = f"{gpa:.2f}"

                # Use the predictive GPA calculation
                final_exam_min = int(self.final_exam_min_entry.get().strip())
                final_exam_max = int(self.final_exam_max_entry.get().strip())
                predictive_gpa = self.calculator.calculate_predictive_gpa(progress_data['grades'], final_exam_min, final_exam_max)
                progress_data['Predictive GPA'] = f"{predictive_gpa:.2f}"

                # Use the old method for Potential GPA
                potential_gpa = self.calculator.calculate_potential_gpa(progress_data['grades'])
                progress_data['Potential GPA'] = f"{potential_gpa:.2f}"

                self.display_results(progress_data)
        except requests.RequestException as e:
            messagebox.showerror("Connection Error", f"Failed to fetch data: {str(e)}")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")

    def validate_nv_number(self, nv_number):
        return bool(re.match(r'^nv\d{5}$', nv_number.lower()))

    def display_results(self, data):
        # Clear previous results
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        # Create info frame with grid
        info_frame = ttk.LabelFrame(self.results_frame, text="Student Information", padding="5")
        info_frame.grid(row=0, column=0, sticky="ew", pady=5)
        info_frame.grid_columnconfigure(1, weight=1)

        # Display student info in 2 columns
        row = 0
        col = 0
        for key, value in data['student_info'].items():
            ttk.Label(info_frame, text=f"{key}:").grid(row=row, column=col*2, sticky="w", padx=5)
            ttk.Label(info_frame, text=value).grid(row=row, column=col*2+1, sticky="w", padx=5)
            col = (col + 1) % 2
            if col == 0:
                row += 1

        # GPA information
        gpa_info = ttk.LabelFrame(self.results_frame, text="GPA Information", padding="5")
        gpa_info.grid(row=1, column=0, sticky="ew", pady=5)
        gpa_info.grid_columnconfigure(1, weight=1)
        gpa_info.grid_columnconfigure(3, weight=1)

        # Display GPAs in 2 columns
        ttk.Label(gpa_info, text="Current GPA:").grid(row=0, column=0, sticky="w", padx=5)
        ttk.Label(gpa_info, text=data['GPA']).grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(gpa_info, text="Predictive GPA:").grid(row=0, column=2, sticky="w", padx=5)
        self.predictive_gpa_label = ttk.Label(gpa_info, text=data['Predictive GPA'])
        self.predictive_gpa_label.grid(row=0, column=3, sticky="w", padx=5)
        ttk.Label(gpa_info, text="Potential GPA:").grid(row=1, column=0, sticky="w", padx=5)
        ttk.Label(gpa_info, text=data['Potential GPA']).grid(row=1, column=1, sticky="w", padx=5)
        
        # Add recalculate button
        ttk.Button(gpa_info, text="Recalculate Predictive", 
                  command=lambda: self.recalculate_predictive(data['grades'])).grid(
                      row=1, column=2, columnspan=2, sticky="e", padx=5, pady=5)

        # Grades table with scrollbar
        table_frame = ttk.Frame(self.results_frame)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        columns = ('Course Code', 'Course Name', 'Hours', 'Mark', 'Mark in %')
        tree = ttk.Treeview(table_frame, columns=columns, show='headings')
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        
        tree.configure(yscrollcommand=scrollbar.set)
        
        # Configure columns with proportional widths
        widths = [100, 250, 70, 70, 70]
        for col, width in zip(columns, widths):
            tree.heading(col, text=col)
            tree.column(col, width=width, minwidth=50)

        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Add data
        for grade in data['grades']:
            course_code = grade['Course Code']
            hours = self.calculator.get_course_hours(course_code)
            hours = hours if hours is not None else 'N/A'
            
            tree.insert('', "end", values=(
                grade['Course Code'],
                grade['Course Name'],
                hours,
                grade['Mark'],
                grade['Mark in %']
            ))

    def recalculate_predictive(self, grades_data):
        try:
            final_exam_min = int(self.final_exam_min_entry.get().strip())
            final_exam_max = int(self.final_exam_max_entry.get().strip())
            predictive_gpa = self.calculator.calculate_predictive_gpa(grades_data, final_exam_min, final_exam_max)
            if predictive_gpa is not None:  # Check if calculation was successful
                self.predictive_gpa_label.config(text=f"{predictive_gpa:.2f}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to recalculate: {str(e)}")

# Create the Tkinter window and start the app
if __name__ == "__main__":
    root = tk.Tk()
    app = ProgressViewer(root)
    root.mainloop()
