import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

app = Flask(__name__)

MONGODB_URI = os.environ.get("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI not set")

client = MongoClient(MONGODB_URI)

# Safe debug prints (no secrets)
uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or ""
p = urlparse(uri)
print("MONGO scheme:", p.scheme)
print("MONGO host:", p.hostname)
print("MONGO db:", p.path)
print("MONGO has_user:", bool(p.username))
print("MONGO has_pass:", p.password is not None)
print("MONGO query:", p.query)

db = client["budget-buddy-db"]

expenses_col = db["expenses"]
settings_col = db["settings"]


def get_user_id():
    # NOTE: This is demo-level "auth". Any client can spoof this header.
    return request.headers.get("X-User-Id")


def require_user_id():
    user_id = get_user_id()
    if not user_id:
        return None, (jsonify({"error": "Missing X-User-Id header"}), 401)
    return user_id, None


def parse_object_id(value: str):
    try:
        return ObjectId(value), None
    except (InvalidId, TypeError):
        return None, (jsonify({"error": "Invalid id"}), 400)


@app.route("/")
def home():
    return render_template("index.html")


# -------------------------
# Expenses (scoped per user)
# -------------------------

# Get all expenses for the current user
@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    user_id, err = require_user_id()
    if err:
        return err

    docs = list(expenses_col.find({"userId": user_id}).sort("createdAt", -1))
    out = []
    for d in docs:
        out.append(
            {
                "id": str(d["_id"]),
                "category": d.get("category"),
                "description": d.get("description"),
                "amount": (d.get("amountCents", 0) / 100.0),
                "createdAt": d.get("createdAt").isoformat() if d.get("createdAt") else None,
            }
        )
    return jsonify(out)


# Add an expense (owned by the current user)
@app.route("/api/expenses", methods=["POST"])
def add_expense():
    user_id, err = require_user_id()
    if err:
        return err

    data = request.get_json() or {}

    category = (data.get("category") or "Other").strip()
    description = (data.get("description") or "").strip()

    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    if not description or amount <= 0:
        return jsonify({"error": "Description required and amount must be > 0"}), 400

    doc = {
        "userId": user_id,
        "category": category,
        "description": description,
        "amountCents": int(round(amount * 100)),
        "createdAt": datetime.utcnow(),
    }

    res = expenses_col.insert_one(doc)
    return jsonify({"id": str(res.inserted_id)}), 201


# Delete an expense by id (must belong to current user)
@app.route("/api/expenses/<expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    user_id, err = require_user_id()
    if err:
        return err

    oid, oid_err = parse_object_id(expense_id)
    if oid_err:
        return oid_err

    res = expenses_col.delete_one({"_id": oid, "userId": user_id})
    if res.deleted_count == 0:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"deleted": expense_id})


# Chart summary: totals by category (current user only)
@app.route("/api/expenses/summary", methods=["GET"])
def expenses_summary():
    user_id, err = require_user_id()
    if err:
        return err

    pipeline = [
        {"$match": {"userId": user_id}},
        {"$group": {"_id": "$category", "totalCents": {"$sum": "$amountCents"}}},
        {"$sort": {"totalCents": -1}},
    ]
    agg = list(expenses_col.aggregate(pipeline))
    result = [{"category": r["_id"], "total": r["totalCents"] / 100.0} for r in agg]
    return jsonify(result)


# -------------------------
# Settings (scoped per user)
# -------------------------

@app.route("/api/settings", methods=["POST"])
def save_settings():
    user_id, err = require_user_id()
    if err:
        return err

    data = request.get_json() or {}

    try:
        paycheck = float(data.get("paycheck", 0))
        savings_percent = float(data.get("savingsPercent", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid settings values"}), 400

    settings_col.update_one(
        {"userId": user_id},
        {
            "$set": {
                "paycheckCents": int(round(paycheck * 100)),
                "savingsPercent": savings_percent,
                "updatedAt": datetime.utcnow(),
            }
        },
        upsert=True,
    )

    return jsonify({"ok": True})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    user_id, err = require_user_id()
    if err:
        return err

    doc = settings_col.find_one({"userId": user_id})

    if not doc:
        return jsonify({"paycheck": 0, "savingsPercent": 0})

    return jsonify(
        {
            "paycheck": doc.get("paycheckCents", 0) / 100.0,
            "savingsPercent": doc.get("savingsPercent", 0),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)