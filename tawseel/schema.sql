PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL UNIQUE,
    email TEXT,
    company TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    city TEXT,
    address TEXT,
    phone TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_branches_code ON branches(code);

CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'agent',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_staff_branch ON staff(branch_id);
CREATE INDEX IF NOT EXISTS idx_staff_email ON staff(email);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    admin_id INTEGER REFERENCES admins(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    ip TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON auth_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON auth_sessions(expires_at);

CREATE TABLE IF NOT EXISTS staff_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    ip TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_staff_sessions_token ON staff_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_staff_sessions_expiry ON staff_sessions(expires_at);

CREATE TABLE IF NOT EXISTS otp_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    dev_code TEXT,
    purpose TEXT NOT NULL,
    name TEXT,
    email TEXT,
    company TEXT,
    expires_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    resends INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    sent_at INTEGER NOT NULL,
    consumed_at INTEGER,
    ip TEXT
);

CREATE INDEX IF NOT EXISTS idx_otp_phone ON otp_challenges(phone, created_at);

CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    customer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
    sender_name TEXT,
    sender_phone TEXT,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    service_type TEXT NOT NULL DEFAULT 'standard',
    status TEXT NOT NULL DEFAULT 'pending',
    weight_kg REAL,
    pieces INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    amount REAL,
    currency TEXT NOT NULL DEFAULT 'OMR',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_shipments_code ON shipments(code);
CREATE INDEX IF NOT EXISTS idx_shipments_customer ON shipments(customer_id);
CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
CREATE INDEX IF NOT EXISTS idx_shipments_created ON shipments(created_at);

CREATE TABLE IF NOT EXISTS tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    location TEXT,
    note TEXT,
    event_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_shipment ON tracking_events(shipment_id, event_at);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT,
    read_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at);

CREATE TABLE IF NOT EXISTS contact_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT,
    company TEXT,
    origin TEXT,
    destination TEXT,
    weight TEXT,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    handled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_status ON contact_requests(status, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER REFERENCES admins(id) ON DELETE SET NULL,
    staff_id INTEGER REFERENCES staff(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    detail TEXT,
    ip TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

INSERT OR IGNORE INTO settings (key, value) VALUES ('company_name', 'توصيل');
INSERT OR IGNORE INTO settings (key, value) VALUES ('company_name_en', 'Tawseel');
INSERT OR IGNORE INTO settings (key, value) VALUES ('tagline', 'توصيل موثوق، في الوقت المناسب.');
INSERT OR IGNORE INTO settings (key, value) VALUES ('phone', '');
INSERT OR IGNORE INTO settings (key, value) VALUES ('whatsapp', '');
INSERT OR IGNORE INTO settings (key, value) VALUES ('email', 'info@example.com');
INSERT OR IGNORE INTO settings (key, value) VALUES ('address', 'مسقط، سلطنة عُمان');
INSERT OR IGNORE INTO settings (key, value) VALUES ('working_hours', 'الأحد – الخميس، 8:00 ص – 5:00 م');
INSERT OR IGNORE INTO settings (key, value) VALUES ('instagram', '');
INSERT OR IGNORE INTO settings (key, value) VALUES ('twitter', '');
INSERT OR IGNORE INTO settings (key, value) VALUES ('meta_description', 'توصيل — حلول توصيل وشحن للشركات والأفراد في سلطنة عُمان، مع تتبع مباشر للشحنات وخدمة عملاء متاحة للمساعدة.');
INSERT OR IGNORE INTO settings (key, value) VALUES ('sms_status_updates', '0');
