import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

app = Flask(__name__)

MONGODB_URI = os.environ.get("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI not set")

client = MongoClient(MONGODB_URI)

uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or ""
p = urlparse(uri)
print("MONGO scheme:", p.scheme)
print("MONGO host:", p.hostname)
print("MONGO db:", p.path)
print("MONGO has_user:", bool(p.username))
print("MONGO has_pass:", p.password is not None)
print("MONGO query:", p.query)

db = client['budget-buddy-db']

expenses_col = db["expenses"]
settings_col = db["settings"]

def get_user_id():
    return request.headers.get("X-User-Id")

@app.route('/')
def home():
    return render_template('index.html')


# Get all expenses
@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    docs = list(expenses_col.find().sort("createdAt", -1))
    out = []
    for d in docs:
        out.append({
            "id": str(d["_id"]),
            "category": d.get("category"),
            "description": d.get("description"),
            "amount": (d.get("amountCents", 0) / 100.0),
            "createdAt": d.get("createdAt").isoformat() if d.get("createdAt") else None
        })
    return jsonify(out)


# Add an expense
@app.route("/api/expenses", methods=["POST"])
def add_expense():
    data = request.get_json()

    category = (data.get("category") or "Other").strip()
    description = (data.get("description") or "").strip()

    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    if not description or amount <= 0:
        return jsonify({"error": "Description required and amount must be > 0"}), 400

    doc = {
        "category": category,
        "description": description,
        "amountCents": int(round(amount * 100)),
        "createdAt": datetime.utcnow()
    }

    res = expenses_col.insert_one(doc)
    return jsonify({"id": str(res.inserted_id)}), 201


# Delete an expense by id
@app.route("/api/expenses/<expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    res = expenses_col.delete_one({"_id": ObjectId(expense_id)})
    if res.deleted_count == 0:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"deleted": expense_id})


# Chart summary: totals by category
@app.route("/api/expenses/summary", methods=["GET"])
def expenses_summary():
    pipeline = [
        {"$group": {"_id": "$category", "totalCents": {"$sum": "$amountCents"}}},
        {"$sort": {"totalCents": -1}}
    ]
    agg = list(expenses_col.aggregate(pipeline))
    result = [{"category": r["_id"], "total": r["totalCents"] / 100.0} for r in agg]
    return jsonify(result)

@app.route("/api/settings", methods=["POST"])
def save_settings():
    user_id = get_user_id()
    data = request.get_json()

    paycheck = float(data.get("paycheck", 0))
    savings_percent = float(data.get("savingsPercent", 0))

    settings_col.update_one(
        {"userId" : user_id},
        {"$set" : {
            "paycheckCents" : int(round(paycheck * 100)),
            "savingsPercent" : savings_percent,
            "updatedAt" : datetime.utcnow()
        }},
        upsert = True
    )

    return jsonify({"ok" : True})

@app.route("/api/settings", methods=["GET"])
def get_settings():
    user_id = get_user_id()
    doc = settings_col.find_one({"userId" : user_id})

    if not doc:
        return jsonify({"paycheck": 0, "savingsPercent": 0})

    return jsonify({
        "paycheck" : doc.get("paycheckCents", 0) / 100.0,
        "savingsPercent" : doc.get("savingsPercent", 0)
    })



app.run(host='0.0.0.0', port=5050)
