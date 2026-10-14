"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone, time
from decimal import Decimal, ROUND_HALF_UP
from fastapi import Query
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def create_indexes():
    # Employee codes must be unique, including concurrent requests.
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employee_code",
    )

    # One attendance record per employee per attendance date.
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_employee_date",
    )

    # Attendance filtering, sorting and pagination.
    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="attendance_date_employee",
    )

    # Department-based analytics and employee lookup.
    db.employees.create_index(
        [("department", 1), ("joined_on", 1)],
        name="employee_department_joined",
    )

     # Headcount analytics filters employees by joining date.
    db.employees.create_index(
        [("joined_on", 1)],
        name="employee_joined_on",
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    date_str: str
) -> int:
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)

    local_punch_in = punch_in.astimezone(IST)
    h, m = map(int, shift_start.split(":"))

    shift_start_dt = datetime.combine(
        datetime.fromisoformat(date_str).date(),
        time(h, m),
        tzinfo=IST,
    )

    elapsed_seconds = (
        local_punch_in - shift_start_dt
    ).total_seconds()

    # Late only when more than 10 minutes late.
    if elapsed_seconds <= 600:
        return 0

    return int(elapsed_seconds // 60)



def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round_hours_half_up(
    (punch_out - punch_in).total_seconds() / 3600
)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))



def epoch_ms_to_datetime(value: int) -> datetime:
    """Convert epoch milliseconds to UTC datetime, truncated to seconds."""
    return datetime.fromtimestamp(
        value / 1000, tz=timezone.utc
    ).replace(microsecond=0)


def datetime_to_epoch_ms(value: datetime | None) -> int | None:
    """Convert datetime to epoch milliseconds."""
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return int(value.timestamp() * 1000)


def round_hours_half_up(seconds: int) -> float:
    """Round hours to two decimal places using half-up rounding."""
    hours = Decimal(seconds) / Decimal(3600)
    return float(
        hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None


class PatchAttendanceIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: Optional[str] = None
    regularized_by: Optional[str] = None


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #



@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="MongoDB unavailable"
        )



@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc



@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = {}

    if department:
        q["department"] = department

    skip = (page - 1) * page_size

    total = db.employees.count_documents(q)

    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }




@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    if body.status not in ["PRESENT", "WFH", "ON_DUTY"]:
        raise HTTPException(
            status_code=422,
            detail="Invalid attendance status"
        )

    if body.punched_at is not None:
        ts = epoch_ms_to_datetime(body.punched_at)
    else:
        ts = datetime.now(timezone.utc).replace(microsecond=0)

    local_ts = ts.astimezone(IST)

    shift_start_h, shift_start_m = map(
        int, emp["shift_start"].split(":")
    )
    end_h, end_m = map(int, emp["shift_end"].split(":"))

    overnight = (end_h, end_m) <= (
        shift_start_h, shift_start_m
    )

    attendance_date = local_ts.date()

    if overnight and (local_ts.hour, local_ts.minute) < (
        end_h, end_m
    ):
        attendance_date -= timedelta(days=1)

    d = attendance_date.isoformat()

    if db.attendance_logs.find_one(
        {"emp_code": body.emp_code, "date": d}
    ):
        raise HTTPException(
            status_code=409,
            detail="Attendance record already exists for this date"
        )

    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts, emp["shift_start"], d
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        db.attendance_logs.insert_one(doc)
    except Exception as exc:
        from pymongo.errors import DuplicateKeyError

        if isinstance(exc, DuplicateKeyError):
            raise HTTPException(
                status_code=409,
                detail="Attendance record already exists for this date"
            )
        raise

    doc.pop("_id", None)
    doc["punch_in"] = datetime_to_epoch_ms(ts)

    return doc



