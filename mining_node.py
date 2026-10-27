import hashlib
import json
import random
import time
import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId  # Правилен импорт, за да няма грешка 500

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
devices_col = db["devices"]
pending_tx_col = db["pending_transactions"]
shop_col = db["shop_items"]       # Колекция за артикулите в магазина
orders_col = db["shop_orders"]     # Колекция за поръчките

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
    
    # Инициализиране на примерни дигитални/физически артикули в магазина
    if shop_col.count_documents({}) == 0:
        shop_col.insert_many([
            {
                "title": "VIP Miner Status (30 дни)",
                "description": "Намалена Gas Fee такса на 0.5% и специален златен профил.",
                "price": 15.0,
                "type": "digital",
                "stock": 999
            },
            {
                "title": "3D STL Файл: VASK Node Enclosure",
                "description": "Готов 3D модел за кутийка за ESP32/Arduino, брандирана с VASK.",
                "price": 5.0,
                "type": "digital",
                "stock": 999
            },
            {
                "title": "Физически VASK Ключодържател",
                "description": "3D принтиран ключодържател с монетата VASK (включва доставка).",
                "price": 25.0,
                "type": "physical",
                "stock": 50
            },
            {
                "title": "VASK Sticker Pack (5 бр.)",
                "description": "Комплект водоустойчиви стикери за твоя лаптоп или ESP32 кейс.",
                "price": 10.0,
                "type": "physical",
                "stock": 100
            }
        ])

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

@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/get_job", methods=["GET"])
def get_job():
    sensor_id = random.randint(1000, 9999)
    temp = round(random.uniform(18.5, 38.2), 2)
    humidity = round(random.uniform(30.0, 85.0), 1)
    target_payload = f"IOT_NODE_{sensor_id}_TEMP:{temp}_HUM:{humidity}%_TIME:{int(time.time())}"
    return jsonify({"target": target_payload, "difficulty": get_current_difficulty()})

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template("register.html", error="Всички полета са задължителни!")

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
    
    total_users = users_col.count_documents({})
    total_blocks = sensors_col.count_documents({})
    user_devices = list(devices_col.find({"owner": username}))
    
    shop_items = list(shop_col.find({"stock": {"$gt": 0}}))
    user_orders = list(orders_col.find({"buyer": username}).sort("timestamp", -1))
    
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
                           difficulty=get_current_difficulty(),
                           symbol=COIN_SYMBOL,
                           coin_name=COIN_NAME,
                           total_users=total_users,
                           total_blocks=total_blocks,
                           user_devices=user_devices,
                           shop_items=shop_items,
                           user_orders=user_orders,
                           marketing_budget=budget_state.get("marketing_budget", 0.0),
                           maintenance_fund=budget_state.get("maintenance_fund", 0.0),
                           mining_pool_budget=budget_state.get("mining_pool_budget", 0.0),
                           block_reward=calculate_dynamic_reward(),
                           pending_txs=pending_txs)

# --- Управление на чакащи транзакции (Admin) ---
@app.route("/admin/resolve_pending/<tx_id>", methods=["POST"])
def resolve_pending(tx_id):
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))
    
    action = request.form.get("action")
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
            users_col.update_one({"username": sender}, {"$inc": {"balance": amount}})
            pending_tx_col.update_one({"_id": ObjectId(tx_id)}, {"$set": {"status": "REJECTED"}})
            log_transaction(sender, recipient, amount, "user_transfer_rejected", "REJECTED")

    return redirect(url_for("dashboard"))

# --- Покупка от VASK Shop ---
@app.route("/shop/buy/<item_id>", methods=["POST"])
def shop_buy(item_id):
    if "user" not in session:
        return redirect(url_for("login"))

    username = session["user"]
    item = shop_col.find_one({"_id": ObjectId(item_id)})
    user = users_col.find_one({"username": username})

    if item and user and item.get("stock", 0) > 0:
        price = float(item["price"])
        if user.get("balance", 0.0) >= price:
            shipping_address = request.form.get("address", "Дигитална доставка")

            users_col.update_one({"username": username}, {"$inc": {"balance": -price}})
            system_col.update_one({"type": "budget"}, {"$inc": {"maintenance_fund": price}})
            shop_col.update_one({"_id": ObjectId(item_id)}, {"$inc": {"stock": -1}})

            orders_col.insert_one({
                "buyer": username,
                "item_title": item["title"],
                "price": price,
                "type": item["type"],
                "address": shipping_address,
                "status": "PROCESSING" if item["type"] == "physical" else "DELIVERED",
                "timestamp": time.time()
            })

            log_transaction(username, "SHOP_MAINTENANCE_FUND", price, f"shop_purchase ({item['title']})")

    return redirect(url_for("dashboard"))

# --- Админ: Добавяне на Нов Артикул в Магазина ---
@app.route("/admin/add_shop_item", methods=["POST"])
def admin_add_shop_item():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    item_type = request.form.get("type", "digital")
    try:
        price = float(request.form.get("price", 0))
        stock = int(request.form.get("stock", 1))
    except ValueError:
        price, stock = 0.0, 0

    if title and price > 0:
        shop_col.insert_one({
            "title": title,
            "description": description,
            "price": price,
            "type": item_type,
            "stock": stock
        })

    return redirect(url_for("dashboard"))

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
            users_col.update_one({"username": sender}, {"$inc": {"balance": -amount}})
            log_transaction(sender, recipient, amount, "user_transfer_pending", "PENDING")
        else:
            users_col.update_one({"username": sender}, {"$inc": {"balance": -amount}})
            users_col.update_one({"username": recipient}, {"$inc": {"balance": net_amount}})
            system_col.update_one({"type": "budget"}, {"$inc": {"maintenance_fund": fee}})
            log_transaction(sender, recipient, net_amount, "user_transfer", "APPROVED")

    return redirect(url_for("dashboard"))

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
        
        sensors_col.insert_one({
            "validated_by": username, 
            "raw_target": target_string, 
            "block_hash": result_hash, 
            "reward": miner_reward, 
            "timestamp": time.time()
        })
        
        users_col.update_one({"username": username}, {"$inc": {"balance": miner_reward}})
        log_transaction("NETWORK_MINING", username, miner_reward, "reward")
        
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

@app.route("/miner")
def web_miner():
    return render_template("miner.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
