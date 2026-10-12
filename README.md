# Employee Attendance & Analytics API

A FastAPI application for employee management, attendance tracking, and attendance analytics using MongoDB.

## Requirements

- Python 3.10 or later
- MongoDB 6.0 or later
- pip

## Setup on Windows

Open PowerShell in the project directory.

```powershell
cd D:\candidate_kit
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Make sure MongoDB is running locally. The application uses `attendance_db` as its default database and connects to `mongodb://localhost:27017` unless environment variables override these settings.

To use a different MongoDB connection, set `MONGO_URI` and optionally `MONGO_DB` before starting the application.

## Run the API

```powershell
python -m uvicorn app.main:app --port 8000
```

Open the interactive API documentation:

http://127.0.0.1:8000/docs

Health check:

http://127.0.0.1:8000/health

## Main Features

- Employee creation and listing
- Attendance punch-in and punch-out
- Attendance filtering and pagination
- Employee monthly analytics
- Department summaries and trends
- Late-arrival leaderboard
- Admin query execution plans

## Project Files

- `app/main.py` — API implementation
- `requirements.txt` — Python dependencies
- `openapi.yaml` — API contract
- `DATA_MODEL.md` — database model documentation
- `REVIEW.md` — code review findings
- `DECISIONS.md` — technical decisions

## Before Submission

Run the syntax check, verify MongoDB connectivity, test the documented endpoints, and confirm the API responses match the provided contract. Do not commit credentials, `.env` files, or other secrets.