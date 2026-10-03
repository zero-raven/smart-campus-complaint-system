-- =====================================================================
-- Seed reference data for the Smart Campus Complaint Management System
-- Idempotent: safe to run repeatedly (ON CONFLICT DO NOTHING / upserts)
-- =====================================================================

BEGIN;

-- ---------------- Departments ----------------
INSERT INTO department (dept_code, dept_name, office_email, office_phone, campus_zone) VALUES
 ('CIVIL',   'Civil Engineering',        'civil@rvce.edu.in',   '080-2839-9101', 'North Block'),
 ('EEE',     'Electrical Engineering',   'eee@rvce.edu.in',     '080-2839-9102', 'East Block'),
 ('HOSTEL',  'Hostel Maintenance',       'hostel@rvce.edu.in',  '080-2839-9103', 'Hostel Block'),
 ('IT',      'IT & Network Infrastructure','it@rvce.edu.in',     '080-2839-9104', 'Admin Block'),
 ('FACULTY', 'Faculty Office',           'faculty@rvce.edu.in', '080-2839-9105', 'Admin Block'),
 ('MESS',    'Mess & Catering',          'mess@rvce.edu.in',    '080-2839-9106', 'Mess Block'),
 ('SECURITY','Campus Security',          'security@rvce.edu.in','080-2839-9107', 'Gate 1'),
 ('ACAD',    'Academic Affairs',         'academic@rvce.edu.in','080-2839-9108', 'Admin Block')
ON CONFLICT (dept_code) DO NOTHING;

-- ---------------- Categories ----------------
INSERT INTO category (category_code, category_name, description) VALUES
 ('ELECTRICAL',     'Electrical',        'Power supply, wiring, switches, appliances'),
 ('PLUMBING',       'Plumbing',          'Water supply, leaks, drainage, washrooms'),
 ('CIVIL',          'Civil / Infrastructure','Building damage, roads, roofs, benches'),
 ('NETWORK',        'Network / IT',      'LAN, WiFi, internet, lab systems, printers'),
 ('HOUSEKEEPING',   'Housekeeping',      'Cleaning, dust, waste, washroom supplies'),
 ('SECURITY',       'Security',          'Safety, lighting, CCTV, access issues'),
 ('EXAMINATION',    'Examination',       'Seating, timetable, results, revaluation'),
 ('MESS',           'Mess / Food',       'Food quality, menu, mess cleanliness'),
 ('LIBRARY',        'Library',           'Books, e-resources, reading room, seating'),
 ('TRANSPORT',      'Transport',         'Bus, parking, cycle tracks'),
 ('SPORTS',         'Sports',            'Ground equipment, gym, tournaments'),
 ('OTHER',          'Other',             'Anything that does not fit above')
ON CONFLICT (category_code) DO NOTHING;

-- ---------------- Priorities ----------------
INSERT INTO priority (priority_code, priority_name, priority_rank, sla_hours, description) VALUES
 ('LOW',      'Low',      1, 168, 'Cosmetic or non-urgent; resolve within a week'),
 ('MEDIUM',   'Medium',   2, 72,  'Routine issue; resolve within three days'),
 ('HIGH',     'High',     3, 24,  'Affects a group of people daily; next-day fix'),
 ('CRITICAL', 'Critical', 4, 4,   'Safety hazard or total outage; fix immediately')
ON CONFLICT (priority_code) DO NOTHING;

-- ---------------- Complaint statuses ----------------
INSERT INTO complaint_status (status_code, status_name, description, is_terminal, sort_order) VALUES
 ('SUBMITTED',   'Submitted',     'Complaint registered and awaiting triage',   FALSE, 1),
 ('TRIAGED',     'Triaged',       'Category and priority confirmed by staff',   FALSE, 2),
 ('ASSIGNED',    'Assigned',      'Given to a staff member for action',         FALSE, 3),
 ('IN_PROGRESS', 'In Progress',   'Work underway on the complaint',             FALSE, 4),
 ('RESOLVED',    'Resolved',      'Action completed, awaiting confirmation',   FALSE, 5),
 ('CLOSED',      'Closed',        'Confirmed by the reporter; lifecycle ends',  TRUE,  6),
 ('REJECTED',    'Rejected',      'Invalid or out-of-scope; lifecycle ends',    TRUE,  7)
