# REVIEW.md

# Code Review

## Defects Identified and Fixes

| Defect | Expected symptom | Fix applied |
|---|---|---|
| Late-minute threshold was checked after flooring elapsed minutes | A punch-in just over 10 minutes late could be incorrectly marked as on time | Check elapsed seconds against 600 seconds before flooring to whole minutes |
| Repeated punch-out was reported as a missing punch-in | A previously closed attendance record could return 404 instead of 409 | Check for an existing closed record and return 409 when appropriate |
| Employee list pagination lacked input bounds | Invalid page numbers or excessively large page sizes could be accepted | Added validation: page >= 1 and page_size between 1 and 100 |
| Employee results did not have explicit ordering | Results could appear in an inconsistent order across pages | Added sorting by emp_code |
| Attendance list loaded all matching records into Python | Large attendance datasets could consume excess memory and slow pagination | Used MongoDB count, sorting, skip, and limit |
| Attendance list pagination lacked input bounds | Invalid pagination parameters could be accepted | Added page and page_size validation |
| Attendance date range was not validated | A start date later than the end date could produce confusing results | Reject reversed date ranges with HTTP 422 |

## Items Reviewed but Not Classified as Defects

- The unique employee-code index is necessary to prevent duplicate employee codes.
- The unique employee/date attendance index enforces one attendance record per employee per date.
- A conditional update during punch-out helps prevent concurrent requests from closing the same record twice.
- A 404 response is appropriate when the employee or relevant punch-in record does not exist.

## Remaining Verification

- Confirm all endpoint responses match `openapi.yaml`.
- Verify timestamp formats, response field names, and rounding rules.
- Confirm all Admin Explain routes execute the actual corresponding queries with execution statistics.
- Run the complete test suite before submission.
