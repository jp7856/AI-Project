import os
import smtplib
import json
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///events.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

db = SQLAlchemy(app)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    location = db.Column(db.String(300), default='')
    color = db.Column(db.String(20), default='#3788d8')
    notify_email = db.Column(db.String(500), default='')
    notified_1month = db.Column(db.Boolean, default=False)
    notified_2weeks = db.Column(db.Boolean, default=False)
    revenue = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'start': self.start_date.isoformat(),
            'end': (self.end_date + timedelta(days=1)).isoformat(),
            'location': self.location,
            'backgroundColor': self.color,
            'borderColor': self.color,
            'notify_email': self.notify_email,
            'notified_1month': self.notified_1month,
            'notified_2weeks': self.notified_2weeks,
            'revenue': self.revenue,
        }


class EmailSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    smtp_host = db.Column(db.String(200), default='smtp.gmail.com')
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(200), default='')
    smtp_password = db.Column(db.String(300), default='')
    sender_name = db.Column(db.String(200), default='행사 일정표')
    use_tls = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'smtp_host': self.smtp_host,
            'smtp_port': self.smtp_port,
            'smtp_user': self.smtp_user,
            'smtp_password': '●' * len(self.smtp_password) if self.smtp_password else '',
            'sender_name': self.sender_name,
            'use_tls': self.use_tls,
        }


def get_email_settings():
    settings = EmailSettings.query.first()
    if not settings:
        settings = EmailSettings()
        db.session.add(settings)
        db.session.commit()
    return settings


FIXED_RECIPIENTS = [
    'jp@neungyule.com',
    'kwonyh@neungyule.com',
    'ssem2@neungyule.com',
]


def send_notification_email(event, notice_type):
    settings = get_email_settings()
    if not settings.smtp_user or not settings.smtp_password:
        print(f"[알림] 이메일 설정이 없어 발송 스킵: {event.title}")
        return False

    extra = [e.strip() for e in (event.notify_email or '').split(',') if e.strip()]
    recipients = list(dict.fromkeys(FIXED_RECIPIENTS + extra))

    days_left = (event.start_date - date.today()).days
    if notice_type == '1month':
        subject = f"[행사 알림] 1개월 전 - {event.title}"
        notice_text = "1개월"
    else:
        subject = f"[행사 알림] 2주 전 - {event.title}"
        notice_text = "2주"

    body = f"""
안녕하세요,

'{event.title}' 행사가 {notice_text} 후에 시작됩니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 행사명: {event.title}
📆 일정: {event.start_date.strftime('%Y년 %m월 %d일')} ~ {event.end_date.strftime('%Y년 %m월 %d일')}
📍 장소: {event.location or '미정'}
📝 내용: {event.description or '-'}
⏰ D-{days_left}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

준비에 참고하시기 바랍니다.

- 행사 일정표 시스템 -
"""

    try:
        msg = MIMEMultipart()
        msg['From'] = f"{settings.sender_name} <{settings.smtp_user}>"
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        if settings.use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)

        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, recipients, msg.as_string())
        server.quit()
        print(f"[이메일 발송 완료] {event.title} - {notice_type} ({', '.join(recipients)})")
        return True
    except Exception as e:
        print(f"[이메일 발송 오류] {event.title}: {e}")
        return False


def check_and_send_notifications():
    with app.app_context():
        today = date.today()
        events = Event.query.all()
        for event in events:
            days_until = (event.start_date - today).days

            if 28 <= days_until <= 32 and not event.notified_1month:
                if send_notification_email(event, '1month'):
                    event.notified_1month = True
                    db.session.commit()

            if 12 <= days_until <= 16 and not event.notified_2weeks:
                if send_notification_email(event, '2weeks'):
                    event.notified_2weeks = True
                    db.session.commit()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/events')
def events():
    return render_template('events.html')


@app.route('/settings')
def settings():
    s = get_email_settings()
    return render_template('settings.html', settings=s)


@app.route('/api/events', methods=['GET'])
def get_events():
    year = request.args.get('year', datetime.now().year, type=int)
    events = Event.query.filter(
        db.extract('year', Event.start_date) == year
    ).all()
    all_events = Event.query.all()
    result = [e.to_dict() for e in all_events]
    return jsonify(result)


@app.route('/api/events', methods=['POST'])
def create_event():
    data = request.json
    try:
        rev = data.get('revenue')
        event = Event(
            title=data['title'],
            description=data.get('description', ''),
            start_date=date.fromisoformat(data['start_date']),
            end_date=date.fromisoformat(data['end_date']),
            location=data.get('location', ''),
            color=data.get('color', '#3788d8'),
            notify_email=data.get('notify_email', ''),
            revenue=float(rev) if rev not in (None, '') else None,
        )
        db.session.add(event)
        db.session.commit()
        return jsonify(event.to_dict()), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/events/<int:event_id>', methods=['GET'])