@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        q["date"] = {}

        if date_from:
            q["date"]["$gte"] = date_from

        if date_to:
            q["date"]["$lte"] = date_to

        if date_from and date_to and date_from > date_to:
            raise HTTPException(
                status_code=422,
                detail="date_from must not be after date_to"
            )

    if status:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)

    skip = (page - 1) * page_size

    docs = list(
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )

    return {
        "items": docs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Use the supplied timestamp, or current time.
    if body.punched_at is not None:
        ts = epoch_ms_to_datetime(body.punched_at)
    else:
        ts = datetime.now(timezone.utc).replace(microsecond=0)

    # Find the latest open attendance record for this employee.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": ts},
            "punch_out":None,
        },
        sort=[("punch_in", -1)],
    )

    
    if not record:
        existing_record = db.attendance_logs.find_one(
            {
                "emp_code": body.emp_code,
                "punch_in": {"$lte": ts},
                "punch_out": {"$ne": None},
            },
            sort=[("punch_in", -1)],
        )

        if existing_record:
            raise HTTPException(
                status_code=409,
                detail="Attendance already punched out"
            )

        raise HTTPException(
            status_code=404,
            detail="No punch-in record found"
        )


    if record.get("punch_out") is not None:
        raise HTTPException(
            status_code=409,
            detail="Attendance already punched out"
        )

    punch_in_time = record["punch_in"]

    # MongoDB may return a naive datetime; treat it as UTC.
    if punch_in_time.tzinfo is None:
        punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

    elapsed_seconds = int((ts - punch_in_time).total_seconds())

    if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in and within 24 hours"
        )

    shift_end = emp["shift_end"]
    h, m = map(int, shift_end.split(":"))

    shift_start_h, shift_start_m = map(
        int, emp["shift_start"].split(":")
    )

    attendance_day = datetime.fromisoformat(record["date"]).date()
    punch_in_local = punch_in_time.astimezone(IST)
    overnight = (h, m) <= (shift_start_h, shift_start_m)

    end_day = attendance_day
    if overnight:
        end_day += timedelta(days=1)

    shift_end_dt = datetime.combine(
        end_day, time(h, m), tzinfo=IST
    ).astimezone(timezone.utc)

    work_hours = round_hours_half_up(elapsed_seconds)
    overtime_minutes = max(
        0, int((ts - shift_end_dt).total_seconds() // 60)
    )
    if overtime_minutes < 30:
        overtime_minutes = 0

    half_day = work_hours < 4.50

    
    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Attendance was updated by another request"
        )

    return {
        "emp_code": record["emp_code"],
        "date": record["date"],
        "status": record["status"],
        "punch_in": datetime_to_epoch_ms(punch_in_time),
        "punch_out": datetime_to_epoch_ms(ts),
        "work_hours": work_hours,
        "late_minutes": record.get("late_minutes", 0),
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
        "history": record.get("history", []),
    }




