import sqlite3
from datetime import date
from contextlib import contextmanager

DB_PATH = "fwc26.db"

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

class Database:
    def init(self):
        with get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT,
                    username TEXT,
                    tokens INTEGER DEFAULT 0,
                    task_channel INTEGER DEFAULT 0,
                    task_twitter INTEGER DEFAULT 0,
                    task_referral INTEGER DEFAULT 0,
                    tasks_done INTEGER DEFAULT 0,
                    total_won INTEGER DEFAULT 0,
                    total_lost INTEGER DEFAULT 0,
                    referrer_id INTEGER,
                    sol_wallet TEXT,
                    joined_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    match_id TEXT,
                    prediction TEXT,
                    amount INTEGER,
                    result TEXT DEFAULT 'pending',
                    settled INTEGER DEFAULT 0,
                    bet_date TEXT DEFAULT CURRENT_DATE,
                    UNIQUE(user_id, match_id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS liquidity (
                    id INTEGER PRIMARY KEY,
                    total INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS settled_matches (
                    match_id TEXT PRIMARY KEY,
                    result TEXT,
                    settled_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS deposits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    txn_hash TEXT UNIQUE,
                    sol_amount REAL,
                    tokens_added INTEGER,
                    status TEXT DEFAULT 'pending',
                    submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    tokens INTEGER,
                    usd_value REAL,
                    sol_wallet TEXT,
                    status TEXT DEFAULT 'pending',
                    requested_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                INSERT OR IGNORE INTO liquidity (id, total) VALUES (1, 0);

                CREATE TABLE IF NOT EXISTS custom_matches (
                    id TEXT PRIMARY KEY,
                    home TEXT,
                    away TEXT,
                    match_date TEXT,
                    time_utc TEXT
                );
            """)
        self.ensure_admin()

    def ensure_admin(self):
        with get_conn() as conn:
            existing = conn.execute("SELECT user_id FROM users WHERE user_id=8710356869").fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO users (user_id, name, username, tokens, task_channel, task_twitter, task_referral, tasks_done) VALUES (?,?,?,?,?,?,?,?)",
                    (8710356869, "Admin", "admin", 100000, 1, 1, 1, 3)
                )

    def register_user(self, user_id, name, username, referrer_id=None):
        with get_conn() as conn:
            existing = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO users (user_id, name, username, tokens, referrer_id) VALUES (?,?,?,?,?)",
                (user_id, name, username, 0, referrer_id)
            )
            if referrer_id:
                ref_count = conn.execute("SELECT COUNT(*) as c FROM users WHERE referrer_id=?", (referrer_id,)).fetchone()["c"]
                if ref_count < 20:
                    conn.execute(
                        "UPDATE users SET task_referral=1, tasks_done=tasks_done+1 WHERE user_id=? AND task_referral=0",
                        (referrer_id,)
                    )
            return True

    def get_user(self, user_id):
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def add_tokens(self, user_id, amount):
        with get_conn() as conn:
            conn.execute("UPDATE users SET tokens=tokens+? WHERE user_id=?", (amount, user_id))

    def deduct_tokens(self, user_id, amount):
        with get_conn() as conn:
            conn.execute("UPDATE users SET tokens=tokens-? WHERE user_id=?", (amount, user_id))

    def complete_task(self, user_id, task_col):
        with get_conn() as conn:
            conn.execute(
                f"UPDATE users SET {task_col}=1, tasks_done=tasks_done+1 WHERE user_id=?",
                (user_id,)
            )

    def set_wallet(self, user_id, wallet):
        with get_conn() as conn:
            conn.execute("UPDATE users SET sol_wallet=? WHERE user_id=?", (wallet, user_id))

    def get_referral_count(self, user_id):
        with get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM users WHERE referrer_id=?", (user_id,)).fetchone()
            return row["c"]

    def place_bet(self, user_id, match_id, prediction, amount):
        """Returns True if placed, False if duplicate (already bet on this match)."""
        with get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO bets (user_id, match_id, prediction, amount) VALUES (?,?,?,?)",
                    (user_id, match_id, prediction, amount)
                )
                return True
            except sqlite3.IntegrityError:
                return False  # UNIQUE(user_id, match_id) violation

    def get_user_bet(self, user_id, match_id):
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM bets WHERE user_id=? AND match_id=?",
                (user_id, match_id)
            ).fetchone()
            return dict(row) if row else None

    def get_bets_for_match(self, match_id):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bets WHERE match_id=? AND settled=0", (match_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def record_win(self, user_id, match_id, amount):
        with get_conn() as conn:
            conn.execute("UPDATE users SET total_won=total_won+? WHERE user_id=?", (amount, user_id))
            conn.execute(
                "UPDATE bets SET result='won', settled=1 WHERE user_id=? AND match_id=?",
                (user_id, match_id)
            )

    def record_loss(self, user_id, match_id, amount):
        with get_conn() as conn:
            conn.execute("UPDATE users SET total_lost=total_lost+? WHERE user_id=?", (amount, user_id))
            conn.execute(
                "UPDATE bets SET result='lost', settled=1 WHERE user_id=? AND match_id=?",
                (user_id, match_id)
            )

    def add_liquidity(self, amount):
        with get_conn() as conn:
            conn.execute("UPDATE liquidity SET total=total+? WHERE id=1", (amount,))

    def mark_match_settled(self, match_id, result):
        with get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO settled_matches (match_id, result) VALUES (?,?)", (match_id, result))
            conn.execute("UPDATE bets SET settled=1 WHERE match_id=? AND settled=0", (match_id,))

    def is_match_settled(self, match_id):
        with get_conn() as conn:
            row = conn.execute("SELECT match_id FROM settled_matches WHERE match_id=?", (match_id,)).fetchone()
            return row is not None

    def submit_deposit(self, user_id, txn_hash, sol_amount):
        with get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO deposits (user_id, txn_hash, sol_amount) VALUES (?,?,?)",
                    (user_id, txn_hash, sol_amount)
                )
                return True
            except:
                return False

    def get_pending_deposits(self):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT d.*, u.name, u.username FROM deposits d JOIN users u ON d.user_id=u.user_id WHERE d.status='pending' ORDER BY d.submitted_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def approve_deposit(self, deposit_id, tokens):
        with get_conn() as conn:
            dep = conn.execute("SELECT * FROM deposits WHERE id=?", (deposit_id,)).fetchone()
            if not dep:
                return False
            conn.execute("UPDATE deposits SET status='approved', tokens_added=? WHERE id=?", (tokens, deposit_id))
            conn.execute("UPDATE users SET tokens=tokens+? WHERE user_id=?", (tokens, dep["user_id"]))
            return dict(dep)

    def get_daily_withdrawn(self, user_id):
        today = str(date.today())
        with get_conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(tokens), 0) as total FROM withdrawals WHERE user_id=? AND status!='rejected' AND DATE(requested_at)=?",
                (user_id, today)
            ).fetchone()
            return row["total"]

    def save_custom_match(self, match_id, home, away, match_date, time_utc):
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO custom_matches (id, home, away, match_date, time_utc) VALUES (?,?,?,?,?)",
                (match_id, home, away, match_date, time_utc)
            )

    def load_custom_matches(self):
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM custom_matches").fetchall()
            return [{"id": r["id"], "home": r["home"], "away": r["away"], "date": r["match_date"], "time": r["time_utc"]} for r in rows]

    def request_withdrawal(self, user_id, tokens, sol_wallet):
        usd = tokens / 100
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO withdrawals (user_id, tokens, usd_value, sol_wallet) VALUES (?,?,?,?)",
                (user_id, tokens, usd, sol_wallet)
            )
            conn.execute("UPDATE users SET tokens=tokens-? WHERE user_id=?", (tokens, user_id))

    def get_pending_withdrawals(self):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT w.*, u.name, u.username FROM withdrawals w JOIN users u ON w.user_id=u.user_id WHERE w.status='pending' ORDER BY w.requested_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def approve_withdrawal(self, withdrawal_id):
        with get_conn() as conn:
            conn.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (withdrawal_id,))

    def get_leaderboard(self, limit=10):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT user_id, name, username, tokens FROM users WHERE user_id != 8710356869 ORDER BY tokens DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_users(self):
        with get_conn() as conn:
            rows = conn.execute("SELECT user_id FROM users WHERE user_id != 8710356869").fetchall()
            return [r["user_id"] for r in rows]

    def get_stats(self):
        today = str(date.today())
        with get_conn() as conn:
            users = conn.execute("SELECT COUNT(*) as c FROM users WHERE user_id != 8710356869").fetchone()["c"]
            tokens = conn.execute("SELECT SUM(tokens) as s FROM users WHERE user_id != 8710356869").fetchone()["s"] or 0
            liquidity = conn.execute("SELECT total FROM liquidity WHERE id=1").fetchone()["total"]
            bets = conn.execute("SELECT COUNT(*) as c FROM bets").fetchone()["c"]
            won = conn.execute("SELECT COUNT(*) as c FROM bets WHERE result='won'").fetchone()["c"]
            lost = conn.execute("SELECT COUNT(*) as c FROM bets WHERE result='lost'").fetchone()["c"]
            bets_today = conn.execute("SELECT COUNT(*) as c FROM bets WHERE bet_date=?", (today,)).fetchone()["c"]
            won_today = conn.execute("SELECT COUNT(*) as c FROM bets WHERE result='won' AND bet_date=?", (today,)).fetchone()["c"]
            lost_today = conn.execute("SELECT COUNT(*) as c FROM bets WHERE result='lost' AND bet_date=?", (today,)).fetchone()["c"]
            return {
                "users": users, "tokens": tokens, "liquidity": liquidity,
                "bets": bets, "won": won, "lost": lost,
                "bets_today": bets_today, "won_today": won_today, "lost_today": lost_today
            }

db = Database()