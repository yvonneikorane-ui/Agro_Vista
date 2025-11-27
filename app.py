# ----------------------------------------------------
# LOGIN ENDPOINT (copy-paste complete block)
# ----------------------------------------------------
from flask import render_template, redirect, url_for, session

# Simple in-memory users (replace with DB in production)
USERS = {
    "admin": "password123",   # change this to secure passwords
    "user1": "userpass"
}

@app.route("/login", methods=["GET", "POST"])
def login():
    try:
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            if username in USERS and USERS[username] == password:
                session["username"] = username
                return redirect(url_for("index"))
            else:
                return Response(
                    "<h3>Login Failed. Invalid username or password.</h3>"
                    '<a href="/login">Try again</a>',
                    mimetype="text/html"
                )

        # GET request: render login form
        login_html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Login - AgroVista</title>
            <style>
                body { font-family: Arial, sans-serif; background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; }
                .login-box { background: white; padding: 40px; border-radius: 10px; box-shadow: 0px 0px 10px rgba(0,0,0,0.1); width: 300px; text-align: center; }
                input { width: 100%; padding: 10px; margin: 10px 0; border-radius: 5px; border: 1px solid #ccc; }
                button { padding: 10px 20px; width: 100%; border: none; border-radius: 5px; background: #4CAF50; color: white; cursor: pointer; }
                button:hover { background: #388e3c; }
            </style>
        </head>
        <body>
            <div class="login-box">
                <h2>Login</h2>
                <form method="POST">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="password" name="password" placeholder="Password" required>
                    <button type="submit">Login</button>
                </form>
            </div>
        </body>
        </html>
        """
        return Response(login_html, mimetype="text/html")

    except Exception as e:
        return jsonify({"error": f"Failed to load login page: {str(e)}"}), 500