ON CONFLICT (status_code) DO NOTHING;

-- ---------------- Allowed status transitions (state machine as data) ----------------
INSERT INTO allowed_transition (status_id, next_status_id, required_role, requires_remark)
SELECT s.status_id, n.status_id, v.role::VARCHAR(20), v.needs_remark
FROM (VALUES
  ('SUBMITTED','TRIAGED',    'STAFF',     FALSE),
  ('SUBMITTED','REJECTED',   'STAFF',     TRUE),
  ('TRIAGED',  'ASSIGNED',   'STAFF',     FALSE),
  ('TRIAGED',  'REJECTED',   'STAFF',     TRUE),
  ('ASSIGNED', 'IN_PROGRESS','STAFF',     FALSE),
  ('ASSIGNED', 'TRIAGED',    'ADMIN',     TRUE),
  ('IN_PROGRESS','RESOLVED', 'STAFF',     TRUE),
  ('IN_PROGRESS','ASSIGNED',  'ADMIN',     TRUE),
  ('RESOLVED', 'CLOSED',     'STUDENT',   FALSE),
  ('RESOLVED', 'IN_PROGRESS','ADMIN',     TRUE)
) AS v(from_code, to_code, role, needs_remark)
JOIN complaint_status s ON s.status_code = v.from_code
JOIN complaint_status n ON n.status_code = v.to_code;

-- ---------------- Campus buildings and locations ----------------
INSERT INTO campus_building (building_code, building_name, building_type, floors, dept_id)
SELECT b.code, b.name, b.btype, b.floors, d.dept_id
FROM (VALUES
  ('MAIN',   'Main Academic Block','ACADEMIC', 5, 'FACULTY'),
  ('CSEBLK', 'CSE Block',          'ACADEMIC', 4, 'FACULTY'),
  ('EEE_BLK','Electrical Block',   'ACADEMIC', 4, 'EEE'),
  ('CIVIL_BLK','Civil Block',      'ACADEMIC', 3, 'CIVIL'),
  ('HOSTEL_A','Hostel Block A',    'HOSTEL',   4, 'HOSTEL'),
  ('ADMIN',  'Administration Block','ADMIN',  3, 'ACAD'),
  ('LIB',    'Central Library',    'ACADEMIC', 3, 'FACULTY'),
  ('MESSBLK','Mess Block',         'MESS',     2, 'MESS'),
  ('GYM',    'Sports Complex',     'SPORTS',   1, 'FACULTY'),
  ('SEC_BLK','Security Block',     'ADMIN',    1, 'SECURITY')
) AS b(code, name, btype, floors, dept_code)
JOIN department d ON d.dept_code = b.dept_code;

INSERT INTO campus_location
    (building_id, location_type, floor_no, room_number, landmark)
SELECT bl.building_id, l.ltype, l.floor_no, l.room_no, l.landmark
FROM (VALUES
  ('CSEBLK',  'ROOM',       2, '208', 'CSE Block second floor'),
  ('CSEBLK',  'LAB',        3, '312', 'Systems Lab'),
  ('CSEBLK',  'LAB',        3, '314', 'Programming Lab'),
  ('CSEBLK',  'WASHROOM',   2, NULL,  'CSE Block washroom'),
  ('CSEBLK',  'COMMON',     1, NULL,  'CSE Block corridor'),
  ('MAIN',    'ROOM',       1, '101', 'Lecture Hall 1'),
  ('MAIN',    'ROOM',       3, '305', 'Lecture Hall 3'),
  ('MAIN',    'COMMON',     1, NULL,  'Main corridor'),
  ('HOSTEL_A','ROOM',       2, '214', 'Hostel A room 214'),
  ('HOSTEL_A','WASHROOM',   3, NULL,  'Hostel A common washroom'),
  ('HOSTEL_A','STAIRCASE',  3, NULL,  'Hostel A stairwell'),
  ('MESSBLK', 'COMMON',     1, NULL,  'Dining hall'),
  ('MESSBLK', 'COMMON',     1, NULL,  'Kitchen entrance'),
  ('LIB',     'COMMON',     2, NULL,  'Reading hall'),
  ('LIB',     'COMMON',     1, NULL,  'Issue counter'),
  ('GYM',     'COMMON',     1, NULL,  'Gym floor'),
  ('EEE_BLK', 'LAB',        2, '201', 'Electrical machines lab')
) AS l(building_code, ltype, floor_no, room_no, landmark)
JOIN campus_building bl ON bl.building_code = l.building_code;

