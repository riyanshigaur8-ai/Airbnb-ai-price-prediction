from flask import Flask, render_template, request, redirect, session
from joblib import load
import pandas as pd
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secret123"

# ================= LOAD MODEL ================= #
model = load("model/model.pkl")
columns = load("model/columns.pkl")

# ================= DATABASE ================= #
def get_db():
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    conn = get_db()

    # Users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)

    # Predictions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            location TEXT,
            room_type TEXT,
            price REAL
        )
    """)

    conn.commit()
    conn.close()

create_tables()

# ================= AUTH ================= #

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        phone = request.form["phone"]
        age = request.form["age"]
        password = generate_password_hash(request.form["password"])

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (username, email, phone, age, password) VALUES (?, ?, ?, ?, ?)",
                (username, email, phone, age, password)
            )
            conn.commit()
            return redirect("/login")
        except:
            return "User already exists"
        finally:
            conn.close()

    return render_template("register.html", error="User already exists")




@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user"] = username
            return redirect("/dashboard")
        else:
            return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/bookings")
def bookings():
    if "user" not in session:
        return redirect("/login")
    return render_template("bookings.html")

@app.route("/profile", methods=["POST"])
def profile():
    if "user" not in session:
        return redirect("/login")

    email = request.form["email"]
    phone = request.form["phone"]
    age = request.form["age"]

    conn = get_db()
    conn.execute(
        "UPDATE users SET email=?, phone=?, age=? WHERE username=?",
        (email, phone, age, session["user"])
    )
    conn.commit()
    conn.close()

    return redirect("/profile")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

# ================= DASHBOARD ================= #

@app.route('/dashboard', methods=['GET'])
def dashboard():
    if 'user' not in session:
        return redirect('/login')

    try:
        import plotly.express as px

        df = pd.read_csv('data/AB_NYC_2019.csv')

        # Filters
        location = request.args.get('location')
        room_type = request.args.get('room_type')
        min_price = request.args.get('min_price')
        max_price = request.args.get('max_price')

        if location and location != "All":
            df = df[df['neighbourhood_group'] == location]

        if room_type and room_type != "All":
            df = df[df['room_type'] == room_type]

        if min_price:
            df = df[df['price'] >= float(min_price)]

        if max_price:
            df = df[df['price'] <= float(max_price)]

        # Graphs
        fig1 = px.histogram(df, x="price", nbins=50)

        room_counts = df['room_type'].value_counts().reset_index()
        room_counts.columns = ['room_type', 'count']
        fig2 = px.bar(room_counts, x='room_type', y='count')

        loc_counts = df['neighbourhood_group'].value_counts().reset_index()
        loc_counts.columns = ['location', 'count']
        fig3 = px.bar(loc_counts, x='location', y='count')

        # MAP
        fig4 = px.scatter_mapbox(
            df,
            lat="latitude",
            lon="longitude",
            color="price",
            size="price",
            hover_name="room_type",
            zoom=10,
            height=500
        )
        fig4.update_layout(mapbox_style="open-street-map")

        return render_template(
            'dashboard.html',
            graph1=fig1.to_html(full_html=False),
            graph2=fig2.to_html(full_html=False),
            graph3=fig3.to_html(full_html=False),
            graph4=fig4.to_html(full_html=False)
        )

    except Exception as e:
        return f"Dashboard Error: {str(e)}"

# ================= PREDICTION ================= #

@app.route("/predict_page")
def predict_page():
    if "user" not in session:
        return redirect("/login")
    return render_template("predict.html")


@app.route("/predict", methods=["POST"])
def predict():
    if "user" not in session:
        return redirect("/login")

    try:
        data = {col: 0 for col in columns}

        lat = float(request.form["latitude"])
        lon = float(request.form["longitude"])
        min_nights = float(request.form["minimum_nights"])
        availability = float(request.form["availability"])
        loc = request.form["location"]
        room = request.form["room_type"]

        data["latitude"] = lat
        data["longitude"] = lon
        data["minimum_nights"] = min_nights
        data["availability_365"] = availability

        loc_col = f"neighbourhood_group_{loc}"
        if loc_col in data:
            data[loc_col] = 1

        room_col = f"room_type_{room}"
        if room_col in data:
            data[room_col] = 1

        final_input = [data[col] for col in columns]
        prediction = model.predict([final_input])[0]

        # Save prediction
        conn = get_db()
        conn.execute(
            "INSERT INTO predictions (user, location, room_type, price) VALUES (?, ?, ?, ?)",
            (session['user'], loc, room, float(prediction))
        )
        conn.commit()
        conn.close()

        # Market comparison
        df = pd.read_csv('data/AB_NYC_2019.csv')
        market_avg = df[
            (df['neighbourhood_group'] == loc) &
            (df['room_type'] == room)
        ]['price'].mean()

        return render_template(
            "predict_result.html",
            prediction=round(prediction, 2),
            market_avg=round(market_avg, 2)
        )

    except Exception as e:
        return f"Prediction Error: {str(e)}"

# ================= HISTORY ================= #

@app.route("/history")
def history():
    if 'user' not in session:
        return redirect('/login')

    import plotly.express as px

    conn = get_db()
    df = pd.read_sql_query(
        "SELECT * FROM predictions WHERE user = ?",
        conn,
        params=(session['user'],)
    )
    conn.close()

    if df.empty:
        return "No predictions yet."

    fig = px.line(df, x="id", y="price", title="Your Prediction History")

    return render_template(
        "history.html",
        graph=fig.to_html(full_html=False)
    )

# ================= RUN ================= #

if __name__ == "__main__":
    app.run(debug=True)