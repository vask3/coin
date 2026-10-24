import hashlib
import json
import random
import time
import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vasko_crypto_super_secret_key")

# --- MONGO DB SETUP ---
MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["coin"]

users_col = db["users"]
sensors_col = db["sensor_history"]
system_col = db["system_state"]
tx_col = db["transactions"]

COIN_NAME = "VASKO"
COIN_SYMBOL = "VASK"
ADMIN_USERNAME = "vasko_creator"  
WELCOME_BONUS = 5.0  

BLOCK_REWARD = 0.05 
STAKING_DAILY_RATE = 0.001
current_difficulty = "0000"

MAX_SUPPLY = 2000000.0
MARKETING_RESERVE_INIT = 200000.0
RESERVE_INIT = 800000.0

def init_system_budget():
    if not system_col.find_one({"type": "budget"}):
        system_col.insert_one({
            "type": "budget",
            "marketing_budget": MARKETING_RESERVE_INIT,
            "mining_pool_budget": RESERVE_INIT,
            "total_minted": 0.0
        })

init_system_budget()

def log_transaction(sender, receiver, amount, tx_type):
    tx_col.insert_one({
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "type": tx_type,
        "timestamp": time.time()
    })

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
    return render_template("index.html")

@app.route("/api/network_status")
def api_network_status():
    last_block = sensors_col.find_one(sort=[("_id", -1)])
    next_target = f"IOT_NODE_{random.randint(1000,9999)}_TEMP:{random.uniform(18.5, 38.2):.2f}_TIME:{int(time.time())}"
    return jsonify({
        "next_target": next_target,
        "difficulty": current_difficulty,
        "total_blocks": sensors_col.count_documents({}),
        "last_block_hash": last_block.get("block_hash", "N/A") if last_block else "Няма запечатани блокове",
        "last_miner": last_block.get("validated_by", "N/A") if last_block else "N/A",
        "block_reward": BLOCK_REWARD
    })

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

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
            "staked_balance": 0.0,
            "mining_key": mining_key,
            "role": role,
            "last_active": time.time(),
            "last_staking_claim": time.time()
        }
        users_col.insert_one(user_doc)
        system_col.update_one({"type": "budget"}, {"$inc": {"marketing_budget": -WELCOME_BONUS}})
        log_transaction("SYSTEM_AIRDROP", username, WELCOME_BONUS, "welcome_bonus")

        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
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
    return redirect(url_for("home"))

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    
    username = session["user"]
    user_data = users_col.find_one({"username": username}) or {}
    
    last_sensor_doc = sensors_col.find_one(sort=[("_id", -1)])
    sensor_display = last_sensor_doc.get('raw_target', 'Няма данни') if last_sensor_doc else "Няма запечатани данни"

    total_users = users_col.count_documents({})
    total_blocks = sensors_col.count_documents({})
    user_blocks = list(sensors_col.find({"validated_by": username}).sort("timestamp", -1).limit(5))
    budget_state = system_col.find_one({"type": "budget"}) or {"marketing_budget": 0.0, "mining_pool_budget": 0.0}

    # Подаваме абсолютно всички променливи едновременно, за да няма сривове
    return render_template("dashboard.html", 
                           username=username, 
                           balance=user_data.get("balance", 0.0), 
                           staked_balance=user_data.get("staked_balance", 0.0),
                           mining_key=user_data.get("mining_key", "N/A"),
                           role=user_data.get("role", "user"),
                           last_sensor=sensor_display, 
                           difficulty=current_difficulty,
                           symbol=COIN_SYMBOL,
                           coin_name=COIN_NAME,
                           total_users=total_users,
                           total_blocks=total_blocks,
                           user_blocks=user_blocks,
                           marketing_budget=budget_state.get("marketing_budget", 0.0),
                           mining_pool_budget=budget_state.get("mining_pool_budget", 0.0),
                           max_supply=MAX_SUPPLY,
                           block_reward=BLOCK_REWARD,
                           pool_reward=BLOCK_REWARD)

@app.route("/staking/deposit", methods=["POST"])
def staking_deposit():
    if "user" not in session:
        return redirect(url_for("login"))
    
    username = session["user"]
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0.0

    user = users_col.find_one({"username": username})
    if user and amount > 0 and user.get("balance", 0.0) >= amount:
        users_col.update_one({"username": username}, {
            "$inc": {"balance": -amount, "staked_balance": amount}
        })
        log_transaction(username, "STAKING_POOL", amount, "staking_deposit")

    return redirect(url_for("dashboard"))

