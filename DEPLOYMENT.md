# Going live: HTTPS domain + Google indexing

## Fastest path: a free HTTPS URL in ~15 minutes (no domain purchase)

If you just want `https://something` working in a browser today, use
Render. You get a valid certificate and a managed Postgres without
buying a domain or renting a server.

1. Push this project to a GitHub repo (private is fine).
   ```bash
   git init && git add -A
   git commit -m "Aevyra"
   git remote add origin git@github.com:<you>/<repo>.git
   git push -u origin main
   ```
   Check `.env` is NOT in the commit: `git ls-files | grep .env`
   should show only `.env.example`.

2. https://render.com -> sign up -> **New** -> **Blueprint** ->
   select the repo. It reads `render.yaml` and creates the web
   service plus the database.

3. Paste your keys when prompted (`LITEAPI_KEY`, `GEOAPIFY_API_KEY`,
   `PEXELS_API_KEY`, and whichever else you use). `APP_SECRET_KEY`
   is generated for you; `APP_BASE_URL` is wired to the Render URL
   automatically.

4. Deploy. Migrations run on boot via `start.sh`.

5. Open `https://<your-app>.onrender.com` - that is your live URL,
   typeable in any browser.

Caveat: the free tier sleeps after ~15 minutes idle and takes about a
minute to wake. Fine for testing and for Google's crawler; upgrade
before you promote the site to real customers.

**Fly.io** is an equivalent alternative - see `fly.toml` for the
commands.

Once that works and you want your own name (`https://aevyra.com`),
either add a custom domain in Render's dashboard, or use the
self-hosted VPS route below for full control.

---

Three separate jobs. Do them in order.

1. Put the app on a server reachable from the internet
2. Attach a domain with HTTPS
3. Tell Google the site exists and let it crawl

---

## 0. Before you expose anything

Your current `.env` is a development file. Fix these first - they are
the difference between a demo and something safe to publish.

- [ ] **Rotate every API key** you have pasted into chats, screenshots
      or commits (OpenAI, Anthropic, Gemini, Geoapify, Pexels,
      Ticketmaster, OpenRouteService, OpenWeather, LiteAPI).
- [ ] **Change the Postgres password.** `agent:123456789` must not
      leave your laptop.
- [ ] **Generate a fresh `APP_SECRET_KEY`** for production; do not
      reuse the development one.
      `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- [ ] `APP_ENV=production` and `APP_BASE_URL=https://yourdomain.com`
      Until `APP_ENV=production`, `robots.txt` returns `Disallow: /`
      on purpose, so nothing gets indexed by accident.
- [ ] Confirm `.env` is in `.gitignore` and was never committed:
      `git log --all --full-history -- .env`
- [ ] Create your admin account on the live site and promote it, then
      verify `/admin` rejects logged-out visitors.

---

## 1. Server

Any VPS with 2 GB RAM works (Hetzner, DigitalOcean, Vultr, Scaleway -
roughly 5-10 EUR/month). Ubuntu 24.04.

```bash
# on the server, as root
apt update && apt install -y docker.io docker-compose-plugin git
adduser --disabled-password --gecos "" aevyra
usermod -aG docker aevyra
su - aevyra

git clone <your repo>            # or scp the folder up
cd Travel-Agency-Application
cp .env.example .env
nano .env                         # real values, see checklist above
```

Add these to `.env` for the stack itself:

```
DOMAIN=yourdomain.com
ACME_EMAIL=you@yourdomain.com
POSTGRES_USER=aevyra
POSTGRES_PASSWORD=<long random string>
POSTGRES_DB=aevyra
```

Note: `docker-compose.yml` overrides `DB_URL` to point at the `db`
container, so you do not need to set it yourself.

---

## 2. Domain and HTTPS

Buy a domain (Namecheap, Porkbun, Cloudflare - about 10 EUR/year).
Create two DNS records pointing at your server's IPv4:

