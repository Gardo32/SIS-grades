from flask import Flask, render_template, request, redirect, url_for, flash, session
from calc import ProgressCalculator
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Use a static secret key in production
calculator = ProgressCalculator()

@app.route("/")
def index():
    return render_template("index.html", title="Login")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        # Assuming you have a function to validate the user
        if validate_user(username, password):
            session["username"] = username
            session["password"] = password
            return redirect(url_for("profile"))
    return render_template("login.html")

@app.route("/calculate", methods=["POST"])
def calculate():
    username = request.form["username"]
    password = request.form["password"]
    final_exam_min = int(request.form["final_exam_min"])
    final_exam_max = int(request.form["final_exam_max"])

    try:
        calculator.login_to_nvtc(username, password)
        html_content = calculator.fetch_progress_data(username)
        progress_data = calculator.parse_progress_data(html_content)
        additional_data = calculator.fetch_points_and_absents()
        progress_data.update(additional_data)

        gpa = calculator.calculate_gpa(progress_data['grades'])
        progress_data['GPA'] = f"{gpa:.2f}"

        predictive_gpa = calculator.calculate_predictive_gpa(progress_data['grades'], final_exam_min, final_exam_max)
        progress_data['Predictive_GPA'] = f"{predictive_gpa:.2f}"

        potential_gpa = calculator.calculate_potential_gpa(progress_data['grades'])
        progress_data['Potential_GPA'] = f"{potential_gpa:.2f}"

        # Store calculation parameters in session for recalculation
        session['username'] = username
        session['password'] = password

        return render_template("results.html", 
                            title="Results", 
                            results=progress_data,
                            username=username,
                            final_exam_min=final_exam_min,
                            final_exam_max=final_exam_max)
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("index"))

@app.route("/recalculate", methods=["POST"])
def recalculate():
    username = request.form["username"]
    final_exam_min = int(request.form["final_exam_min"])
    final_exam_max = int(request.form["final_exam_max"])

    try:
        calculator.login_to_nvtc(session['username'], session['password'])
        return redirect(url_for('calculate'), code=307)  # 307 preserves POST method
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.pop("username", None)
    session.pop("password", None)
    calculator.clear_session()
    return redirect(url_for("login"))

@app.route("/profile")
def profile():
    if "username" in session:
        username = session["username"]
        # Fetch user data based on the username
        user_data = get_user_data(username)
        return render_template("profile.html", user=user_data)
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
