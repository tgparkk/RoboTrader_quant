import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'robotrader.db'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS candidate_stocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code VARCHAR(10) NOT NULL,
  stock_name VARCHAR(100),
  selection_date DATETIME NOT NULL,
  score REAL NOT NULL,
  reasons TEXT,
  status VARCHAR(20) DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)''')

now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
code = '005930'
name = '삼성전자'
score = 90.0
reason = '테스트 입력'

# remove today's row for idempotency
c.execute("DELETE FROM candidate_stocks WHERE stock_code=? AND DATE(selection_date)=DATE('now','localtime')", (code,))
# insert new
c.execute(
    'INSERT INTO candidate_stocks (stock_code, stock_name, selection_date, score, reasons, status, created_at) '
    'VALUES (?,?,?,?,?,\'active\',?)',
    (code, name, now, score, reason, now)
)
conn.commit()
conn.close()
print(f'Inserted candidate {code} {name} at {now}')
