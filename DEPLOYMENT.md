# دليل النشر — توصيل

هذا الدليل يشرح تجهيز الموقع للنشر. **لم يتم نشر الموقع فعلياً**، ولا توجد hosting أو
نطاق مشتراة. نفّذ الخطوات بعد توفير الخادم والنطاق وبيانات مزوّد SMS.

## 1. قبل البدء

تحتاج إلى:

- حساب استضافة يدعم Python 3.12+ أو Docker.
- نطاق (domain) يمكنك تعديل سجلات DNS الخاصة به.
- شهادة TLS؛ معظم المنصات وCaddy يوفّرانهما تلقائياً.
- مزوّد SMS معتمد في سلطنة عُمان (Twilio أو Unifonic) بعد اكتمال التحقق من المرسل.
- بيانات تواصل حقيقية للشركة: الهاتف، واتساب، البريد، والعنوان.

### متغيرات إلزامية في الإنتاج

| المتغير | ملاحظات |
|---|---|
| `APP_ENV=production` | يفعّل قيود الإنتاج ويعطّل OTP التجريبي والبيانات التجريبية |
| `SECRET_KEY` | قيمة عشوائية طويلة وفريدة؛ لا تعِد استخدام مفتاح التطوير |
| `PUBLIC_BASE_URL` | مثل `https://tawseel.example.com` بدون `/` في النهاية |
| `DATA_DIR` | مجلد دائم وقابل للكتابة لقاعدة البيانات |
| `SHIPMENT_CODE_PREFIX` | اختياري: بادئة أكواد الشحنات المولّدة (افتراضياً `TS`) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | تستخدمان لإنشاء أول مدير عند أول تشغيل فقط |
| `SMS_PROVIDER` | `twilio` أو `unifonic` |
| `TWILIO_*` أو `UNIFONIC_*` | بيانات المزوّد |
| `SESSION_COOKIE_SECURE=1` | إلزامي مع HTTPS؛ يطبّق أيضاً على كوكي جلسة موظفي الفروع |
| `TRUST_PROXY=1` | عند التشغيل خلف reverse proxy موثوق |

أنشئ مفتاحاً سرياً:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 2. تجربة الإنتاج محلياً

قبل النشر، شغّل التطبيق بنمط الإنتاج محلياً في نافذة منفصلة:

```powershell
$env:APP_ENV="production"
$env:SECRET_KEY="ضع-مفتاحاً-طويلاً-هنا"
$env:PUBLIC_BASE_URL="http://127.0.0.1:8080"
$env:DEV_SHOW_OTP="0"
$env:SEED_DEMO="0"
$env:SMS_PROVIDER="log"
$env:SESSION_COOKIE_SECURE="0"   # للتجربة المحلية عبر HTTP فقط
.\run.ps1
```

سيعمل الموقع لكن تسجيل دخول العملاء سيفشل لأن `log` غير مسموح لتسليم OTP في الإنتاج.
هذا متوقع، ويجب ضبط مزوّد SMS حقيقي قبل الفتح للعملاء. عند التجربة عبر HTTPS أو في
الإنتاج، أعد `SESSION_COOKIE_SECURE` إلى `1`.

### إعداد الفروع وحسابات الموظفين في الإنتاج

مع `SEED_DEMO=0` لا توجد فروع أو حسابات موظفين تجريبية. بعد أول دخول إلى
`/admin/login`:

1. افتح `/admin/branches` وأنشئ الفروع الفعلية (الكود، الاسم، المدينة، الهاتف).
2. افتح `/admin/staff` وأنشئ حساباً لكل موظف فرع، وحدّد الفرع والدور وكلمة مرور قوية
   (10 أحرف على الأقل). لا يوجد تسجيل عام للموظفين.
3. أسنِد الشحنات إلى الفروع من إنشاء/تعديل الشحنة في لوحة الإدارة، أو من صفحة تفاصيل
   الشحنة. الشحنة غير المسندة لا تظهر في بوابة أي فرع.
4. سلّم بيانات الدخول للموظف عبر قناة آمنة، واطلب منه تغيير كلمة المرور من
   `/staff/profile` بعد أول دخول.