def get_event(event_id):
    event = db.get_or_404(Event, event_id)
    d = event.to_dict()
    d['start_date'] = event.start_date.isoformat()
    d['end_date'] = event.end_date.isoformat()
    return jsonify(d)


@app.route('/api/events/<int:event_id>', methods=['PUT'])
def update_event(event_id):
    event = db.get_or_404(Event, event_id)
    data = request.json
    try:
        event.title = data.get('title', event.title)
        event.description = data.get('description', event.description)
        event.start_date = date.fromisoformat(data['start_date'])
        event.end_date = date.fromisoformat(data['end_date'])
        event.location = data.get('location', event.location)
        event.color = data.get('color', event.color)
        event.notify_email = data.get('notify_email', event.notify_email)
        event.notified_1month = False
        event.notified_2weeks = False
        rev = data.get('revenue')
        event.revenue = float(rev) if rev not in (None, '') else None
        db.session.commit()
        return jsonify(event.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/events/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    event = db.get_or_404(Event, event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': '삭제 완료'})


@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.json
    settings = get_email_settings()
    settings.smtp_host = data.get('smtp_host', settings.smtp_host)
    settings.smtp_port = int(data.get('smtp_port', settings.smtp_port))
    settings.smtp_user = data.get('smtp_user', settings.smtp_user)
    if data.get('smtp_password') and not all(c == '●' for c in data['smtp_password']):
        settings.smtp_password = data['smtp_password']
    settings.sender_name = data.get('sender_name', settings.sender_name)
    settings.use_tls = data.get('use_tls', settings.use_tls)
    db.session.commit()
    return jsonify({'message': '저장 완료'})


@app.route('/api/test-email', methods=['POST'])
def test_email():
    data = request.json
    test_to = data.get('email', '')
    if not test_to:
        return jsonify({'error': '수신 이메일을 입력하세요'}), 400

    settings = get_email_settings()
    if not settings.smtp_user or not settings.smtp_password:
        return jsonify({'error': 'SMTP 설정을 먼저 저장하세요'}), 400

    try:
        msg = MIMEMultipart()
        msg['From'] = f"{settings.sender_name} <{settings.smtp_user}>"
        msg['To'] = test_to
        msg['Subject'] = '[행사 일정표] 테스트 이메일'
        msg.attach(MIMEText('이메일 설정이 정상적으로 작동합니다.', 'plain', 'utf-8'))

        if settings.use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)

        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, [test_to], msg.as_string())
        server.quit()
        return jsonify({'message': f'{test_to}로 테스트 메일을 발송했습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/revenue/summary', methods=['GET'])
def revenue_summary():
    events = Event.query.filter(Event.revenue.isnot(None)).all()

    monthly = {}
    yearly = {}
    for ev in events:
        y = ev.end_date.year
        m = ev.end_date.month
        key_m = f"{y}-{m:02d}"
        monthly[key_m] = monthly.get(key_m, 0) + ev.revenue
        yearly[y] = yearly.get(y, 0) + ev.revenue

    monthly_list = [
        {'year': int(k[:4]), 'month': int(k[5:]), 'label': f"{k[:4]}년 {int(k[5:])}월", 'total': v}
        for k, v in sorted(monthly.items())
    ]
    yearly_list = [
        {'year': y, 'label': f"{y}년", 'total': t}
        for y, t in sorted(yearly.items())
    ]
    grand_total = sum(ev.revenue for ev in events)

    return jsonify({
        'monthly': monthly_list,
        'yearly': yearly_list,
        'grand_total': grand_total,
    })


@app.route('/revenue')
def revenue_page():
    return render_template('revenue.html')


@app.route('/api/notify-now', methods=['POST'])
def notify_now():
    check_and_send_notifications()
    return jsonify({'message': '알림 확인 완료'})


def migrate_db():
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(event)"))
            cols = [row[1] for row in result.fetchall()]
            if 'revenue' not in cols:
                conn.execute(text('ALTER TABLE event ADD COLUMN revenue FLOAT'))
                conn.commit()
    except Exception as e:
        print(f"[마이그레이션] {e}")


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        migrate_db()
        get_email_settings()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_and_send_notifications,
        'cron',
        hour=9,
        minute=0,
        id='daily_notification'
    )
    scheduler.start()

    print("=" * 50)
    print("  행사 일정표 서버 시작")
    print("  http://127.0.0.1:5000")
    print("=" * 50)
    app.run(debug=False, use_reloader=False)
