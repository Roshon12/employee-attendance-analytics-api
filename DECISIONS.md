# DECISIONS.md

**1. Indexes:** I created a unique index on `employees.emp_code` to prevent duplicate employee codes. A unique compound index on `attendance_logs.emp_code` and `date` ensures one attendance record per employee per day. An index on `date` and `emp_code` supports attendance listing and sorting. An index on `department` and `joined_on` supports department-based queries. I would consider an index on `status` and `date`, but would add it only if query plans show that it improves performance.

**2. Punch-in race:** Two identical requests may both pass the initial duplicate check. Both then attempt to insert a record. The unique compound index allows only one insert; the other raises a duplicate-key error. The API should catch that error and return HTTP 409.

**3. Ties:** The leaderboard uses ranking based on late minutes. Employees tied at the cutoff should all be returned if the contract requires including ties. A secondary sort makes their display order predictable.

**4. Headcount:** The department summary starts from employees and uses a lookup for attendance records. This allows employees with zero logs to remain in the headcount.

**5. Improvement:** I would move remaining Python-side analytics calculations into MongoDB aggregation pipelines and test query performance with execution statistics.