@app.patch("/attendance/{emp_code}/{date}")
def patch_attendance(
    emp_code: str,
    date: str,
    body: PatchAttendanceIn,
):
    from pymongo.errors import DuplicateKeyError

    # 1. Validate employee and attendance record.
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")

    record = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": date}
    )
    if not record:
        raise HTTPException(404, "Attendance record not found")

    if not body.reason or not body.reason.strip():
        raise HTTPException(422, "reason is required")

    if not body.regularized_by or not body.regularized_by.strip():
        raise HTTPException(422, "regularized_by is required")

    fields = body.model_fields_set
    status = (
        body.status
        if "status" in fields
        else record.get("status", "PRESENT")
    )

    allowed = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}
    if status not in allowed:
        raise HTTPException(422, "Invalid attendance status")

    old_in = record.get("punch_in")
    old_out = record.get("punch_out")

    def as_utc(value):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    old_in = as_utc(old_in)
    old_out = as_utc(old_out)

    new_in = old_in
    new_out = old_out

    if "punch_in" in fields:
        new_in = (
            epoch_ms_to_datetime(body.punch_in)
            if body.punch_in is not None
            else None
        )

    if "punch_out" in fields:
        new_out = (
            epoch_ms_to_datetime(body.punch_out)
            if body.punch_out is not None
            else None
        )

    # 2. ABSENT and LEAVE records cannot have punch times.
    if status in {"ABSENT", "LEAVE"}:
        if (
            ("punch_in" in fields and body.punch_in is not None)
            or ("punch_out" in fields and body.punch_out is not None)
        ):
            raise HTTPException(
                422,
                "ABSENT and LEAVE cannot have punch times",
            )
        new_in = None
        new_out = None

    else:
        if new_in is None:
            raise HTTPException(
                422,
                "Presence status requires punch_in",
            )

        # Punch-in must belong to this attendance date under R1.
        local_in = new_in.astimezone(IST)
        sh, sm = map(int, emp["shift_start"].split(":"))
        eh, em = map(int, emp["shift_end"].split(":"))
        overnight = (eh, em) <= (sh, sm)

        expected_date = local_in.date()
        if overnight and (local_in.hour, local_in.minute) < (eh, em):
            expected_date -= timedelta(days=1)

        if expected_date.isoformat() != date:
            raise HTTPException(
                422,
                "punch_in does not belong to this attendance date",
            )

        if new_out is not None:
            elapsed = (new_out - new_in).total_seconds()
            if elapsed <= 0 or elapsed > 24 * 60 * 60:
                raise HTTPException(
                    422,
                    "punch_out must be after punch_in and within 24 hours",
                )

    # 3. Recalculate derived fields.
    if status in {"ABSENT", "LEAVE"}:
        work_hours = None
        late_minutes = 0
        overtime_minutes = 0
        half_day = False
    else:
        late_minutes = compute_late_minutes(
            new_in, emp["shift_start"], date
        )

        if new_out is None:
            work_hours = None
            overtime_minutes = 0
            half_day = False
        else:
            seconds = int((new_out - new_in).total_seconds())
            work_hours = round_hours_half_up(seconds)
            half_day = work_hours < 4.50

            end_day = datetime.fromisoformat(date).date()
            if overnight:
                end_day += timedelta(days=1)

            shift_end_dt = datetime.combine(
                end_day, time(eh, em), tzinfo=IST
            ).astimezone(timezone.utc)

            overtime_minutes = max(
                0,
                int((new_out - shift_end_dt).total_seconds() // 60),
            )
            if overtime_minutes < 30:
                overtime_minutes = 0

    old_values = {
        "status": record.get("status", "PRESENT"),
        "punch_in": old_in,
        "punch_out": old_out,
        "work_hours": record.get("work_hours"),
        "late_minutes": record.get("late_minutes", 0),
        "overtime_minutes": record.get("overtime_minutes", 0),
        "half_day": record.get("half_day", False),
    }

    new_values = {
        "status": status,
        "punch_in": new_in,
        "punch_out": new_out,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    # 4. Record only fields that actually changed.
    changed = {
        key: value
        for key, value in new_values.items()
        if old_values[key] != value
    }

    if not changed:
        raise HTTPException(422, "No changes to apply")

    history = record.get("history", [])
    at = datetime.now(timezone.utc).replace(microsecond=0)

    history_entry = {
        "at": at,
        "by": body.regularized_by.strip(),
        "reason": body.reason.strip(),
        "changes": changed,
    }

    update_filter = {"_id": record["_id"]}
    if "history" in record:
        update_filter["history"] = history
    else:
        update_filter["history"] = {"$exists": False}

    update_values = dict(new_values)
    update_values["history"] = history + [history_entry]

    result = db.attendance_logs.update_one(
        update_filter,
        {"$set": update_values},
    )

    if result.modified_count != 1:
        raise HTTPException(
            409,
            "Attendance was updated by another request; retry",
        )

    # 5. Return timestamps in epoch milliseconds.
    def api_value(value):
        if isinstance(value, datetime):
            return datetime_to_epoch_ms(value)
        return value

    response_history = []
    for entry in history + [history_entry]:
        response_history.append({
            "at": api_value(entry["at"]),
            "by": entry["by"],
            "reason": entry["reason"],
            "changes": {
                key: api_value(value)
                for key, value in entry["changes"].items()
            },
        })

    return {
        "emp_code": emp_code,
        "date": date,
        "status": status,
        "punch_in": api_value(new_in),
        "punch_out": api_value(new_out),
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
        "history": response_history,
    }

#Monthly Analytics API
@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(emp_code: str, month: str):
    import re
    from calendar import monthrange
    from datetime import date

    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format"
        )

    try:
        year, month_num = map(int, month.split("-"))
        first_day = date(year, month_num, 1)
        last_day = date(
            year, month_num,
            monthrange(year, month_num)[1]
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    employee = db.employees.find_one({"emp_code": emp_code})

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    joined_on = date.fromisoformat(employee["joined_on"])
    start_day = max(first_day, joined_on)

    working_days = 0
    current_day = start_day

    while current_day <= last_day:
        if current_day.weekday() < 5:
            working_days += 1
        from datetime import timedelta
        current_day += timedelta(days=1)

    records = list(db.attendance_logs.find({
        "emp_code": emp_code,
        "date": {
            "$gte": first_day.isoformat(),
            "$lte": last_day.isoformat()
        }
    }))

    present_days = 0
    leave_days = 0
    late_count = 0

    for record in records:
        record_date = date.fromisoformat(record["date"])

        if record_date.weekday() >= 5:
            continue

        if record.get("status") in ("PRESENT", "WFH", "ON_DUTY"):
            if record.get("half_day", False):
                present_days += 0.5
            else:
                present_days += 1

        if record.get("status") == "LEAVE":
            leave_days += 1

        if record.get("late_minutes", 0) > 0:
            late_count += 1

    attendance_pct = (
        round(present_days / working_days * 100, 2)
        if working_days > 0 else None
    )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": leave_days,
        "late_count": late_count,
        "attendance_pct": attendance_pct
    }


#Department Summary Analytics API
@app.get("/analytics/departments/summary")
def department_summary(month: str, department: Optional[str] = None):
    import re
    from calendar import monthrange
    from datetime import date, timedelta
    from decimal import Decimal, ROUND_HALF_UP

    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format"
        )

    try:
        year, month_num = map(int, month.split("-"))
        first_day = date(year, month_num, 1)
        last_day = date(
            year, month_num,
            monthrange(year, month_num)[1]
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    # Count working days, Monday to Friday
    working_days = 0
    current_day = first_day
    while current_day <= last_day:
        if current_day.weekday() < 5:
            working_days += 1
        current_day += timedelta(days=1)

    # Employees who joined by the end of the selected month
    employee_match = {"joined_on": {"$lte": last_day.isoformat()}}
    if department:
        employee_match["department"] = department

    employee_pipeline = [
        {"$match": employee_match},
        {"$group": {
            "_id": "$department",
            "headcount": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]

    headcounts = {
        row["_id"]: row["headcount"]
        for row in db.employees.aggregate(employee_pipeline)
    }

    attendance_match = {
        "date": {
            "$gte": first_day.isoformat(),
            "$lte": last_day.isoformat()
        }
    }

    if department:
        employee_codes = [
            emp["emp_code"]
            for emp in db.employees.find(
                {"department": department},
                {"emp_code": 1, "_id": 0}
            )
        ]
        attendance_match["emp_code"] = {"$in": employee_codes}

    attendance_pipeline = [
        {"$match": attendance_match},
        {"$lookup": {
            "from": "employees",
            "localField": "emp_code",
            "foreignField": "emp_code",
            "as": "employee"
        }},
        {"$unwind": "$employee"},
        {"$group": {
            "_id": "$employee.department",
            "present_days": {
                "$sum": {
                    "$cond": [
                        {"$in": [
                            "$status",
                            ["PRESENT", "WFH", "ON_DUTY"]
                        ]},
                        {
                            "$cond": [
                                {"$eq": ["$half_day", True]},
                                0.5,
                                1
                            ]
                        },
                        0
                    ]
                }
            },
            "work_hours_sum": {
                "$sum": {
                    "$cond": [
                        {"$and": [
                            {"$in": [
                                "$status",
                                ["PRESENT", "WFH", "ON_DUTY"]
                            ]},
                            {"$ne": ["$work_hours", None]}
                        ]},
                        "$work_hours",
                        0
                    ]
                }
            },
            "work_hours_count": {
                "$sum": {
                    "$cond": [
                        {"$and": [
                            {"$in": [
                                "$status",
                                ["PRESENT", "WFH", "ON_DUTY"]
                            ]},
                            {"$ne": ["$work_hours", None]}
                        ]},
                        1,
                        0
                    ]
                }
            },
            "late_count": {
                "$sum": {
                    "$cond": [
                        {"$gt": [
                            {"$ifNull": ["$late_minutes", 0]}, 0
                        ]},
                        1,
                        0
                    ]
                }
            },
            "total_late_minutes": {
                "$sum": {"$ifNull": ["$late_minutes", 0]}
            },
            "leave_count": {
                "$sum": {
                    "$cond": [
                        {"$eq": ["$status", "LEAVE"]}, 1, 0
                    ]
                }
            },
            "on_duty_count": {
                "$sum": {
                    "$cond": [
                        {"$eq": ["$status", "ON_DUTY"]}, 1, 0
                    ]
                }
            }
        }},
        {"$sort": {"_id": 1}}
    ]

    attendance_rows = {
        row["_id"]: row
        for row in db.attendance_logs.aggregate(attendance_pipeline)
    }

    departments = sorted(set(headcounts) | set(attendance_rows))
    result = []

    for dept in departments:
        headcount = headcounts.get(dept, 0)
        if headcount == 0:
            continue

        row = attendance_rows.get(dept, {})
        hours_count = row.get("work_hours_count", 0)
        average_hours = (
            row.get("work_hours_sum", 0) / hours_count
            if hours_count else None
        )

        result.append({
            "department": dept,
            "headcount": headcount,
            "working_days": working_days,
            "present_days": row.get("present_days", 0),
            "avg_work_hours": (
                float(Decimal(str(average_hours)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )) if average_hours is not None else None
            ),
            "late_count": row.get("late_count", 0),
            "total_late_minutes": row.get("total_late_minutes", 0),
            "leave_count": row.get("leave_count", 0),
            "on_duty_count": row.get("on_duty_count", 0)
        })

    return {"month": month, "items": result}


#LATE LEADERBOARD 
@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = 10,
    department: Optional[str] = None
):
    import re
    from datetime import date
    from calendar import monthrange

    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format"
        )

    if limit < 1:
        raise HTTPException(
            status_code=422,
            detail="limit must be at least 1"
        )

    try:
        year, month_num = map(int, month.split("-"))
        first_day = date(year, month_num, 1)
        last_day = date(
            year, month_num,
            monthrange(year, month_num)[1]
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": first_day.isoformat(),
                    "$lte": last_day.isoformat()
                },
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"}
            }
        },
        {
            "$match": {"total_late_minutes": {"$gt": 0}}
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    if department:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "rank": 1
            }
        }
    ])

    rows = list(db.attendance_logs.aggregate(pipeline))

    # Include every employee tied at the last included rank.
    if len(rows) > limit:
        cutoff_rank = rows[limit - 1]["rank"]
        rows = [row for row in rows if row["rank"] <= cutoff_rank]

    return {
        "month": month,
        "items": rows
    }