5. تحقق من بوابة الفرع على `/staff/login`، ومن أن الموظف لا يرى شحنات فرع آخر.

كوكي بوابة الفرع (`tawseel_staff`) وجلسة الموظف منفصلان عن جلسة الإدارة والعميل. إيقاف
الموظف أو الفرع أو تغيير كلمة المرور/الفرع يُنهي جلسات الموظف المفتوحة.

## 3. النشر باستخدام Docker

### بناء الصورة

```bash
docker build -t tawseel-logistics .
```

### تشغيل الحاوية

أنشئ ملف `.env.production` (لا ترفعه إلى Git) يحتوي على قيم الإنتاج، ثم:

```bash
docker run -d \
  --name tawseel \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v tawseel_data:/data \
  --env-file .env.production \
  tawseel-logistics
```

مهم:

- لا تضع `DATA_DIR` داخل `.env.production` بقيمة نسبية؛ الصورة تضبطه على `/data`.
- لا تحذف volume `tawseel_data`؛ يحتوي قاعدة البيانات والحسابات.
- أول تشغيل ينشئ المدير من `ADMIN_EMAIL` و`ADMIN_PASSWORD`، ولا ينشئ فروعاً أو موظفين
  تجريبيين في الإنتاج.
- بعد نجاح أول تشغيل، يمكنك إزالة `ADMIN_PASSWORD` من بيئة الحاوية؛ الحساب موجود بالفعل.
- أنشئ الفروع وحسابات الموظفين من `/admin/branches` و`/admin/staff` بعد الدخول.

### التحقق

```bash
docker logs -f tawseel
curl http://127.0.0.1:8000/health
```

ثم افتح `https://نطاقك/admin/login`.

### التحديث

```bash
docker build -t tawseel-logistics .
docker stop tawseel && docker rm tawseel
docker run -d ... نفس الأمر مع نفس volume ...
```

خُذ نسخة احتياطية من volume قبل كل تحديث.

## 4. النشر على Render

ملف `render.yaml` جاهز كـ Blueprint:

1. ارفع المشروع إلى مستودع GitHub خاص.
2. من Render اختر **New → Blueprint** واربط المستودع.
3. راجع الخدمة `tawseel-logistics` والقرص `tawseel-data` على المسار `/var/data`.
4. أدخل القيم غير المتزامنة (`sync: false`):
   - `PUBLIC_BASE_URL`
   - `ADMIN_EMAIL` و`ADMIN_PASSWORD`
   - بيانات Twilio.
5. انشر الخدمة، ثم تحقق من `/health`.
6. من **Settings → Custom Domains** أضف النطاق واتبع تعليمات DNS.
7. بعد نجاح أول دخول، غيّر كلمة مرور المدير من `/admin/password`.

ملاحظات Render:

- الخطة المجانية قد لا تدعم قرصاً دائماً. بدون قرص دائم ستُفقد قاعدة البيانات عند إعادة النشر.
- Render يوفّر HTTPS تلقائياً، لذلك أبقِ `SESSION_COOKIE_SECURE=1` و`TRUST_PROXY=1`.
- استخدم `workers=1` مع SQLite لتقليل تعارض الكتابة.

## 5. النشر على VPS مع Gunicorn

### تجهيز الخادم

```bash
sudo adduser --system --group --home /opt/tawseel tawseel
sudo mkdir -p /var/lib/tawseel /etc/tawseel
sudo chown -R tawseel:tawseel /opt/tawseel /var/lib/tawseel

cd /opt/tawseel
sudo -u tawseel python3 -m venv .venv
sudo -u tawseel .venv/bin/pip install -r requirements.txt
```

انسخ ملفات المشروع إلى `/opt/tawseel` واجعل ملكيتها `tawseel:tawseel`.

### ملف البيئة

أنشئ `/etc/tawseel/tawseel.env` بصلاحيات `600`:

```ini
APP_ENV=production
SECRET_KEY=...
PUBLIC_BASE_URL=https://tawseel.example.com
DATA_DIR=/var/lib/tawseel
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=...
TRUST_PROXY=1
SESSION_COOKIE_SECURE=1
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM=+...
```

