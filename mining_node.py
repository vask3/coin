import hashlib
import json
import random
import time
import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "vasko_crypto_super_secret_key"

COIN_NAME = "VASKO"
COIN_SYMBOL = "VASK"
TOTAL_SUPPLY = 900_000_000
DEV_ADDRESS = "vasko_creator"
DEV_SHARE = 0.02
BASE_BLOCK_REWARD = 1000

current_difficulty = "0030" # Намиксваме малко по-лесна трудност за уеб браузър
last_block_time = time.time()
FOUR_YEARS_SECONDS = 4 * 365 * 24 * 60 * 60
USERS_FILE = "users.json"

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
            current_time = time.time()
            cleaned_data = {}
            for username, info in data.items():
                if username == DEV_ADDRESS:
                    cleaned_data[username] = info
                    continue
                last_active = info.get("last_active", current_time)
                if current_time - last_active < FOUR_YEARS_SECONDS:
                    cleaned_data[username] = info
            return cleaned_data
    except Exception:
        return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)

current_job = {
    "target_string": str(random.randint(100000, 999999)),
    "difficulty": current_difficulty
}

@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        if not username or not password:
            return render_template("register.html", error="Всички полета са задължителни!")
        users = load_users()
        if username in users:
            return render_template("register.html", error="Потребителското име е заето!")
        
        # Генерираме уникален 6-символен ключ за миньорство при регистрация
        mining_key = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))

        users[username] = {
            "password": generate_password_hash(password),
            "balance": 0.0,
            "mining_key": mining_key,
            "last_active": time.time(),
            "last_sensor": "Няма данни",
            "last_faucet": 0,
            "daily_blocks": 0,
            "last_reset_day": time.strftime("%Y-%m-%d")
        }
        save_users(users)
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        users = load_users()
        if username in users and check_password_hash(users[username]["password"], password):
            session["user"] = username
            users[username]["last_active"] = time.time()
            save_users(users)
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Грешно име или парола!")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    username = session["user"]
    users = load_users()
    user_data = users.get(username, {})
    
    # Ако няма генериран ключ, му правим един
    if "mining_key" not in user_data:
        user_data["mining_key"] = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
        save_users(users)

    return render_template("dashboard.html", 
                           username=username, 
                           balance=user_data.get("balance", 0), 
                           mining_key=user_data.get("mining_key"),
                           last_sensor=user_data.get("last_sensor", "Няма"), 
                           difficulty=current_difficulty,
                           symbol=COIN_SYMBOL,
                           coin_name=COIN_NAME)

@app.route("/faucet", methods=["POST"])
def faucet():
    if "user" not in session:
        return jsonify({"status": "ERROR", "message": "Неоторизиран достъп"}), 401
    username = session["user"]
    users = load_users()
    current_time = time.time()
    user_data = users[username]
    if current_time - user_data.get("last_faucet", 0) < 86400:
        return jsonify({"status": "ERROR", "message": "Можеш да вземаш от кранчето веднъж на 24 часа!"}), 400
    
    user_data["balance"] += 50
    user_data["last_faucet"] = current_time
    user_data["last_active"] = current_time
    save_users(users)
    return jsonify({"status": "SUCCESS", "message": f"Получи 50 {COIN_SYMBOL}!", "new_balance": user_data["balance"]})

@app.route("/get_job", methods=["GET"])
def get_job():
    current_job["target_string"] = str(random.randint(100000, 999999))
    current_job["difficulty"] = current_difficulty
    return jsonify({"target": current_job["target_string"], "difficulty": current_job["difficulty"]})

@app.route("/submit_block", methods=["POST"])
def submit_block():
    global current_difficulty, last_block_time
    data = request.json
    username = data.get("username")
    mining_key = data.get("mining_key")
    nonce = str(data.get("nonce"))
    target_string = data.get("target")

    users = load_users()
    if username not in users or users[username].get("mining_key") != mining_key:
        return jsonify({"status": "REJECTED", "message": "Грешен потребител или 6-символен ключ!"}), 401

    # Проверка за дневна квота (максимум 50 блока на ден от устройство/браузър)
    today = time.strftime("%Y-%m-%d")
    if users[username].get("last_reset_day") != today:
        users[username]["last_reset_day"] = today
        users[username]["daily_blocks"] = 0

    if users[username].get("daily_blocks", 0) >= 50:
        return jsonify({"status": "REJECTED", "message": "Достигната е дневната квота за копаене (50 блока)!"}), 429

    combined = target_string + nonce
    result_hash = hashlib.sha256(combined.encode()).hexdigest()

    if result_hash.startswith(current_difficulty):
        now = time.time()
        time_taken = now - last_block_time
        last_block_time = now

        if time_taken < 10 and len(current_difficulty) < 6:
            current_difficulty += "0"
        elif time_taken > 60 and len(current_difficulty) > 3:
            current_difficulty = current_difficulty[:-1]

        current_time = time.time()
        dev_reward = BASE_BLOCK_REWARD * DEV_SHARE
        miner_reward = BASE_BLOCK_REWARD * (1 - DEV_SHARE)

        users[username]["balance"] += miner_reward
        users[username]["daily_blocks"] += 1
        users[username]["last_active"] = current_time

        if DEV_ADDRESS not in users:
            users[DEV_ADDRESS] = {"password": "N/A", "balance": 0, "last_active": current_time}
        users[DEV_ADDRESS]["balance"] += dev_reward

        save_users(users)
        return jsonify({"status": "ACCEPTED", "message": f"Блокът е приет! Награда: {miner_reward} {COIN_SYMBOL}"})
    else:
        return jsonify({"status": "REJECTED", "message": "Невалиден хеш (Proof-of-Work грешка)!"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