#DEPARTMENT TREND



@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
):
    import re
    from datetime import date, timedelta, datetime, time

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", from_date):
        raise HTTPException(422, "'from' must be YYYY-MM-DD")

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", to_date):
        raise HTTPException(422, "'to' must be YYYY-MM-DD")

    try:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(422, "Invalid date")

    if end < start:
        raise HTTPException(422, "'to' must be >= 'from'")

    if (end - start).days + 1 > 92:
        raise HTTPException(422, "Date range cannot exceed 92 days")

    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(404, "Department not found")

    start_s = start.isoformat()
    end_s = end.isoformat()

    start_dt = datetime.combine(start, time.min)
    end_exclusive_dt = datetime.combine(
        end + timedelta(days=1), time.min
    )

    pipeline = [
        {"$match": {"department": department}},
        {"$limit": 1},
        {"$project": {
            "_id": 0,
            "date": {"$dateFromString": {"dateString": start_s}},
            "present_count": {"$literal": 0},
            "late_count": {"$literal": 0}
        }},
        {"$unionWith": {
            "coll": "attendance_logs",
            "pipeline": [
                {"$match": {
                    "date": {"$gte": start_s, "$lte": end_s}
                }},
                {"$lookup": {
                    "from": "employees",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "employee"
                }},
                {"$unwind": "$employee"},
                {"$match": {"employee.department": department}},
                {"$addFields": {
                    "date_obj": {
                        "$dateFromString": {"dateString": "$date"}
                    }
                }},
                {"$group": {
                    "_id": "$date_obj",
                    "present_count": {"$sum": {"$cond": [
                        {"$in": [
                            "$status", ["PRESENT", "WFH", "ON_DUTY"]
                        ]},
                        {"$cond": [
                            {"$eq": ["$half_day", True]}, 0.5, 1
                        ]},
                        0
                    ]}},
                    "late_count": {"$sum": {"$cond": [
                        {"$gt": [
                            {"$ifNull": ["$late_minutes", 0]}, 0
                        ]},
                        1, 0
                    ]}}
                }},
                {"$project": {
                    "_id": 0,
                    "date": "$_id",
                    "present_count": 1,
                    "late_count": 1
                }}
            ]
        }},
        {"$group": {
            "_id": "$date",
            "present_count": {"$sum": "$present_count"},
            "late_count": {"$sum": "$late_count"}
        }},
        {"$project": {
            "_id": 0,
            "date": "$_id",
            "present_count": 1,
            "late_count": 1
        }},
        {"$densify": {
            "field": "date",
            "range": {
                "step": 1,
                "unit": "day",
                "bounds": [start_dt, end_exclusive_dt]
            }
        }},
        {"$set": {
            "present_count": {"$ifNull": ["$present_count", 0]},
            "late_count": {"$ifNull": ["$late_count", 0]}
        }},
        {"$lookup": {
            "from": "employees",
            "let": {"trend_date": {
                "$dateToString": {
                    "format": "%Y-%m-%d",
                    "date": "$date",
                    "timezone": "UTC"
                }
            }},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$department", department]},
                    {"$lte": ["$joined_on", "$$trend_date"]}
                ]}}},
                {"$count": "total"}
            ],
            "as": "hc"
        }},
        {"$set": {
            "headcount": {
                "$ifNull": [
                    {"$arrayElemAt": ["$hc.total", 0]}, 0
                ]
            },
            "is_working_day": {
                "$not": [{"$in": [
                    {"$dayOfWeek": "$date"}, [1, 7]
                ]}]
            }
        }},
        {"$set": {
            "attendance_rate": {
                "$cond": [
                    {"$and": [
                        "$is_working_day",
                        {"$gt": ["$headcount", 0]}
                    ]},
                    {"$round": [
                        {"$divide": [
                            "$present_count", "$headcount"
                        ]},
                        4
                    ]},
                    None
                ]
            }
        }},
        {"$setWindowFields": {
            "sortBy": {"date": 1},
            "output": {
                "moving_avg_7d": {
                    "$avg": "$attendance_rate",
                    "window": {"documents": [-6, 0]}
                }
            }
        }},
        {"$set": {
            "moving_avg_7d": {
                "$cond": [
                    {"$eq": ["$moving_avg_7d", None]},
                    None,
                    {"$round": ["$moving_avg_7d", 4]}
                ]
            }
        }},
        {"$sort": {"date": 1}},
        {"$project": {
            "_id": 0,
            "date": {
                "$dateToString": {
                    "format": "%Y-%m-%d",
                    "date": "$date",
                    "timezone": "UTC"
                }
            },
            "is_working_day": 1,
            "headcount": 1,
            "present_count": 1,
            "laFte_count": 1,
            "attendance_rate": 1,
            "moving_avg_7d": 1
        }}
    ]

    items = list(db.employees.aggregate(pipeline))

    return {
        "department": department,
        "from": start_s,
        "to": end_s,
        "items": items
    }



