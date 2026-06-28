# IQ Auto Trader

เว็บ dashboard สำหรับทดลอง auto-trade กับ IQ Option โดยเริ่มจาก `demo` mode ก่อน และแยก adapter สำหรับ `iqoption` mode ไว้ต่างหาก

## สรุปไลบรารีที่เลือก

ตอนนี้ยังไม่พบ public official API สำหรับบอทเทรด IQ Option ที่ชัดเจน ไลบรารีที่ใช้งานกันเป็น community/unofficial เป็นหลัก โปรเจกต์นี้จึงเลือก `api-iqoption-faria==7.1.2` เพราะเป็นแพ็กเกจ PyPI ที่ยังใหม่กว่าแพ็กเกจ `iqoptionapi` รุ่นเก่า และ module ภายในยัง expose `iqoptionapi.stable_api.IQ_Option` ที่ใช้กับตัวอย่าง/เอกสาร community ได้

ข้อควรระวัง:

- เริ่มด้วย `broker.mode: demo` และ `broker.account_type: PRACTICE`
- ห้ามเปิด `REAL` จนกว่าจะทดสอบ strategy, risk guard, และสถานะบัญชีจนมั่นใจ
- IQ Option adapter ใช้ API ที่ไม่เป็นทางการ อาจพังได้เมื่อฝั่ง broker เปลี่ยน WebSocket หรือ login flow

## ติดตั้งและรัน

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8887 --reload
```

เปิดเว็บ:

```text
http://127.0.0.1:8887
```

## รันด้วย Docker

ระบบจะ mount `config.yaml`, `data/`, และ `logs/` จากเครื่องเข้า container เพื่อให้ config, credential, SQLite history, และ log ยังอยู่ใน workspace เดิม

```bash
docker compose up -d --build
docker compose logs -f iq-auto-trader
```

หยุด container:

```bash
docker compose down
```

## ตั้งค่า

แก้ไฟล์ `config.yaml`

```yaml
broker:
  mode: demo
  account_type: PRACTICE
  email: ""
  password: ""
  two_factor_code: ""
```

ถ้าจะลองเชื่อม IQ Option:

```yaml
broker:
  mode: iqoption
  account_type: PRACTICE
  email: "your@email.com"
  password: "your-password"
```

ระบบจะไม่อนุญาตให้ยิง `REAL` ถ้า `risk.allow_real_balance` ยังเป็น `false`

ตั้ง auto asset selector:

```yaml
trading:
  asset: EURUSD-OTC
  auto_select_asset: true
  assets:
    - EURUSD-OTC
    - GBPUSD-OTC
    - USDJPY-OTC
    - EURJPY-OTC
    - AUDCAD-OTC
```

ถ้า `auto_select_asset: true` ระบบจะ scan ทุกตัวใน `trading.assets` แต่ timeframe จะล็อกตาม `trading.duration_minutes` เช่นตั้ง `1` จะ scan/open เฉพาะ `1m` ถ้าไม่มีตัวไหนผ่าน `min_confidence` จะไม่เปิด order

## รัน session ทดสอบ

รัน PRACTICE session สูงสุด 15 orders หรือ 60 นาที:

```bash
source .venv/bin/activate
python scripts/run_practice_session.py --max-orders 15 --max-minutes 60
```

ระบบจะเขียน log เพิ่มที่ `logs/practice-session-YYYYMMDD-HHMMSS.log` และยังบันทึกลง SQLite เหมือนเดิม

## โครงสร้างข้อมูล

SQLite อยู่ที่ `data/trading.db`

- `trades`: order/trade history พร้อม status, P/L, confidence, reason, raw response
- `signals`: signal ที่ engine ประเมินในแต่ละ tick
- `events`: log สำคัญของระบบ เช่น start/stop/open/close/error

## API สำคัญ

- `GET /api/status`
- `POST /api/bot/start`
- `POST /api/bot/stop`
- `POST /api/bot/tick`
- `POST /api/trades/manual`
- `GET /api/trades?limit=50`
- `GET /api/events?limit=80`
- `GET /api/equity`
