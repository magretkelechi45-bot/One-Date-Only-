import os, sqlite3, secrets, json, urllib.request, urllib.error
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

app=Flask(__name__,static_folder='static')
app.secret_key=os.getenv('SESSION_SECRET',secrets.token_hex(32))
DB=os.getenv('DATABASE_PATH','date_site.db')
PAYSTACK_SECRET=os.getenv('PAYSTACK_SECRET_KEY','')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','')
def conn():
    db=sqlite3.connect(DB,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db
def init():
    with conn() as db:
        db.executescript("""CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY,day TEXT NOT NULL,place TEXT NOT NULL,time TEXT NOT NULL,active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY,ref TEXT UNIQUE NOT NULL,name TEXT NOT NULL,slot_id INTEGER NOT NULL,created TEXT NOT NULL,status TEXT DEFAULT 'confirmed');
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,type TEXT NOT NULL,detail TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payments(ref TEXT PRIMARY KEY,email TEXT,amount INTEGER,status TEXT DEFAULT 'pending',created TEXT NOT NULL);""")
        if not db.execute('SELECT 1 FROM slots').fetchone():
            db.executemany('INSERT INTO slots(day,place,time) VALUES(?,?,?)',[
                ('2026-11-07','Location to be announced','5:00 PM'),
                ('2026-11-14','Location to be announced','4:00 PM'),
                ('2026-11-21','Location to be announced','6:00 PM')])
init()
def now():return datetime.now(timezone.utc).isoformat()
def event(db,typ,detail):db.execute('INSERT INTO events(type,detail,created) VALUES(?,?,?)',(typ,detail,now()))
def admin(fn):
    @wraps(fn)
    def wrapper(*a,**k):
        if not session.get('admin'):return jsonify(error='Unauthorized'),401
        return fn(*a,**k)
    return wrapper
@app.get('/')
def home():return send_from_directory('static','index.html')
@app.get('/api/slots')
def slots():
    with conn() as db:return jsonify([dict(r) for r in db.execute('SELECT * FROM slots WHERE active=1 ORDER BY day,id')])
@app.post('/api/choice')
def choice():
    v=(request.json or {}).get('choice')
    if v not in ('yes','no'):return jsonify(error='Invalid choice'),400
    with conn() as db:event(db,v,'Visitor clicked '+v.upper())
    return jsonify(ok=True)
@app.post('/api/book')
def book():
    d=request.json or {};name=str(d.get('name','')).strip()[:80];slot=d.get('slot_id')
    if not name:return jsonify(error='Enter your name'),400
    with conn() as db:
        r=db.execute('SELECT id FROM slots WHERE id=? AND active=1',(slot,)).fetchone()
        if not r:return jsonify(error='Date unavailable'),400
        ref='DATE-'+secrets.token_hex(5).upper()
        db.execute('INSERT INTO bookings(ref,name,slot_id,created) VALUES(?,?,?,?)',(ref,name,slot,now()))
        event(db,'booking',f'{name} booked slot {slot} ({ref})')
        pos=db.execute("SELECT COUNT(*) FROM bookings WHERE status='confirmed'").fetchone()[0]
    return jsonify(ref=ref,position=pos,ahead=pos-1)
@app.get('/api/booking/<ref>')
def booking(ref):
    with conn() as db:
        r=db.execute("""SELECT b.ref,b.name,b.status,s.day,s.place,s.time,
          (SELECT COUNT(*) FROM bookings x WHERE x.status='confirmed' AND x.id<=b.id) AS position
          FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.ref=?""",(ref,)).fetchone()
        if not r:return jsonify(error='Not found'),404
        out=dict(r);out['ahead']=max(0,out['position']-1)
        return jsonify(out)
@app.post('/api/admin/login')
def login():
    if not ADMIN_PASSWORD:return jsonify(error='Set ADMIN_PASSWORD on the server first'),503
    if secrets.compare_digest(str((request.json or {}).get('password','')),ADMIN_PASSWORD):
        session['admin']=True;return jsonify(ok=True)
    return jsonify(error='Incorrect password'),401
@app.post('/api/admin/logout')
def logout():session.clear();return jsonify(ok=True)
@app.get('/api/admin/data')
@admin
def data():
    with conn() as db:
        return jsonify(slots=[dict(r) for r in db.execute('SELECT * FROM slots ORDER BY day,id')],
        bookings=[dict(r) for r in db.execute('SELECT b.*,s.day,s.place,s.time FROM bookings b JOIN slots s ON s.id=b.slot_id ORDER BY b.id DESC')],
        events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 100')],
        payments=[dict(r) for r in db.execute('SELECT * FROM payments ORDER BY created DESC')])
@app.post('/api/admin/slots')
@admin
def add_slot():
    d=request.json or {}
    if not all(str(d.get(k,'')).strip() for k in ('day','place','time')):return jsonify(error='All fields required'),400
    with conn() as db:db.execute('INSERT INTO slots(day,place,time) VALUES(?,?,?)',(d['day'],d['place'][:160],d['time'][:60]))
    return jsonify(ok=True)
@app.patch('/api/admin/slots/<int:id>')
@admin
def edit_slot(id):
    d=request.json or {}
    fields={k:d[k] for k in ('day','place','time','active') if k in d}
    if not fields:return jsonify(error='No changes'),400
    with conn() as db:db.execute('UPDATE slots SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),id))
    return jsonify(ok=True)
@app.patch('/api/admin/bookings/<int:id>')
@admin
def edit_booking(id):
    status=(request.json or {}).get('status')
    if status not in ('confirmed','cancelled'):return jsonify(error='Invalid status'),400
    with conn() as db:db.execute('UPDATE bookings SET status=? WHERE id=?',(status,id))
    return jsonify(ok=True)
def paystack(path,payload=None):
    headers={'Authorization':'Bearer '+PAYSTACK_SECRET,'Content-Type':'application/json'}
    req=urllib.request.Request('https://api.paystack.co'+path,data=json.dumps(payload).encode() if payload else None,headers=headers)
    with urllib.request.urlopen(req,timeout=15) as res:return json.load(res)
@app.post('/api/paystack/start')
def pay_start():
    if not PAYSTACK_SECRET:return jsonify(error='Paystack is not configured yet'),503
    email=str((request.json or {}).get('email','')).strip()
    if '@' not in email:return jsonify(error='Valid email required'),400
    ref='REJECT-'+secrets.token_hex(8).upper()
    try:
        out=paystack('/transaction/initialize',{'email':email,'amount':500000,'currency':'NGN','reference':ref,'callback_url':request.host_url.rstrip('/')+'/?payment_ref='+ref})
        if not out.get('status'):raise ValueError('Initialization failed')
        with conn() as db:db.execute('INSERT INTO payments(ref,email,amount,created) VALUES(?,?,?,?)',(ref,email,500000,now()))
        return jsonify(url=out['data']['authorization_url'],ref=ref)
    except Exception:return jsonify(error='Could not start checkout'),502
@app.get('/api/paystack/verify/<ref>')
def pay_verify(ref):
    with conn() as db:
        row=db.execute('SELECT * FROM payments WHERE ref=?',(ref,)).fetchone()
        if not row:return jsonify(error='Unknown reference'),404
    if not PAYSTACK_SECRET:return jsonify(error='Not configured'),503
    try:
        result=paystack('/transaction/verify/'+ref)
        d=result.get('data',{})
        success=d.get('status')=='success' and d.get('amount')==500000 and d.get('currency')=='NGN' and d.get('reference')==ref
        with conn() as db:
            old=db.execute('SELECT status FROM payments WHERE ref=?',(ref,)).fetchone()
            if success:
                db.execute("UPDATE payments SET status='paid' WHERE ref=?",(ref,))
                if old['status']!='paid':event(db,'payment','Verified payment '+ref)
        return jsonify(paid=success,status='paid' if success else d.get('status','pending'))
    except Exception:return jsonify(error='Verification unavailable'),502
if __name__=='__main__':
    app.run(debug=False,host='0.0.0.0',port=int(os.getenv('PORT','5000')))