-- ---------------- Triage rules (the configurable rule engine) ----------------
-- Category -> default department
INSERT INTO triage_rule (rule_type, category_id, dept_id, keyword, priority_id, match_weight)
SELECT 'CATEGORY_DEFAULT', c.category_id, d.dept_id, NULL, p.priority_id, 0
FROM (VALUES
  ('ELECTRICAL',   'EEE',     'MEDIUM'),
  ('PLUMBING',     'CIVIL',   'MEDIUM'),
  ('CIVIL',        'CIVIL',   'MEDIUM'),
  ('NETWORK',      'IT',      'HIGH'),
  ('HOUSEKEEPING', 'HOSTEL',  'LOW'),
  ('SECURITY',     'SECURITY','HIGH'),
  ('EXAMINATION',  'ACAD',    'HIGH'),
  ('MESS',         'MESS',    'MEDIUM'),
  ('LIBRARY',      'FACULTY', 'LOW'),
  ('TRANSPORT',    'SECURITY','MEDIUM'),
  ('SPORTS',       'FACULTY', 'LOW'),
  ('OTHER',        'ACAD',    'LOW')
) AS v(category_code, dept_code, priority_code)
JOIN category c   ON c.category_code = v.category_code
JOIN department d ON d.dept_code = v.dept_code
JOIN priority p   ON p.priority_code = v.priority_code;

-- Keyword -> priority override (safety escalation).
-- Where two keywords can match the same text, the rule engine must resolve
-- to the HIGHEST match_weight; the 'accident' rows below deliberately exercise
-- that tie-breaking path (100 CRITICAL vs 30 HIGH).
INSERT INTO triage_rule (rule_type, category_id, keyword, priority_id, match_weight)
SELECT 'KEYWORD', c.category_id, v.keyword, p.priority_id, v.weight
FROM (VALUES
  ('ELECTRICAL','fire',            100, 'CRITICAL'),
  ('ELECTRICAL','sparking',        100, 'CRITICAL'),
  ('ELECTRICAL','short circuit',   100, 'CRITICAL'),
  ('ELECTRICAL','electrocution',   100, 'CRITICAL'),
  ('ELECTRICAL','smoke',           100, 'CRITICAL'),
  ('ELECTRICAL','exposed wire',    100, 'CRITICAL'),
  ('PLUMBING',  'gas leak',        100, 'CRITICAL'),
  ('PLUMBING',  'sewage',           90, 'HIGH'),
  ('PLUMBING',  'no water',         80, 'HIGH'),
  ('PLUMBING',  'contaminated',     80, 'HIGH'),
  ('SECURITY',  'accident',        100, 'CRITICAL'),
  ('SECURITY',  'accident',         30, 'HIGH'),
  ('SECURITY',  'theft',            90, 'HIGH'),
  ('SECURITY',  'harassment',       90, 'HIGH'),
  ('SECURITY',  'stranger',         70, 'HIGH'),
  ('SECURITY',  'cameras not working', 70, 'HIGH'),
  ('NETWORK',   'exam server',      50, 'CRITICAL'),
  ('NETWORK',   'wifi',             40, 'HIGH'),
  ('NETWORK',   'lan cable',        40, 'HIGH')
) AS v(category_code, keyword, weight, priority_code)
JOIN category c ON c.category_code = v.category_code
JOIN priority p ON p.priority_code = v.priority_code;

