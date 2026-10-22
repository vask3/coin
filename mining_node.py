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
BASE_BLOCK_REWARD = 0.00005000  # Micro-rewards (like satoshis)

current_difficulty = "000"       # Difficulty requirement for blocks
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
                # Ensure every loaded user has a mining key
                if "mining_key" not in info:
                    info["mining_key"] = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
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
            return render_template("register.html", error="All fields are required!")
        users = load_users()
        if username in users:
            return render_template("register.html", error="Username is already taken!")
        
        mining_key = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))

        users[username] = {
            "password": generate_password_hash(password),
            "balance": 0.0,
            "mining_key": mining_key,
            "last_active": time.time(),
            "last_sensor": "No data",
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
        return render_template("login.html", error="Invalid username or password!")
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
    
    if "mining_key" not in user_data or not user_data["mining_key"]:
        user_data["mining_key"] = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
        save_users(users)

    return render_template("dashboard.html", 
                           username=username, 
                           balance=user_data.get("balance", 0), 
                           mining_key=user_data.get("mining_key"),
                           last_sensor=user_data.get("last_sensor", "None"), 
                           difficulty=current_difficulty,
                           symbol=COIN_SYMBOL,
                           coin_name=COIN_NAME)

@app.route("/regenerate_key", methods=["POST"])
def regenerate_key():
    if "user" not in session:
        return jsonify({"status": "ERROR", "message": "Unauthorized"}), 401
    username = session["user"]
    users = load_users()
    if username in users:
        new_key = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
        users[username]["mining_key"] = new_key
        save_users(users)
        return jsonify({"status": "SUCCESS", "new_key": new_key})
    return jsonify({"status": "ERROR", "message": "User not found"}), 404

@app.route("/miner")
def miner_page():
    return render_template("miner.html")

@app.route("/faucet", methods=["POST"])
def faucet():
    if "user" not in session:
        return jsonify({"status": "ERROR", "message": "Unauthorized access"}), 401
    username = session["user"]
    users = load_users()
    current_time = time.time()
    user_data = users[username]
    if current_time - user_data.get("last_faucet", 0) < 86400:
        return jsonify({"status": "ERROR", "message": "You can use the faucet only once every 24 hours!"}), 400
    
    user_data["balance"] += 3.0  # Faucet gives exactly 3 coins
    user_data["last_faucet"] = current_time
    user_data["last_active"] = current_time
    save_users(users)
    return jsonify({"status": "SUCCESS", "message": f"Received 3 {COIN_SYMBOL}!", "new_balance": user_data["balance"]})

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
    
    # Strict validation: Check if user exists and mining key matches precisely
    if username not in users or not mining_key or users[username].get("mining_key") != mining_key:
        return jsonify({"status": "REJECTED", "message": "Invalid username or incorrect 6-character mining key!"}), 401

    today = time.strftime("%Y-%m-%d")
    if users[username].get("last_reset_day") != today:
        users[username]["last_reset_day"] = today
        users[username]["daily_blocks"] = 0

    if users[username].get("daily_blocks", 0) >= 50:
        return jsonify({"status": "REJECTED", "message": "Daily mining quota reached (50 blocks)!"}), 429

    combined = target_string + nonce
    result_hash = hashlib.sha256(combined.encode()).hexdigest()

    if result_hash.startswith(current_difficulty):
        now = time.time()
        time_taken = now - last_block_time
        last_block_time = now

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
        return jsonify({"status": "ACCEPTED", "message": f"Block accepted! Reward: {miner_reward:.8f} {COIN_SYMBOL}"})
    else:
        return jsonify({"status": "REJECTED", "message": "Invalid hash (Proof-of-Work failed)!"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
