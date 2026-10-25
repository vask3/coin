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
promo_col = db["promo_codes"]
devices_col = db["devices"]  # Нова колекция за устройствата на потребителите
pending_tx_col = db["pending_transactions"]  # За транзакции над 50 VASK

COIN_NAME = "VASKO"
COIN_SYMBOL = "VASK"
ADMIN_USERNAME = "vasko_creator"  
WELCOME_BONUS = 5.0  

STAKING_DAILY_RATE = 0.001
NETWORK_FEE_PERCENT = 0.01  # 1% Gas Fee
PENDING_THRESHOLD = 50.0    # Праг за ръчно одобрение

MAX_SUPPLY = 2000000.0
MARKETING_RESERVE_INIT = 200000.0
RESERVE_INIT = 800000.0

def init_system_budget():
    if not system_col.find_one({"type": "budget"}):
        system_col.insert_one({
            "type": "budget",
            "marketing_budget": MARKETING_RESERVE_INIT,
            "mining_pool_budget": RESERVE_INIT,
            "maintenance_fund": 0.0,
            "total_minted": 0.0,
            "difficulty": "000"
        })

init_system_budget()

def get_current_difficulty():
    state = system_col.find_one({"type": "budget"})
    return state.get("difficulty", "000") if state else "000"

def calculate_dynamic_reward():
    diff_length = len(get_current_difficulty())
    base_reward = 0.00025 + (diff_length * 0.00002) 
    jitter = random.uniform(-0.00002, 0.00003)
    return round(max(0.0001, base_reward + jitter), 6)

def adjust_difficulty():
    recent_blocks = list(sensors_col.find().sort("timestamp", -1).limit(4))
    if len(recent_blocks) >= 4:
        t_newest = recent_blocks[0]["timestamp"]
        t_oldest = recent_blocks[3]["timestamp"]
        avg_time = (t_newest - t_oldest) / 3.0
        
        current_diff = get_current_difficulty()
        if avg_time < 6.0 and len(current_diff) < 6:
            new_diff = current_diff + "0"
            system_col.update_one({"type": "budget"}, {"$set": {"difficulty": new_diff}})
        elif avg_time > 25.0 and len(current_diff) > 2:
            new_diff = current_diff[:-1]
            system_col.update_one({"type": "budget"}, {"$set": {"difficulty": new_diff}})

