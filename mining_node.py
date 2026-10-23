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
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://vasko_user:vasko1234@cluster0.abcde.mongodb.net/vasko_db?retryWrites=true&w=majority")
client = MongoClient(MONGO_URI)
db = client["vasko_crypto"]

users_col = db["users"]
sensors_col = db["sensor_history"]
promos_col = db["promo_codes"]

COIN_NAME = "VASKO"
COIN_SYMBOL = "VASK"
ADMIN_USERNAME = "vasko_creator"  # Твоят администраторски акаунт
WELCOME_BONUS = 5.0  # Стратегически начален бонус: 5 VASK
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
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password")

        if not username or not password:
            return render_template("register.html", error="Всички полета са задължителни!")

        if email and is_disposable_email(email):
            return render_template("register.html", error="Временни имейли (Temp-Mail) не са позволени!")

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
            "daily_blocks": 0,
            "last_reset_day": time.strftime("%Y-%m-%d"),
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
    return redirect(url_for("login"))

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

@app.route("/regenerate_key", methods=["POST"])
def regenerate_key():
    if "user" not in session:
        return jsonify({"status": "ERROR", "message": "Unauthorized"}), 401
    username = session["user"]
    new_key = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
    users_col.update_one({"username": username}, {"$set": {"mining_key": new_key}})
    return jsonify({"status": "SUCCESS", "new_key": new_key})

@app.route("/get_job", methods=["GET"])
def get_job():
    target_payload = f"SYS_NODE_TEMP:24.5_TIME:{int(time.time())}"
    return jsonify({
        "target": target_payload, 
        "difficulty": current_difficulty
    })

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

        sensors_col.insert_one({
            "validated_by": username,
            "raw_target": target_string,
            "block_hash": result_hash,
            "timestamp": time.time()
        })

        users_col.update_one({"username": username}, {
            "$inc": {"balance": miner_reward},
            "$set": {"last_active": time.time()}
        })

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

    if amount <= 0:
        return jsonify({"status": "ERROR", "message": "Невалидна сума!"}), 400

    user = users_col.find_one({"username": target_user})
    if not user:
        return jsonify({"status": "ERROR", "message": "Потребителят не е намерен!"}), 404

    users_col.update_one({"username": target_user}, {"$inc": {"balance": amount}})
    return jsonify({"status": "SUCCESS", "message": f"Преведени {amount} {COIN_SYMBOL} на {target_user}!"})

@app.route("/admin/create_promo", methods=["POST"])
def create_promo():
    if session.get("role") != "admin":
        return jsonify({"status": "ERROR", "message": "Нямате права!"}), 403

    data = request.json
    code = data.get("code").strip().upper()
    reward = float(data.get("reward", 0))
    max_uses = int(data.get("max_uses", 1))

    if promos_col.find_one({"code": code}):
        return jsonify({"status": "ERROR", "message": "Кодът съществува!"}), 400

    promos_col.insert_one({"code": code, "reward": reward, "max_uses": max_uses, "current_uses": 0, "active": True})
    return jsonify({"status": "SUCCESS", "message": f"Промокод '{code}' създаден!"})

@app.route("/redeem_promo", methods=["POST"])
def redeem_promo():
    if "user" not in session:
        return jsonify({"status": "ERROR", "message": "Unauthorized"}), 401

    username = session["user"]
    data = request.json
    code = data.get("code", "").strip().upper()

    promo = promos_col.find_one({"code": code, "active": True})
    if not promo or promo["current_uses"] >= promo["max_uses"]:
        return jsonify({"status": "ERROR", "message": "Невалиден или изчерпан код!"}), 400

    user = users_col.find_one({"username": username})
    if code in user.get("used_promos", []):
        return jsonify({"status": "ERROR", "message": "Вече сте използвали този код!"}), 400

    users_col.update_one({"username": username}, {"$inc": {"balance": promo["reward"]}, "$push": {"used_promos": code}})
    promos_col.update_one({"code": code}, {"$inc": {"current_uses": 1}})

    return jsonify({"status": "SUCCESS", "message": f"Успешно добавени {promo['reward']} {COIN_SYMBOL}!"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
