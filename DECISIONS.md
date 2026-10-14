# DECISIONS.md

## 1. Database Indexes

- A unique index on `employees.emp_code` prevents duplicate employee codes.
- A unique compound index on `attendance_logs.emp_code` and `date` ensures one attendance record per employee per day.
- An index on `date` and `emp_code` supports attendance filtering, sorting, and pagination.
- An index on `employees.joined_on` supports headcount queries based on joining dates.
- Additional indexes should be introduced only when query plans and workload justify their cost.

## 2. Concurrent Punch-In and Punch-Out

- The unique employee/date index prevents duplicate attendance records when simultaneous punch-in requests occur.
- Duplicate-key errors should be handled and returned as HTTP 409.
- Punch-out should use a conditional database update so only one concurrent request can close an open attendance record successfully.

## 3. Attendance Calculations

- Attendance dates and shift calculations use the Asia/Kolkata time zone.
- Late arrival is counted only when the delay is strictly greater than the 10-minute grace period.
- Overtime is counted only when it reaches at least 30 minutes after shift end.
- Work hours and analytics rates must follow the rounding rules specified in the assignment.

## 4. Analytics and Query Performance

- Analytics should use MongoDB aggregation pipelines rather than loading complete datasets into Python.
- Department headcount must include employees who have no attendance records during the reporting period.
- Attendance trends must include calendar dates with no attendance records, including weekends.
- Explain endpoints should report execution statistics and use appropriate indexes for their corresponding queries.

## 5. Error Handling and Pagination

- Invalid date ranges and pagination parameters should return appropriate validation errors.
- Missing employees or attendance records should return the appropriate not-found response.
- Repeated punch-out requests should not close an already closed attendance record again.
- Pagination should have sensible limits and deterministic sorting.

## 6. Verification

- The current automated test suite contains six passing tests.
- Additional integration tests are needed for concurrency, regularization history, analytics edge cases, and exact contract compliance.