def log_transaction(sender, receiver, amount, tx_type, status="APPROVED"):
    tx_col.insert_one({
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "type": tx_type,
        "status": status,
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
        "difficulty": get_current_difficulty(),
        "total_blocks": sensors_col.count_documents({}),
        "last_block_hash": last_block.get("block_hash", "N/A") if last_block else "Няма запечатани блокове",
        "last_miner": last_block.get("validated_by", "N/A") if last_block else "N/A",
        "block_reward": calculate_dynamic_reward()
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
    
    # Вземане на устройствата на потребителя
    user_devices = list(devices_col.find({"owner": username}))
    
    budget_state = system_col.find_one({"type": "budget"}) or {
        "marketing_budget": 0.0, 
        "maintenance_fund": 0.0, 
        "mining_pool_budget": 0.0
    }
    
    pending_txs = list(pending_tx_col.find({"status": "PENDING"})) if session.get("role") == "admin" else []

    return render_template("dashboard.html", 
                           username=username, 
                           balance=user_data.get("balance", 0.0), 
                           staked_balance=user_data.get("staked_balance", 0.0),
                           mining_key=user_data.get("mining_key", "N/A"),
                           role=user_data.get("role", "user"),
                           last_sensor=sensor_display, 
                           difficulty=get_current_difficulty(),
                           symbol=COIN_SYMBOL,
                           coin_name=COIN_NAME,
                           total_users=total_users,
                           total_blocks=total_blocks,
                           user_blocks=user_blocks,
                           user_devices=user_devices,
                           marketing_budget=budget_state.get("marketing_budget", 0.0),
                           maintenance_fund=budget_state.get("maintenance_fund", 0.0),
                           mining_pool_budget=budget_state.get("mining_pool_budget", 0.0),
                           max_supply=MAX_SUPPLY,
                           block_reward=calculate_dynamic_reward(),
                           pending_txs=pending_txs)

# --- Превод с лимит 50 VASK (Автоматично или Pending) ---
@app.route("/transfer", methods=["POST"])
def transfer():
    if "user" not in session:
        return redirect(url_for("login"))
    
    sender = session["user"]
    recipient = request.form.get("recipient", "").strip()
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0.0

    if amount <= 0 or sender == recipient:
        return redirect(url_for("dashboard"))

    sender_doc = users_col.find_one({"username": sender})
    recipient_doc = users_col.find_one({"username": recipient})

    if sender_doc and recipient_doc and sender_doc.get("balance", 0.0) >= amount:
        fee = round(amount * NETWORK_FEE_PERCENT, 6)
        net_amount = amount - fee

        if amount > PENDING_THRESHOLD:
            # Пращаме в PENDING за ръчно одобрение от админ
            pending_tx_col.insert_one({
                "sender": sender,
                "recipient": recipient,
                "amount": amount,
                "net_amount": net_amount,
                "fee": fee,
                "type": "user_transfer",
                "status": "PENDING",
                "timestamp": time.time()
            })
            # Заключваме сумата от баланса на изпращача временно
            users_col.update_one({"username": sender}, {"$inc": {"balance": -amount}})
            log_transaction(sender, recipient, amount, "user_transfer_pending", "PENDING")
        else:
            # Автоматично изпълнение под 50 VASK
            users_col.update_one({"username": sender}, {"$inc": {"balance": -amount}})
            users_col.update_one({"username": recipient}, {"$inc": {"balance": net_amount}})
            system_col.update_one({"type": "budget"}, {"$inc": {"maintenance_fund": fee}})
            log_transaction(sender, recipient, net_amount, "user_transfer", "APPROVED")
            if fee > 0:
                log_transaction(sender, "MAINTENANCE_FUND", fee, "network_gas_fee", "APPROVED")

    return redirect(url_for("dashboard"))

# --- Админ одобрява или отхвърля чакаща транзакция над 50 VASK ---
@app.route("/admin/resolve_pending/<tx_id>", methods=["POST"])
def resolve_pending(tx_id):
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))
    
    action = request.form.get("action")
    from bson.ObjectId import ObjectId
    tx = pending_tx_col.find_one({"_id": ObjectId(tx_id), "status": "PENDING"})
    
    if tx:
        sender = tx["sender"]
        recipient = tx["recipient"]
        amount = tx["amount"]
        net_amount = tx["net_amount"]
        fee = tx["fee"]

        if action == "approve":
            users_col.update_one({"username": recipient}, {"$inc": {"balance": net_amount}})
            system_col.update_one({"type": "budget"}, {"$inc": {"maintenance_fund": fee}})
            pending_tx_col.update_one({"_id": ObjectId(tx_id)}, {"$set": {"status": "APPROVED"}})
            log_transaction(sender, recipient, net_amount, "user_transfer_approved", "APPROVED")
        elif action == "reject":
            # Връщаме сумата на изпращача при отказ
            users_col.update_one({"username": sender}, {"$inc": {"balance": amount}})
            pending_tx_col.update_one({"_id": ObjectId(tx_id)}, {"$set": {"status": "REJECTED"}})
            log_transaction(sender, recipient, amount, "user_transfer_rejected", "REJECTED")

    return redirect(url_for("dashboard"))

# --- Активиране на промокод ---
@app.route("/redeem_promo", methods=["POST"])
def redeem_promo():
    if "user" not in session:
        return redirect(url_for("login"))
    
    username = session["user"]
    code_input = request.form.get("promo_code", "").strip().upper()
    
    promo = promo_col.find_one({"code": code_input, "active": True})
    if promo:
        if username in promo.get("used_by", []):
            return redirect(url_for("dashboard"))

        source = promo.get("source", "personal")
        reward_amount = promo.get("reward", 0.0)

        if source == "marketing":
            budget_state = system_col.find_one({"type": "budget"}) or {}
            if budget_state.get("marketing_budget", 0.0) >= reward_amount:
                system_col.update_one({"type": "budget"}, {"$inc": {"marketing_budget": -reward_amount}})
                users_col.update_one({"username": username}, {"$inc": {"balance": reward_amount}})
                promo_col.update_one({"code": code_input}, {"$push": {"used_by": username}})
                log_transaction("MARKETING_BUDGET", username, reward_amount, f"PROMO_CODE ({code_input})")
        else:
            admin_doc = users_col.find_one({"username": ADMIN_USERNAME})
            if admin_doc and admin_doc.get("balance", 0.0) >= reward_amount:
                users_col.update_one({"username": ADMIN_USERNAME}, {"$inc": {"balance": -reward_amount}})
                users_col.update_one({"username": username}, {"$inc": {"balance": reward_amount}})
                promo_col.update_one({"code": code_input}, {"$push": {"used_by": username}})
                log_transaction(ADMIN_USERNAME, username, reward_amount, f"PROMO_CODE ({code_input})")

    return redirect(url_for("dashboard"))

