# hdb-info-bot

A Telegram bot with a casual Singaporean tone that helps you **buy**, **sell**,
or **rent** an HDB flat. Tell it a town, postal code, or district number, and
it pulls real transaction data from [data.gov.sg](https://data.gov.sg/datasets?topics=housing),
crunches recent price/rent stats by flat type, and drops a Google Map with
pins for the areas you asked about.

```
You: /start
Bot: Eh hello there! 👋 I'm your HDB kaki — you looking to buy, sell, or rent?
You: [Buy 🏠]
Bot: Steady, shopping for a place ah! Which area you keen on?
You: Bishan
Bot: Ok here's the lobang for Bishan (last 12 months):
     4 Room — 27 transaction(s)
       Median: $520,000  (typical range $505,000–$535,000)
       ...
     [map image with a pin + legend]
```

## How it works

- **Data**: [data.gov.sg](https://data.gov.sg)'s `datastore_search` API —
  the [Resale Flat Prices](https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view)
  dataset for buy/sell, [Renting Out of Flats](https://data.gov.sg/datasets/d_c9f57187485a850908655db0e8cfe651/view)
  for rent.
- **Locality resolution**: free text ("Bishan", "near AMK"), 6-digit postal
  codes, or district numbers ("D19") are all mapped down to HDB's 26 town
  names — see [`hdb_bot/localities.py`](hdb_bot/localities.py).
- **Stats**: median/mean/percentiles per flat type over the last 12 months,
  plus a year-on-year trend — see [`hdb_bot/stats.py`](hdb_bot/stats.py).
- **Map**: Google Static Maps with one lettered pin per matched town + a text
  legend (Google's marker labels only support a single character, so the
  price itself can't be printed on the pin — see [`hdb_bot/maps.py`](hdb_bot/maps.py)).

## Project layout

```
hdb_bot/            bot package (conversation flow, data client, stats, maps, formatting)
tests/              pytest regression suite (mocked HTTP; no real API calls by default)
scripts/smoke_test.py   manual script that hits the REAL data.gov.sg/Maps APIs
deploy/hdb-bot.service  systemd unit for the Oracle Cloud VM deployment
Dockerfile          container build for the Cloud Run deployment
```

---

## 1. Getting your API keys (start from zero)

### 1a. Telegram bot token

1. In Telegram, message **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`, give it a display name, then a unique username ending in
   `bot` (e.g. `hdb_info_bot`).
3. BotFather replies with a token like `123456789:AAExampleTokenTextHere`.
   Copy it — this is your `TELEGRAM_BOT_TOKEN`.
4. Optional: send `/setcommands` to BotFather and register `start` and
   `cancel` so they show up in Telegram's command menu.

### 1b. data.gov.sg API key (recommended, not strictly required)

The `datastore_search` API works without a key today, but data.gov.sg began
enforcing tighter rate limits on unauthenticated requests from Dec 2025
onwards, so getting a key is worth the two minutes:

1. Go to [data.gov.sg](https://data.gov.sg) and sign up (top-right login
   modal → Sign Up), preferably with an email you can access an OTP on.
2. Once logged in, open your account dashboard and request an API key —
   choose **Developer key** for a personal project like this.
3. Copy the key into `DATA_GOV_SG_API_KEY`.

### 1c. Google Maps Static API key

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a new project (e.g. "hdb-info-bot").
2. Enable billing on the project (Cloud Console → Billing). This sounds
   scary but Google gives **$200/month free credit**, and Static Maps costs
   ~$2 per 1,000 loads — a personal bot won't come close to that.
3. Go to **APIs & Services → Library**, search for **Maps Static API**,
   click Enable.
4. Go to **APIs & Services → Credentials → Create Credentials → API key**.
5. Click **Restrict key**: under "API restrictions" limit it to *Maps Static
   API* only. Under "Application restrictions" you can restrict by IP once
   you know your server's outbound IP (Oracle VM has a fixed public IP;
   Cloud Run's outbound IP isn't fixed unless you set up a static egress —
   for a personal project, API-restriction alone is normally enough).
6. Copy the key into `GOOGLE_MAPS_API_KEY`. If you skip this whole section,
   the bot still works — it just replies with text stats and no map image.

---

## 2. Run it locally

```bash
git clone <this repo>
cd hdb-info-bot
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and fill in TELEGRAM_BOT_TOKEN at minimum
python -m hdb_bot.main
```

Message your bot on Telegram and walk through Buy → a town name → confirm
you get stats back (and a map, if you configured `GOOGLE_MAPS_API_KEY`).

## 3. Run the tests

```bash
pip install -r requirements-dev.txt
pytest                 # fast, all mocked, no network — run this before every deploy
pytest -m live         # hits the REAL data.gov.sg + Google Maps APIs, run occasionally
python scripts/smoke_test.py --town "Toa Payoh"   # eyeball real output
```

---

## 4. Deploy — Option A: Oracle Cloud Always Free VM (polling mode)

Simplest and most reliable option: a genuinely free-forever micro VM, bot
runs in long-polling mode so **no inbound port or public URL is needed at
all**.

1. Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/).
   A card is required for identity verification but you will not be charged
   as long as you stay within the Always Free limits.
2. Console → **Compute → Instances → Create Instance**.
   - Image: **Ubuntu 24.04** (or latest LTS).
   - Shape: click "Change shape" → Always Free-eligible shapes → pick
     `VM.Standard.E2.1.Micro` (AMD, simplest) or an Ampere `VM.Standard.A1.Flex`
     if you want more headroom — both are free-forever.
   - Add your SSH public key (or let Oracle generate a key pair for you).
   - Create. Note the instance's public IP.
3. SSH in and set up the bot:
   ```bash
   ssh ubuntu@<public-ip>
   sudo apt update && sudo apt install -y python3.12-venv git
   sudo useradd -m -s /bin/bash hdbbot
   sudo su - hdbbot
   git clone <this repo> hdb-info-bot
   cd hdb-info-bot
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   nano .env        # fill in TELEGRAM_BOT_TOKEN, DATA_GOV_SG_API_KEY, GOOGLE_MAPS_API_KEY
   chmod 600 .env
   exit              # back to your sudo user
   ```
4. Install the systemd service:
   ```bash
   sudo cp /home/hdbbot/hdb-info-bot/deploy/hdb-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now hdb-bot
   sudo journalctl -u hdb-bot -f     # watch it come up; Ctrl+C to stop watching
   ```
5. No firewall/security-list changes needed — polling only makes outbound
   HTTPS calls.

**Caveat**: Oracle can reclaim Always Free resources on accounts that stay
completely inactive for a long period (historically ~a few months of zero
activity). Logging in to the console occasionally avoids this.

---

## 5. Deploy — Option B: Google Cloud Run (webhook mode)

Serverless, scales to zero, Cloud Run's Always Free tier (2M requests/month)
comfortably covers a personal bot. Needs a GCP billing account on file (same
project as your Maps key works fine) but you won't be charged within the
free quota.

1. Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install) or
   use Cloud Shell in the console.
2. Enable the needed APIs:
   ```bash
   gcloud config set project <your-project-id>
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
   ```
3. Deploy straight from source (uses the provided `Dockerfile`):
   ```bash
   gcloud run deploy hdb-info-bot \
     --source . \
     --region asia-southeast1 \
     --allow-unauthenticated \
     --min-instances=0 \
     --set-env-vars RUN_MODE=webhook,TELEGRAM_BOT_TOKEN=<token>,DATA_GOV_SG_API_KEY=<key>,GOOGLE_MAPS_API_KEY=<key>
   ```
   Note the resulting service URL, e.g. `https://hdb-info-bot-xxxxx-as.a.run.app`.
4. Set `WEBHOOK_URL` to that URL and redeploy (or set it in the same command
   above once you know the URL — Cloud Run URLs are deterministic per
   service+region, so you can predict it and set it in the first deploy too).
5. Point Telegram at your webhook:
   ```bash
   curl "https://api.telegram.org/bot<token>/setWebhook?url=<service-url>"
   curl "https://api.telegram.org/bot<token>/getWebhookInfo"   # should show your URL, no pending errors
   ```
6. `--min-instances=0` keeps it in the free tier (scale-to-zero); the
   tradeoff is a few seconds of cold-start latency on the first message
   after idle. Bump to `--min-instances=1` if you want to eliminate that,
   but note that then incurs a small always-on cost outside the free tier.

---

## 6. Known limitations / things to revisit

- **Map pins are town-centroid, not per-block.** The datasets only carry a
  `town` field, not exact coordinates, so pins mark the general town area —
  matches the data's own granularity.
- **Price can't be printed directly on the pin.** Google Static Maps marker
  labels are a single character only; a future enhancement could render a
  custom marker icon (e.g. via a text-to-image service) with the price baked
  in, at the cost of an extra external dependency.
- **District → town mapping is approximate.** Singapore's postal districts
  are sector groupings that don't align cleanly with HDB town boundaries;
  a few central districts are mostly private housing and get mapped to the
  nearest HDB town with an explanatory note in the bot's reply.
- **In-memory cache only.** Fine for a single always-on process (the Oracle
  VM); on Cloud Run each cold instance starts with an empty cache, which is
  still fine since the datasets update roughly monthly.
- **data.gov.sg rate limits**: get a Developer API key (section 1b) if you
  hit 429s; consider a Production key if this bot gets heavy use.