# ADMIN EXPLAIN API
@app.get("/admin/explain/{endpoint}")
def admin_explain(
    endpoint: str,
    month: Optional[str] = None,
    department: Optional[str] = None,
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    from calendar import monthrange
    from datetime import date
    import re

    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }

    if endpoint not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"endpoint must be one of: {', '.join(sorted(allowed))}",
        )

    def parse_month(value):
        if not value or not re.fullmatch(r"\d{4}-\d{2}", value):
            raise HTTPException(422, "month must be YYYY-MM")
        try:
            year, month_num = map(int, value.split("-"))
            first = date(year, month_num, 1)
            last = date(year, month_num, monthrange(year, month_num)[1])
            return first.isoformat(), last.isoformat()
        except ValueError:
            raise HTTPException(422, "Invalid month")

    if endpoint == "attendance_list":
        query = {}
        if emp_code:
            query["emp_code"] = emp_code

        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to

        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from must be <= date_to")

        explain = db.command({
            "explain": {
                "find": "attendance_logs",
                "filter": query,
                "sort": {"date": -1, "emp_code": 1},
                "skip": 0,
                "limit": 20,
            },
            "verbosity": "executionStats",
        })
        collection = "attendance_logs"

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(422, "emp_code and month are required")

        first, last = parse_month(month)

        explain = db.command({
            "explain": {
                "aggregate": "attendance_logs",
                "pipeline": [
                    {"$match": {
                        "emp_code": emp_code,
                        "date": {"$gte": first, "$lte": last},
                    }},
                    {"$group": {
                        "_id": "$emp_code",
                        "present_days": {"$sum": {"$cond": [
                            {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                            {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                            0,
                        ]}},
                        "late_count": {"$sum": {"$cond": [
                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            1, 0,
                        ]}},
                    }},
                ],
                "cursor": {},
            },
            "verbosity": "executionStats",
        })
        collection = "attendance_logs"

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(422, "month is required")

        first, last = parse_month(month)
        employee_match = {"joined_on": {"$lte": last}}
        if department:
            employee_match["department"] = department

        explain = db.command({
            "explain": {
                "aggregate": "employees",
                "pipeline": [
                    {"$match": employee_match},
                    {"$group": {
                        "_id": "$department",
                        "headcount": {"$sum": 1},
                    }},
                ],
                "cursor": {},
            },
            "verbosity": "executionStats",
        })
        collection = "employees"

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(422, "month is required")

        first, last = parse_month(month)
        pipeline = [
            {"$match": {
                "date": {"$gte": first, "$lte": last},
                "late_minutes": {"$gt": 0},
            }},
            {"$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
            }},
        ]

        explain = db.command({
            "explain": {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {},
            },
            "verbosity": "executionStats",
        })
        collection = "attendance_logs"

    
    else:  # department_trend
        if not department or not from_date or not to_date:
            raise HTTPException(
                422,
                "department, from and to are required",
            )

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", from_date):
            raise HTTPException(422, "'from' must be YYYY-MM-DD")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", to_date):
            raise HTTPException(422, "'to' must be YYYY-MM-DD")

        try:
            start = date.fromisoformat(from_date)
            end = date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(422, "Invalid date")

        if end < start or (end - start).days + 1 > 92:
            raise HTTPException(
                422,
                "Invalid date range; maximum is 92 days",
            )

        start_dt = datetime.combine(
            start, time.min, tzinfo=timezone.utc
        )
        end_exclusive_dt = datetime.combine(
            end + timedelta(days=1), time.min, tzinfo=timezone.utc
        )

        pipeline = [
            {"$match": {
                "date": {
                    "$gte": start.isoformat(),
                    "$lte": end.isoformat(),
                }
            }},
            {"$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }},
            {"$unwind": "$employee"},
            {"$match": {"employee.department": department}},
            {"$addFields": {
                "date_obj": {
                    "$dateFromString": {"dateString": "$date"}
                }
            }},
            {"$group": {
                "_id": "$date_obj",
                "count": {"$sum": 1},
            }},
            {"$project": {
                "_id": 0,
                "date": "$_id",
                "count": 1,
            }},
            {"$sort": {"date": 1}},
            {"$densify": {
                "field": "date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [start_dt, end_exclusive_dt],
                },
            }},
        ]

        explain = db.command({
            "explain": {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {},
            },
            "verbosity": "executionStats",
        })
        collection = "attendance_logs"


    return {
        "endpoint": endpoint,
        "collection": collection,
        "explain": explain,
    }
# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