# --- Служебна регистрация на потребител ---
@app.route("/admin/create_user", methods=["POST"])
def admin_create_user():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))

    new_username = request.form.get("username", "").strip()
    new_email = request.form.get("email", "").strip()
    new_password = request.form.get("password", "")
    try:
        initial_balance = float(request.form.get("balance", WELCOME_BONUS))
    except ValueError:
        initial_balance = WELCOME_BONUS

    if not new_username or not new_password or users_col.find_one({"username": new_username}):
        return redirect(url_for("dashboard"))

    mining_key = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
    
    users_col.insert_one({
        "username": new_username,
        "email": new_email,
        "password": generate_password_hash(new_password),
        "balance": initial_balance,
        "staked_balance": 0.0,
        "mining_key": mining_key,
        "role": "user",
        "last_active": time.time(),
        "last_staking_claim": time.time()
    })
    log_transaction("ADMIN_CREATION", new_username, initial_balance, "admin_user_registration")
    return redirect(url_for("dashboard"))

# --- Админ създава промокод ---
@app.route("/admin/create_promo", methods=["POST"])
def admin_create_promo():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))
    
    code = request.form.get("code", "").strip().upper()
    source = request.form.get("source", "personal")
    try:
        reward = float(request.form.get("reward", 0))
    except ValueError:
        reward = 0.0

    if code and reward > 0:
        promo_col.insert_one({
            "code": code,
            "reward": reward,
            "source": source,
            "active": True,
            "created_at": time.time(),
            "used_by": []
        })
    return redirect(url_for("dashboard"))

# --- Редактиране на баланс с избор на фонд за корекция ---
@app.route("/admin/edit_user", methods=["POST"])
def admin_edit_user():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))

    target_user = request.form.get("target_user", "").strip()
    fund_target = request.form.get("fund_target", "marketing") # Къде отива разликата
    try:
        new_balance = float(request.form.get("balance", 0))
    except ValueError:
        new_balance = None

    user = users_col.find_one({"username": target_user})
    if user and new_balance is not None:
        old_balance = user.get("balance", 0.0)
        diff = new_balance - old_balance

        # Актуализираме баланса на потребителя
        users_col.update_one({"username": target_user}, {"$set": {"balance": new_balance}})

        # Ако отнемаме пари, ги вкарваме в избрания фонд. Ако добавяме, ги теглим от фонда.
        if diff != 0:
            fund_key = "marketing_budget" if fund_target == "marketing" else ("maintenance_fund" if fund_target == "maintenance" else "mining_pool_budget")
            system_col.update_one({"type": "budget"}, {"$inc": {fund_key: -diff}})
            log_transaction(target_user, fund_key.upper(), abs(diff), "balance_adjustment")

    return redirect(url_for("dashboard"))

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
        users_col.update_one({"username": username}, {"$inc": {"balance": -amount, "staked_balance": amount}})
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
            users_col.update_one({"username": username}, {"$inc": {"balance": yield_reward}, "$set": {"last_staking_claim": now}})
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
    return jsonify({"target": target_payload, "difficulty": get_current_difficulty()})

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

    current_diff = get_current_difficulty()
    if result_hash.startswith(current_diff):
        miner_reward = calculate_dynamic_reward()
        
        # Запис на блока
        sensors_col.insert_one({
            "validated_by": username, 
            "raw_target": target_string, 
            "block_hash": result_hash, 
            "reward": miner_reward, 
            "timestamp": time.time()
        })
        
        # Добавяне на наградата към баланса
        users_col.update_one({"username": username}, {"$inc": {"balance": miner_reward}})
        log_transaction("NETWORK_MINING", username, miner_reward, "reward")
        
        # Регистриране или обновяване на устройството в секцията "Your Devices"
        device_id = f"NODE_{mining_key}"
        devices_col.update_one(
            {"device_id": device_id, "owner": username},
            {
                "$set": {"last_active": time.time()},
                "$inc": {"blocks_mined": 1, "total_mined": miner_reward},
                "$setOnInsert": {"status": "Active"}
            },
            upsert=True
        )

        adjust_difficulty()
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
