import hashlib
import json
import random
import time
import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient

app = Flask(__name__)
app.secret_key = "vasko_crypto_super_secret_key"

# --- MONGO DB SETUP ---
MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["coin"]

users_col = db["users"]
sensors_col = db["sensor_history"]
promos_col = db["promo_codes"]

COIN_NAME = "VASKO"
COIN_SYMBOL = "VASK"
ADMIN_USERNAME = "vasko_creator"  
WELCOME_BONUS = 5.0  
BASE_BLOCK_REWARD = 0.00005000

current_difficulty = "0000"

DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", 
    "tempmail.com", "temp-mail.org", "yopmail.com", "trashmail.com"
}

def is_disposable_email(email):
    if "@" not in email:
        return False
    domain = email.split("@")[-1].lower()
    return domain in DISPOSABLE_EMAIL_DOMAINS

@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("dashboard"))
    # Вече зарежда твоето налично miner.html от папката templates
    return render_template("miner.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password")

        if not username or not password:
            return render_template("register.html", error="Всички полета са задължителни!")

        if email and is_disposable_email(email):
            return render_template("register.html", error="Временни имейли не са позволени!")

        if users_col.find_one({"username": username}):
            return render_template("register.html", error="Потребителското име е заето!")

        mining_key = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
        role = "admin" if username == ADMIN_USERNAME else "user"

        user_doc = {
            "username": username,
            "email": email,
            "password": generate_password_hash(password),
            "balance": WELCOME_BONUS,
            "mining_key": mining_key,
            "role": role,
            "last_active": time.time(),
            "used_promos": []
        }
        users_col.insert_one(user_doc)
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        user = users_col.find_one({"username": username})
        if user and check_password_hash(user["password"], password):
            session["user"] = username
            session["role"] = user.get("role", "user")
            users_col.update_one({"username": username}, {"$set": {"last_active": time.time()}})
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Невалидно име или парола!")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("/"))

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    
    username = session["user"]
    user_data = users_col.find_one({"username": username})
    
    last_sensor_doc = sensors_col.find_one(sort=[("_id", -1)])
    sensor_display = f"{last_sensor_doc['raw_target']}" if last_sensor_doc else "Няма запечатани данни"

    return render_template("dashboard.html", 
                           username=username, 
                           balance=user_data.get("balance", 0.0), 
                           mining_key=user_data.get("mining_key"),
                           role=user_data.get("role", "user"),
                           last_sensor=sensor_display, 
                           difficulty=current_difficulty,
                           symbol=COIN_SYMBOL,
                           coin_name=COIN_NAME)

@app.route("/esp32_guides")
def esp32_guides():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("esp32_guides.html", symbol=COIN_SYMBOL)

@app.route("/get_job", methods=["GET"])
def get_job():
    target_payload = f"SYS_NODE_TEMP:24.5_TIME:{int(time.time())}"
    return jsonify({"target": target_payload, "difficulty": current_difficulty})

@app.route("/submit_block", methods=["POST"])
def submit_block():
    data = request.json
    username = data.get("username")
    mining_key = data.get("mining_key")
    nonce = str(data.get("nonce"))
    target_string = data.get("target")

    user = users_col.find_one({"username": username})
    if not user or user.get("mining_key") != mining_key:
        return jsonify({"status": "REJECTED", "message": "Невалиден ключ!"}), 401

    combined = target_string + nonce
    result_hash = hashlib.sha256(combined.encode()).hexdigest()

    if result_hash.startswith(current_difficulty):
        miner_reward = BASE_BLOCK_REWARD
        sensors_col.insert_one({"validated_by": username, "raw_target": target_string, "block_hash": result_hash, "timestamp": time.time()})
        users_col.update_one({"username": username}, {"$inc": {"balance": miner_reward}})
        return jsonify({"status": "ACCEPTED", "message": f"Блокът е валидиран! Награда: {miner_reward} {COIN_SYMBOL}"})
    else:
        return jsonify({"status": "REJECTED", "message": "PoW грешен хеш!"}), 400

@app.route("/admin/transfer", methods=["POST"])
def admin_transfer():
    if session.get("role") != "admin":
        return jsonify({"status": "ERROR", "message": "Нямате права!"}), 403
    data = request.json
    target_user = data.get("target_user")
    amount = float(data.get("amount", 0))
    if amount <= 0: return jsonify({"status": "ERROR", "message": "Невалидна сума!"}), 400
    
    user = users_col.find_one({"username": target_user})
    if not user: return jsonify({"status": "ERROR", "message": "Потребителят не е намерен!"}), 404
    
    users_col.update_one({"username": target_user}, {"$inc": {"balance": amount}})
    return jsonify({"status": "SUCCESS", "message": f"Преведени {amount} {COIN_SYMBOL} на {target_user}!"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
