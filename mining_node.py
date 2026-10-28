import hashlib
import json
import random
import time
import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId

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
shop_col = db["shop_items"]
orders_col = db["shop_orders"]

COIN_NAME = "VASKO"
COIN_SYMBOL = "VASK"
ADMIN_USERNAME = "vasko_creator"  
WELCOME_BONUS = 5.0  

STAKING_DAILY_RATE = 0.001
NETWORK_FEE_PERCENT = 0.01  
PENDING_THRESHOLD = 50.0    

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
    
    # Изчистваме старите продукти и слагаме чисти нови по подразбиране
    shop_col.delete_many({})
    shop_col.insert_many([
        {
            "title": "VIP Miner Status (30 Days)",
            "description": "Reduced Gas Fee to 0.5% and special golden profile badge.",
            "price": 15.0,
            "type": "digital",
            "stock": 999
        },
        {
            "title": "3D STL File: VASK Node Enclosure",
            "description": "Ready 3D printable model for ESP32/Arduino case branded with VASK.",
            "price": 5.0,
            "type": "digital",
            "stock": 999
        },
        {
            "title": "Physical VASK Keychain",
            "description": "3D printed physical VASK coin keychain (shipping included).",
            "price": 25.0,
            "type": "physical",
            "stock": 50
        },
        {
            "title": "VASK Sticker Pack (5 pcs)",
            "description": "Waterproof sticker pack for your laptop or ESP32 enclosure.",
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
            return render_template("register.html", error="All fields are required!")

        if users_col.find_one({"username": username}):
            return render_template("register.html", error="Username is already taken!")

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
        return render_template("login.html", error="Invalid username or password!")
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
    
    # Гарантираме си, че създателят винаги е администратор
    if username == ADMIN_USERNAME and user_data.get("role") != "admin":
        users_col.update_one({"username": username}, {"$set": {"role": "admin"}})
        user_data["role"] = "admin"
        session["role"] = "admin"

    total_users = users_col.count_documents({})
    total_blocks = sensors_col.count_documents({})
    user_devices = list(devices_col.find({"owner": username}))
    
    budget_state = system_col.find_one({"type": "budget"}) or {
        "marketing_budget": 0.0, 
        "maintenance_fund": 0.0, 
        "mining_pool_budget": 0.0
    }
    
    pending_txs = list(pending_tx_col.find({"status": "PENDING"})) if user_data.get("role") == "admin" else []

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
                           marketing_budget=budget_state.get("marketing_budget", 0.0),
                           maintenance_fund=budget_state.get("maintenance_fund", 0.0),
                           mining_pool_budget=budget_state.get("mining_pool_budget", 0.0),
                           block_reward=calculate_dynamic_reward(),
                           pending_txs=pending_txs)

@app.route("/shop")
def shop_page():
    if "user" not in session:
        return redirect(url_for("login"))
    
    username = session["user"]
    user_data = users_col.find_one({"username": username}) or {}
    
    shop_items = list(shop_col.find({"stock": {"$gt": 0}}))
    user_orders = list(orders_col.find({"buyer": username}).sort("timestamp", -1))

    return render_template("shop.html", 
                           username=username,
                           balance=user_data.get("balance", 0.0),
                           symbol=COIN_SYMBOL,
                           shop_items=shop_items,
                           user_orders=user_orders,
                           role=user_data.get("role", "user"))

@app.route("/shop/checkout/<item_id>", methods=["GET"])
def shop_checkout(item_id):
    if "user" not in session:
        return redirect(url_for("login"))

    try:
        item = shop_col.find_one({"_id": ObjectId(item_id)})
    except Exception:
        return redirect(url_for("shop"))
        
    user = users_col.find_one({"username": session["user"]})

    if not item or item.get("stock", 0) <= 0:
        return redirect(url_for("shop"))

    return render_template("checkout.html", item=item, balance=user.get("balance", 0.0), symbol=COIN_SYMBOL)

@app.route("/shop/process_checkout/<item_id>", methods=["POST"])
def process_checkout(item_id):
    if "user" not in session:
        return redirect(url_for("login"))

    username = session["user"]
    try:
        item = shop_col.find_one({"_id": ObjectId(item_id)})
    except Exception:
        return redirect(url_for("shop"))
        
    user = users_col.find_one({"username": username})

    if item and user and item.get("stock", 0) > 0:
        price = float(item["price"])
        if user.get("balance", 0.0) >= price:
            full_name = request.form.get("full_name", "").strip()
            phone = request.form.get("phone", "").strip()
            city = request.form.get("city", "").strip()
            address = request.form.get("address", "").strip()
            notes = request.form.get("notes", "").strip()

            users_col.update_one({"username": username}, {"$inc": {"balance": -price}})
            system_col.update_one({"type": "budget"}, {"$inc": {"maintenance_fund": price}})
            shop_col.update_one({"_id": ObjectId(item_id)}, {"$inc": {"stock": -1}})

            orders_col.insert_one({
                "buyer": username,
                "item_title": item["title"],
                "price": price,
                "type": item["type"],
                "shipping_details": {
                    "full_name": full_name,
                    "phone": phone,
                    "city": city,
                    "address": address,
                    "notes": notes
                },
                "status": "PROCESSING" if item["type"] == "physical" else "DELIVERED",
                "timestamp": time.time()
            })

            log_transaction(username, "SHOP_MAINTENANCE_FUND", price, f"shop_purchase ({item['title']})")

    return redirect(url_for("shop"))

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

    return redirect(url_for("shop"))

@app.route("/admin/resolve_pending/<tx_id>", methods=["POST"])
def resolve_pending(tx_id):
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))
    
    action = request.form.get("action")
    try:
        tx = pending_tx_col.find_one({"_id": ObjectId(tx_id), "status": "PENDING"})
    except Exception:
        return redirect(url_for("dashboard"))
    
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
        return jsonify({"status": "REJECTED", "message": "Invalid key!"}), 401

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

        return jsonify({"status": "ACCEPTED", "message": f"🎉 Block mined successfully! Reward: {miner_reward} {COIN_SYMBOL}"})
    else:
        return jsonify({"status": "REJECTED", "message": "PoW incorrect hash!"}), 400

@app.route("/miner")
def web_miner():
    return render_template("miner.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