@app.route("/staking/claim", methods=["POST"])
def staking_claim():
    if "user" not in session:
        return redirect(url_for("login"))
    
    username = session["user"]
    user = users_col.find_one({"username": username})
    if user:
        staked = user.get("staked_balance", 0.0)
        last_claim = user.get("last_staking_claim", time.time())
        now = time.time()
        
        hours_passed = (now - last_claim) / 3600.0
        if hours_passed >= 1 and staked > 0:
            yield_reward = staked * (STAKING_DAILY_RATE / 24.0) * hours_passed
            users_col.update_one({"username": username}, {
                "$inc": {"balance": yield_reward},
                "$set": {"last_staking_claim": now}
            })
            log_transaction("STAKING_RESERVE", username, yield_reward, "staking_yield")

    return redirect(url_for("dashboard"))

@app.route("/admin/transactions")
def admin_transactions():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))
    
    recent_txs = list(tx_col.find().sort("timestamp", -1).limit(50))
    return render_template("admin_txs.html", txs=recent_txs, symbol=COIN_SYMBOL)

@app.route("/miner")
def web_miner():
    return render_template("miner.html")

@app.route("/esp32_guides")
def esp32_guides():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("esp32_guides.html", symbol=COIN_SYMBOL)

@app.route("/get_job", methods=["GET"])
def get_job():
    sensor_id = random.randint(1000, 9999)
    temp = round(random.uniform(18.5, 38.2), 2)
    humidity = round(random.uniform(30.0, 85.0), 1)
    target_payload = f"IOT_NODE_{sensor_id}_TEMP:{temp}_HUM:{humidity}%_TIME:{int(time.time())}"
    return jsonify({"target": target_payload, "difficulty": current_difficulty})

@app.route("/submit_block", methods=["POST"])
def submit_block():
    data = request.json or {}
    username = data.get("username")
    mining_key = data.get("mining_key")
    nonce = str(data.get("nonce", ""))
    target_string = data.get("target", "")

    user = users_col.find_one({"username": username})
    if not user or user.get("mining_key") != mining_key:
        return jsonify({"status": "REJECTED", "message": "Невалиден ключ!"}), 401

    combined = target_string + nonce
    result_hash = hashlib.sha256(combined.encode()).hexdigest()

    if result_hash.startswith(current_difficulty):
        miner_reward = BLOCK_REWARD
        sensors_col.insert_one({
            "validated_by": username, 
            "raw_target": target_string, 
            "block_hash": result_hash, 
            "timestamp": time.time()
        })
        users_col.update_one({"username": username}, {"$inc": {"balance": miner_reward}})
        log_transaction("NETWORK_MINING", username, miner_reward, "reward")
        return jsonify({"status": "ACCEPTED", "message": f"🎉 Успешен блок! Награда: {miner_reward} {COIN_SYMBOL}"})
    else:
        return jsonify({"status": "REJECTED", "message": "PoW грешен хеш!"}), 400

@app.route("/admin/transfer", methods=["POST"])
def admin_transfer():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))
    
    target_user = request.form.get("target_user", "").strip()
    source_type = request.form.get("source_type", "personal")
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0.0

    if amount <= 0:
        return redirect(url_for("dashboard"))

    if target_user == "marketing_budget":
        admin_data = users_col.find_one({"username": ADMIN_USERNAME}) or {}
        if source_type == "personal" and admin_data.get("balance", 0.0) >= amount:
            users_col.update_one({"username": ADMIN_USERNAME}, {"$inc": {"balance": -amount}})
            system_col.update_one({"type": "budget"}, {"$inc": {"marketing_budget": amount}})
            log_transaction(ADMIN_USERNAME, "MARKETING_BUDGET", amount, "fund_refill")

    elif target_user == "mining_pool":
        admin_data = users_col.find_one({"username": ADMIN_USERNAME}) or {}
        if source_type == "personal" and admin_data.get("balance", 0.0) >= amount:
            users_col.update_one({"username": ADMIN_USERNAME}, {"$inc": {"balance": -amount}})
            system_col.update_one({"type": "budget"}, {"$inc": {"mining_pool_budget": amount}})
            log_transaction(ADMIN_USERNAME, "RESERVE_FUND", amount, "fund_refill")

    else:
        if not users_col.find_one({"username": target_user}):
            return redirect(url_for("dashboard"))

        if source_type == "marketing":
            budget_state = system_col.find_one({"type": "budget"}) or {"marketing_budget": 0.0}
            if budget_state.get("marketing_budget", 0.0) >= amount:
                system_col.update_one({"type": "budget"}, {"$inc": {"marketing_budget": -amount}})
                users_col.update_one({"username": target_user}, {"$inc": {"balance": amount}})
                log_transaction("MARKETING_BUDGET", target_user, amount, "admin_transfer")
        
        elif source_type == "personal":
            admin_data = users_col.find_one({"username": ADMIN_USERNAME}) or {}
            if admin_data.get("balance", 0.0) >= amount:
                users_col.update_one({"username": ADMIN_USERNAME}, {"$inc": {"balance": -amount}})
                users_col.update_one({"username": target_user}, {"$inc": {"balance": amount}})
                log_transaction(ADMIN_USERNAME, target_user, amount, "admin_transfer")

    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
