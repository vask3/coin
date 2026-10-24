# 🪙 VASKO Ecosystem (VASK)

An independent, private IoT and Proof-of-Work (PoW) cryptocurrency ecosystem built with Python (Flask), MongoDB Atlas, and Gunicorn. Hosted on Render.

## 🚀 Key Features
- **Direct IoT Proof-of-Work Mining**: Miners solve randomized IoT sensor data payloads (temperature, humidity, timestamps) to validate blocks.
- **Dynamic Difficulty Adjustment**: The network automatically scales its mining difficulty in real-time based on block solution speeds.
- **Fixed Supply & Rewards**: Hard-capped at 2,000,000 VASK with a standardized reward model per validated block.
- **Staking Mechanism**: Users can lock their VASK to earn passive daily interest yields.
- **Administrative Control Panel**: Root-level management for fund distribution, marketing reserve allocation, and private transaction ledger auditing.

## 🛠️ Tech Stack
- **Backend**: Python, Flask, Gunicorn
- **Database**: MongoDB Atlas (PyMongo)
- **Frontend**: Responsive HTML5 / CSS3 Dark UI with real-time API polling
- **Hosting**: Render (Cloud Platform)

## 📦 Project Structure
```text
├── mining_node.py          # Main Flask application & PoW logic
├── requirements.txt        # Python dependencies
└── templates/
    ├── dashboard.html      # User dashboard & modern admin panel
    ├── index.html          # Landing / Login page
    ├── register.html       # Registration with disposable email check
    ├── miner.html          # Built-in web miner interface
    ├── admin_txs.html      # Private transaction history ledger
    └── esp32_guides.html   # Hardware integration guides for ESP32