```
A     @      203.0.113.10
A     www    203.0.113.10
```

Wait for DNS to propagate (`dig yourdomain.com +short`), then:

```bash
docker compose up -d --build
docker compose exec app alembic upgrade head
docker compose logs -f caddy      # watch the certificate being issued
```

Caddy obtains a Let's Encrypt certificate automatically on first
request and renews it forever. There is no certbot step, no cron job,
and http:// redirects to https:// for you. `www` redirects to the
bare domain so Google never sees two copies of the same page.

Visit `https://yourdomain.com` - that is the URL you can now type in
any browser.

---

## 3. Google

### 3.1 Verify what the crawler sees

```bash
curl https://yourdomain.com/robots.txt
curl https://yourdomain.com/sitemap.xml
curl https://yourdomain.com/sitemap-destinations.xml
```

`robots.txt` should now list `Disallow:` rules and a `Sitemap:` line -
if it says `Disallow: /`, then `APP_ENV` is not `production`.

### 3.2 Search Console

1. https://search.google.com/search-console -> Add property ->
   **URL prefix** -> `https://yourdomain.com`
2. Verify. The DNS TXT method is the most reliable; the HTML-file
   method needs a static file this app does not serve.
3. **Sitemaps** -> submit `sitemap.xml`
4. **URL Inspection** -> paste `https://yourdomain.com/hotels/paris` ->
   **Request indexing** (do this for a handful of your best pages,
   not hundreds)

### 3.3 Realistic expectations

- Indexing takes **days to weeks**. Ranking for competitive terms like
  "hotel in Paris" takes **months to years**, if ever - you are
  competing with Booking.com's domain authority and budget.
- Nobody can guarantee a Google position, and any service that claims
  otherwise is selling something.
- What this codebase gives you is a technically correct foundation:
  unique titles and descriptions, canonical URLs, clean paths,
  breadcrumbs, JSON-LD that matches visible content, a real sitemap,
  faceted URLs excluded from indexing, mobile layout, and fast
  server-rendered pages.
- Where you can realistically win is **long-tail and local**: specific
  neighbourhoods, niche needs, your own city. Generic head terms are
  not a winnable fight from a standing start.
- The honest differentiator is the offer flow, not the SEO: people who
  find you can ask a human to beat a price they already found. Push
  that in your content.

### 3.4 Also worth doing

- Google Business Profile if you have a real trading address
- Bing Webmaster Tools (free, submit the same sitemap)
- Write genuine destination content on the city pages - thin pages
  will not rank, and the code deliberately refuses to mass-generate
  filler

---

## 4. Operating it

```bash
docker compose logs -f app          # application logs
docker compose exec app pytest -q   # test suite on the server
docker compose pull && docker compose up -d --build   # deploy update
docker compose exec app alembic upgrade head          # after a model change
```

**Back up the database** - this is the only irreplaceable thing here:

```bash
docker compose exec db pg_dump -U aevyra aevyra \
  | gzip > backup-$(date +%F).sql.gz
```

Put that in a nightly cron and copy it off the server.

### Payments in production

Stripe test keys must be swapped for live keys, and the webhook must
point at the public URL:

1. Stripe dashboard -> Developers -> Webhooks -> Add endpoint
2. URL: `https://yourdomain.com/api/payments/stripe/webhook`
3. Events: `checkout.session.completed`,
   `checkout.session.expired`, `payment_intent.payment_failed`
4. Copy the signing secret into `STRIPE_WEBHOOK_SECRET`

Taking real money also means real obligations: terms of service, a
privacy policy, a refund policy, and in the EU a cookie/consent notice
plus GDPR handling for the personal data in `hotel_offer_requests`.
Get those in place before the first live payment, not after.

### Email in production

Console logging is fine locally but drops mail on the floor in
production. Set `SMTP_HOST` and friends, or use Resend/Mailgun/SES.
Add SPF and DKIM records for your domain or your confirmations will
land in spam.
