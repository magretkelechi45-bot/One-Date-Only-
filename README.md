# Date Invitation Website 💌

## Run locally
1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. Set environment variables `ADMIN_PASSWORD` (a strong password) and `SESSION_SECRET` (random long string).
4. Optional: set `PAYSTACK_SECRET_KEY` to your Paystack **test** secret key for testing.
5. Run `python app.py` and visit `http://localhost:5000`.

## Deploy
Deploy this Flask app on a Python-capable host with HTTPS, persistent storage for `date_site.db`, and the environment variables above. A platform that deletes local files on restart will lose bookings; use a persistent disk or migrate to managed PostgreSQL for production. Run behind a production WSGI server such as gunicorn (`gunicorn app:app`) rather than Flask's development server.

## Important
- Dates are preloaded as **examples**; edit them through Admin before sharing.
- Payment is **voluntary**. A visitor may enter an optional account number, but it is not transmitted or used for payment. The site never collects bank PINs. Paystack securely handles checkout authentication.
- Paystack payment requires your own secret key configured on the server. Never paste it into the HTML.
- Payment verification checks the reference, currency, amount, and Paystack success status.
- Dashboard polls every eight seconds; no push/email notifications are configured.
- Dashboard counts YES/NO clicks in the last 100 events; these are not unique people.
- Bookings use a database-backed global queue, not separate queues per date.
- Visitor identity is self-entered; anonymous clicks cannot identify the visitor.
- Production hardening needed before public launch: CSRF protection, rate limits, stronger admin auth, privacy notice, and database backups.

## Payment flow clarification
Visitors provide an email to initiate optional Paystack checkout. This website does not request or store their bank account numbers, bank PINs, or OTPs. Paystack handles payment credentials on its hosted page.