### خدمة systemd

`/etc/systemd/system/tawseel.service`:

```ini
[Unit]
Description=Tawseel website
After=network.target

[Service]
User=tawseel
Group=tawseel
WorkingDirectory=/opt/tawseel
EnvironmentFile=/etc/tawseel/tawseel.env
ExecStart=/opt/tawseel/.venv/bin/gunicorn \
  --bind 127.0.0.1:8000 \
  --workers 1 \
  --threads 8 \
  --timeout 120 \
  wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tawseel
sudo systemctl status tawseel
```

### Caddy (HTTPS تلقائي)

`/etc/caddy/Caddyfile`:

```caddyfile
tawseel.example.com {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

### Nginx (بديل)

```nginx
server {
    listen 443 ssl http2;
    server_name tawseel.example.com;

    # ssl_certificate ...
    # ssl_certificate_key ...

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

## 6. إعداد SMS

### Twilio

1. أنشئ حساب Twilio وفعّل رقم مرسل.
2. اضبط:
   - `SMS_PROVIDER=twilio`
   - `TWILIO_ACCOUNT_SID`
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_FROM` برقم E.164، مثل `+968...`
3. في الحساب التجريبي، أضف أرقام الاختبار إلى Verified Caller IDs.
4. تحقق من متطلبات تسجيل المرسل/المسار في عُمان قبل الإرسال للعملاء.
5. اختبر تسجيل الدخول برقم حقيقي وتأكد من وصول الرمز.

### Unifonic

1. احصل على `AppSid` وSender ID معتمد.
2. اضبط:
   - `SMS_PROVIDER=unifonic`
   - `UNIFONIC_APPSID`
   - `UNIFONIC_SENDER`
   - `UNIFONIC_URL` إذا لزم.
3. تحقق من `/health` ثم اختبر OTP.

بعد ربط المزوّد، فعّل خيار **إرسال SMS عند تحديث حالة الشحنة** من `/admin/settings`
إذا رغبت. كل رسالة تستهلك رصيداً لدى المزوّد.

## 7. النطاق وDNS وTLS

1. اشترِ النطاق من مسجّل معتمد.
2. أضف سجل `A` للخادم أو `CNAME` للمنصة.
3. انتظر انتشار DNS.
4. فعّل شهادة TLS (تلقائي في Caddy/Render، أو Let's Encrypt مع Nginx).
5. اضبط `PUBLIC_BASE_URL` على `https://...` وأعد تشغيل التطبيق.
6. تأكد من تحويل HTTP إلى HTTPS.

## 8. قائمة ما قبل الإطلاق

- [ ] استبدال الهاتف والبريد والعنوان وواتساب من `/admin/settings`.
- [ ] تغيير كلمة مرور المدير الافتراضية.
- [ ] إنشاء الفروع الفعلية من `/admin/branches`.
- [ ] إنشاء حسابات موظفي الفروع من `/admin/staff` وتعيين كل موظف لفرعه الصحيح.
- [ ] إسناد الشحنات إلى الفروع، والتحقق من عزل شحنات كل فرع في `/staff/shipments`.
- [ ] تغيير كلمات مرور الموظفين التجريبية أو إيقاف/حذف الحسابات التجريبية.
- [ ] `APP_ENV=production` و`SECRET_KEY` فريد.
- [ ] `DEV_SHOW_OTP=0` و`SEED_DEMO=0`.
- [ ] `SESSION_COOKIE_SECURE=1` وHTTPS يعمل (يشمل جلسة بوابة الفرع).
- [ ] `TRUST_PROXY=1` فقط عند وجود reverse proxy موثوق.
- [ ] مزوّد SMS مهيأ، و`/health` يظهر `sms: ready`.
- [ ] اختبار OTP لرقم عميل حقيقي.
- [ ] التحقق من `/admin` و`/dashboard` و`/staff` غير مفهرسة في `robots.txt`.
- [ ] أخذ نسخة احتياطية أولية واختبار الاستعادة.
- [ ] مراجعة سياسة الخصوصية والشروط مع مسؤول الشركة.
- [ ] اختبار الموقع على الهاتف وسطح المكتب.
- [ ] التأكد من أن `DATA_DIR` على قرص دائم.

## 9. النسخ الاحتياطي والاستعادة

### SQLite

مع إيقاف التطبيق مؤقتاً:

```bash
sqlite3 /var/lib/tawseel/tawseel.db ".backup '/var/backups/tawseel-$(date +%F).db'"
```

أو باستخدام Python:

```bash
python - <<'PY'
import sqlite3
src = sqlite3.connect('/var/lib/tawseel/tawseel.db')
dst = sqlite3.connect('/var/backups/tawseel-backup.db')
with dst:
    src.backup(dst)
src.close()
dst.close()
PY
```

لا تنسخ `tawseel.db` وحده أثناء عمل التطبيق إذا كانت هناك ملفات `-wal` و`-shm`؛ استخدم
`.backup` أو أوقف التطبيق وانسخ الملفات الثلاثة معاً.

### Docker

```bash
docker run --rm -v tawseel_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/tawseel-data-$(date +%F).tar.gz -C /data .
```

احتفظ بنسخ يومية/أسبوعية في موقع منفصل، واختبر الاستعادة دورياً.

## 10. استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| `SECRET_KEY is required in production` | أضف `SECRET_KEY` إلى بيئة التشغيل |
| `No admin account exists` | اضبط `ADMIN_EMAIL` و`ADMIN_PASSWORD` مؤقتاً أو أنشئ مديراً بالأمر `flask --app wsgi create-admin` |
| OTP لا يصل | راجع `SMS_PROVIDER` والبيانات و`/health` وسجل الخادم |
| 502 من reverse proxy | تأكد أن Gunicorn يعمل على `127.0.0.1:8000` |
| `database is locked` | استخدم عامل Gunicorn واحداً مع SQLite، وتجنب النسخ أثناء الكتابة |
| تسجيل الدخول ينتهي فوراً | تحقق من `SESSION_COOKIE_SECURE` مع HTTP، أو من إعدادات proxy |
| موظف الفرع لا يستطيع الدخول | تأكد من أن الحساب والفرع نشطان، وأن كلمة المرور صحيحة، وأن الجلسة لم تُنهَ بعد تغيير الحساب |
| موظف يرى شحنة لا تخص فرعه | راجع `branch_id` في الشحنة من لوحة الإدارة؛ البوابة لا تعرض إلا شحنات الفرع المطابق |
| فقدان البيانات بعد إعادة النشر | `DATA_DIR` ليس على قرص دائم |
| خطأ CSRF | حدّث الصفحة وأعد إرسال النموذج؛ لا تعطّل الحماية |

## 11. أوامر مفيدة

```bash
# تشغيل محلي
python server.py --port 8080

# اختبارات
python -m unittest discover -s tests -v

# فحص الصحة
curl http://127.0.0.1:8000/health

# قائمة المسارات
flask --app wsgi routes

# إنشاء مدير إضافي
flask --app wsgi create-admin

# تغيير كلمة مرور مدير
flask --app wsgi set-admin-password
```

## 12. حدود النسخة الحالية

- SQLite مناسب لخادم واحد ونسخة واحدة من التطبيق. عند الحاجة إلى عدة نسخ أو كتابة كثيفة،
  انتقل إلى PostgreSQL مع تعديل طبقة قاعدة البيانات.
- لا توجد لوحة Super Admin متعددة الأدوار؛ كل مدير يملك الصلاحيات الكاملة، بينما موظفو
  الفروع لديهم وصول تشغيلي محدود بشحنات فرعهم فقط.
- دورا الموظف `manager` و`agent` معروضان للتنظيم الإداري حالياً، لكنهما يملكان نفس
  صلاحيات التشغيل داخل بوابة الفرع.
- لا توجد فاتورة إلكترونية أو تكامل مع شركات الشحن؛ التتبع يُدار يدوياً من لوحة الإدارة
  أو بوابة الفرع.
- لا يمكن إرسال OTP حقيقي قبل توفير بيانات مزوّد SMS معتمد.