-- Department-scoped default (global fallback when a category rule is missing)
INSERT INTO triage_rule (rule_type, dept_id, priority_id, match_weight)
SELECT 'DEPARTMENT_DEFAULT', d.dept_id, p.priority_id, 0
FROM (VALUES ('EEE','HIGH'),('IT','HIGH'),('SECURITY','HIGH'),('MESS','MEDIUM'),('HOSTEL','LOW')
) AS v(dept_code, priority_code)
JOIN department d ON d.dept_code = v.dept_code
JOIN priority p  ON p.priority_code = v.priority_code;

-- ---------------- Demo users ----------------
-- Password for every demo account: Campus@2026
INSERT INTO app_user (username, email, password_hash, full_name, role, dept_id, usn, semester, section_name, hostel_name)
SELECT v.username, v.email,
       crypt(v.plain_password, gen_salt('bf')),
       v.full_name, v.role::VARCHAR(20), d.dept_id, v.usn, v.semester, v.section, v.hostel
FROM (VALUES
  ('admin',    'admin@rvce.edu.in',    'Campus@2026','System Administrator','ADMIN',   'ACAD',   NULL,    NULL, NULL, NULL),
  ('dean',     'dean@rvce.edu.in',     'Campus@2026','Dr. Anil Kumar','ADMIN',         'ACAD',   NULL,    NULL, NULL, NULL),
  ('eee.head', 'eeeadh@rvce.edu.in',   'Campus@2026','Dr. Suresh Rao','STAFF',         'EEE',    NULL,    NULL, NULL, NULL),
  ('it.head',  'ithead@rvce.edu.in',   'Campus@2026','Dr. Priya Menon','STAFF',         'IT',     NULL,    NULL, NULL, NULL),
  ('hostel.warden','warden@rvce.edu.in','Campus@2026','Mr. Ramesh Iyer','STAFF',        'HOSTEL', NULL,    NULL, NULL, NULL),
  ('sec.officer','security@rvce.edu.in','Campus@2026','Mr. Deepak Singh','STAFF',        'SECURITY',NULL,   NULL, NULL, NULL),
  ('civil.head','civilhead@rvce.edu.in','Campus@2026','Dr. Fatima Khan','STAFF',         'CIVIL',  NULL,    NULL, NULL, NULL),
  ('viewer',   'viewer@rvce.edu.in',   'Campus@2026','Audit Viewer','VIEWER',         NULL,     NULL,    NULL, NULL, NULL),
  ('nikhil',   'nikhileshnuthalapati@gmail.com','Campus@2026','Nikhilesh N','STUDENT','CIVIL','1RV24CS176',4,'A','Krishna'),
  ('nitin',    'nitin.rvce@outlook.com','Campus@2026','Nitin Gowda R S','STUDENT',      NULL,     '1RV24CS174',4,'A','Krishna')
) AS v(username, email, plain_password, full_name, role, dept_code, usn, semester, section, hostel)
LEFT JOIN department d ON d.dept_code = v.dept_code;

-- Staff profiles for the STAFF-role users
INSERT INTO staff (user_id, dept_id, designation, max_open_complaints, joined_on)
SELECT u.user_id, d.dept_id,
       CASE u.role
         WHEN 'ADMIN' THEN 'Administrator'
         ELSE 'Department Head'
       END,
       10,
       DATE '2020-06-01'
FROM app_user u
JOIN department d ON d.dept_code = (
       SELECT dept_code FROM department WHERE dept_id = u.dept_id)
WHERE u.role = 'STAFF';

-- ---------------- Notifications enabled default ----------------
-- (nothing further required; table created by schema.sql)

-- ---------------- Verification output ----------------
DO $$
DECLARE
    t INT; f INT; s INT;
BEGIN
    SELECT count(*) INTO t FROM information_schema.tables WHERE table_schema='public';
    SELECT count(*) INTO f FROM information_schema.table_constraints
        WHERE constraint_type='FOREIGN KEY' AND table_schema='public';
    SELECT count(*) INTO s FROM triage_rule;
    RAISE NOTICE 'seed complete: % tables, % FKs, % triage rules', t, f, s;
END $$;

COMMIT;
