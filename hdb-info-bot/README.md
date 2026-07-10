# hdb-info-bot

A Telegram bot with a friendly, professional tone that helps you **buy**,
**sell**, or **rent** an HDB flat, find **carpark** availability nearby, or
**compare** prices across districts. Tell it a town, postal code, or
district number, and it pulls real transaction data from
[data.gov.sg](https://data.gov.sg/datasets?topics=housing), summarizes
recent price/rent stats by flat type, and drops a Google Map with pins for
the areas you asked about — plus, on request, the individual HDB blocks
behind those stats as interactive map pins you can pan, zoom, and open in
your own maps app.

```
You: /start
Bot: Hello, and welcome! 👋 I'm your HDB resale and rental information
     assistant. I can help you look at price trends for buying, selling,
     or renting a flat, check nearby carpark availability, or compare
     prices across a few districts. What would you like to do?
You: [Buy 🏠]
Bot: Great, looking to buy a flat. Which area are you interested in?
You: Bishan
Bot: Here is the resale price summary for Bishan (last 12 months):
     4 Room — 27 transaction(s)
       Median: $520,000  (typical range $505,000–$535,000)
       ...
     [map image with a pin + legend]
     [📍 Plot blocks on map]  [🔁 New search]
You: [📍 Plot blocks on map]
Bot: [10 interactive Telegram venue pins, most-transacted blocks first]
     📍 That's 10 of 27 HDB block(s) in Bishan (the most-transacted blocks
     first), sent above as interactive map pins — tap any pin to pan,
     zoom, or open it in your maps app for directions.
```

Every substantive reply ends with a source citation and a disclaimer —
data comes from data.gov.sg, and users are pointed to HDB, CEA, and MND for
authoritative rules (see "Tone, jargon, and citations" below). Send
`/glossary` at any time for plain-English explanations of terms like MOP,
COV, resale levy, or PSF.

Tapping **📍 Plot blocks on map** geocodes the top 10 most-transacted HDB
blocks behind those stats and sends each back as a native Telegram venue —
an interactive map pin you can pan, zoom, or tap to open in your maps app.
Picking **Carparks 🅿️** instead asks for an area, lists nearby HDB carparks
with live lots-available counts, and lets you pick one via inline buttons
to see its full lots breakdown and an interactive map pin. Picking
**Compare Districts 📊** asks for a few areas at once (comma-separated) and
sends back a line chart comparing their monthly average resale price —
this one needs no Google Maps key at all, the chart is rendered locally.

## How it works

- **Data**: every dataset in data.gov.sg's
  [Resale Flat Prices collection](https://data.gov.sg/collections/189/view)
  (5 datasets spanning 1990 to present — the resale market has been split
  across successive datasets over the years) plus
  [Renting Out of Flats](https://data.gov.sg/datasets/d_c9f57187485a850908655db0e8cfe651/view)
  for rent — see the full list in [`hdb_bot/datasets.py`](hdb_bot/datasets.py).
  This covers everything at
  [data.gov.sg/datasets?topics=housing&resultId=189](https://data.gov.sg/datasets?topics=housing&resultId=189).
- **Local-cache architecture**: the bot does **not** query data.gov.sg live
  when a user messages it. [`hdb_bot/data_sync.py`](hdb_bot/data_sync.py)
  downloads a full local CSV copy of every dataset above (using data.gov.sg's
  bulk download flow) once at startup and then on a repeating schedule
  (`SYNC_INTERVAL_HOURS`, default 24h), checking each dataset's metadata
  first so unchanged datasets are skipped. [`hdb_bot/local_store.py`](hdb_bot/local_store.py)
  indexes those local CSVs by town in memory and serves records to the
  conversation flow — so every user message is fast and never subject to
  data.gov.sg's rate limits.
- **Locality resolution**: free text ("Bishan", "near AMK"), 6-digit postal
  codes, or district numbers ("D19") are all mapped down to HDB's 26 town
  names — see [`hdb_bot/localities.py`](hdb_bot/localities.py).
- **Stats**: median/mean/percentiles per flat type over the last 12 months,
  plus a year-on-year trend — see [`hdb_bot/stats.py`](hdb_bot/stats.py).
- **Map**: Google Static Maps with one lettered pin per matched town + a text
  legend (Google's marker labels only support a single character, so the
  price itself can't be printed on the pin — see [`hdb_bot/maps.py`](hdb_bot/maps.py)).
- **Block-level map (on request)**: the **📍 Plot blocks on map** button
  geocodes the top 10 most-transacted HDB blocks (address strings — the
  dataset has no coordinates) behind the last stats shown, using the Google
  Geocoding API, and sends each one back as a native Telegram **venue**
  message — an interactive pin the user can pan, zoom, and tap to open in
  their own maps app, rather than a static image. Geocoding results are
  cached to disk forever (blocks don't move) in
  [`hdb_bot/geocoding.py`](hdb_bot/geocoding.py), so repeat queries for the
  same area are instant and don't re-spend API quota. Venue messages are
  spaced ~0.35s apart to stay clear of Telegram's per-chat flood limits.
- **Carparks**: a 4th top-level option alongside buy/sell/rent. Combines
  data.gov.sg's static
  [HDB Carpark Information](https://data.gov.sg/dataset/hdb-carpark-information)
  dataset (synced locally like everything else) with its **real-time**
  [Carpark Availability API](https://data.gov.sg/datasets/d_ca933a644e55d34fe21f28b8052fac63/view)
  (queried live, since lots-available changes minute to minute and can't be
  cached) — see [`hdb_bot/carparks.py`](hdb_bot/carparks.py). After listing
  nearby carparks, up to `MAX_CARPARK_BUTTONS` (10) are offered as inline
  buttons; picking one sends the full per-lot-type breakdown (not just a
  single "Car" figure — a carpark can separately report cars, heavy
  vehicles, etc.) and that carpark alone as an interactive venue pin.
  Carpark locations come as SVY21 coordinates, converted to lat/lng for free
  with no API call via [`hdb_bot/svy21.py`](hdb_bot/svy21.py).
- **Compare Districts**: a 5th top-level option that takes several
  comma-separated areas (towns/postal codes/district numbers, freely mixed)
  and charts their monthly average resale price side by side over
  `CHART_MONTHS_WINDOW` months (default 24), capped at 6 areas per chart for
  legibility. Rendered locally with matplotlib
  ([`hdb_bot/charts.py`](hdb_bot/charts.py)) — no external chart service and
  no Google Maps key needed, so this feature always works. Areas that fail
  to resolve are reported but don't block the rest of the comparison.
- **Tone, jargon, and citations**: the bot speaks in a friendly-but-professional
  voice throughout (see [`hdb_bot/formatting.py`](hdb_bot/formatting.py)) and
  is explicit that it provides **general market information, not financial,
  legal, or property advice**. Every substantive reply (price stats, carpark
  listings, comparison charts) ends with a citation of data.gov.sg as the
  data source and a pointer to HDB, CEA, and MND for authoritative rules —
  deliberately *not* asserting specific figures like MOP duration or resale
  levy amounts, since those vary by case and change over time; instead
  `/glossary` (any time, any point in the conversation —
  [`hdb_bot/glossary.py`](hdb_bot/glossary.py)) explains the concepts
  (MOP, COV, resale levy, OTP, EIP, PSF, CPF, remaining lease, and the
  statistical terms used in the stats messages) and directs users to the
  relevant official body for current specifics.

## Project layout

```
hdb_bot/
  datasets.py       registry of every data.gov.sg dataset the bot uses
  data_sync.py      downloads/refreshes local CSV copies (metadata-aware, skips unchanged)
  local_store.py    reads the local CSVs, indexed by town, for the conversation flow
  conversation.py   ConversationHandler: /start -> intent -> locality -> results
  localities.py     postal code / district / town-name resolution
  stats.py          median/percentile/trend/monthly-average calculations
  maps.py           Google Static Maps pin + legend builder (town-overview map)
  geocoding.py      Google Geocoding API client + permanent disk cache, for the block map
  svy21.py          SVY21 <-> WGS84 coordinate conversion (carpark locations), no API needed
  carparks.py       carpark info (local cache) + live availability (real-time API), joined
  charts.py         matplotlib line chart for the district price-comparison feature
  formatting.py     friendly-professional message templates + citation footer
  glossary.py       HDB/property jargon explanations (/glossary command) + source citation
  config.py, main.py
data/               local dataset cache (gitignored, created by data_sync.py; ~90MB,
                    plus geocode_cache.json which grows slowly as blocks get plotted)
tests/              pytest regression suite (mocked HTTP; no real API calls by default)
scripts/smoke_test.py   manual script that runs a REAL sync + hits Google Maps
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

data.gov.sg's APIs work without a key today, but they began enforcing
tighter rate limits on unauthenticated requests from Dec 2025 onwards, so
getting a key is worth the two minutes. The bot only calls data.gov.sg from
its background sync job (once at startup, then every `SYNC_INTERVAL_HOURS`)
and the live carpark-availability check, never for most per-user-messages,
so this matters far less here than it would for a live-query bot — but
it's still good practice:

1. Go to [data.gov.sg](https://data.gov.sg) and sign up (top-right login
   modal → Sign Up), preferably with an email you can access an OTP on.
2. Once logged in, open your account dashboard and request an API key —
   choose **Developer key** for a personal project like this.
3. Copy the key into `DATA_GOV_SG_API_KEY`.

The key is sent as an `x-api-key` request header, per data.gov.sg's own
["How to use your API key"](https://guide.data.gov.sg/developer-guide/api-overview/how-to-use-your-api-key)
guide — this is already implemented for you in
[`hdb_bot/data_sync.py`](hdb_bot/data_sync.py) and
[`hdb_bot/carparks.py`](hdb_bot/carparks.py); you only need to supply the
key itself in `.env`.

### 1c. Google Maps API key (Static Maps + Geocoding)

One key, two APIs enabled on it — Static Maps renders every map image;
Geocoding is only used by the opt-in "📍 Plot blocks on map" button.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a new project (e.g. "hdb-info-bot").
2. Enable billing on the project (Cloud Console → Billing). This sounds
   scary but Google gives **$200/month free credit**; Static Maps costs
   ~$2/1,000 loads and Geocoding ~$5/1,000 requests, and geocoding results
   are cached to disk forever (a given HDB block only ever gets geocoded
   once) — a personal bot won't come close to the free credit.
3. Go to **APIs & Services → Library**, search for and Enable **Maps Static
   API**, then do the same for **Geocoding API**.
4. Go to **APIs & Services → Credentials → Create Credentials → API key**.
5. Click **Restrict key**: under "API restrictions" limit it to those two
   APIs. Under "Application restrictions" you can restrict by IP once you
   know your server's outbound IP (Oracle VM has a fixed public IP; Cloud
   Run's outbound IP isn't fixed unless you set up a static egress — for a
   personal project, API-restriction alone is normally enough).
6. Copy the key into `GOOGLE_MAPS_API_KEY`. If you skip this whole section,
   the bot still works — it just replies with text stats and no map images,
   and the "Plot blocks on map" button tells the user maps aren't set up.

---

## 2. Run it locally

```bash
git clone <this repo>
cd hdb-info-bot
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and replace the your-...-here placeholders with real values
# (TELEGRAM_BOT_TOKEN at minimum — see section 1 above for how to get each key)
python -m hdb_bot.main
```

The first run downloads all 7 datasets (~90MB total, a minute or two) before
the bot starts serving — that's expected, it's the initial sync described
above. Message your bot on Telegram and walk through Buy → a town name →
confirm you get stats back (and a map, if you configured `GOOGLE_MAPS_API_KEY`).

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
     --min-instances=1 \
     --set-env-vars RUN_MODE=webhook,TELEGRAM_BOT_TOKEN=<token>,DATA_GOV_SG_API_KEY=<key>,GOOGLE_MAPS_API_KEY=<key>
   ```
   (`--min-instances=1` here on purpose — see the cold-start caveat in step 6.)
   Note the resulting service URL, e.g. `https://hdb-info-bot-xxxxx-as.a.run.app`.
4. Set `WEBHOOK_URL` to that URL and redeploy (or set it in the same command
   above once you know the URL — Cloud Run URLs are deterministic per
   service+region, so you can predict it and set it in the first deploy too).
5. Point Telegram at your webhook:
   ```bash
   curl "https://api.telegram.org/bot<token>/setWebhook?url=<service-url>"
   curl "https://api.telegram.org/bot<token>/getWebhookInfo"   # should show your URL, no pending errors
   ```
6. **Cold-start caveat specific to this bot**: each fresh Cloud Run instance
   starts with an empty `data/` directory (container filesystems aren't
   persisted across instances), so the blocking startup sync has to
   re-download all ~90MB of datasets before that instance can answer its
   first message — this can take a minute, not a few seconds. With the more
   usual `--min-instances=0` (scale-to-zero, strictly free), that
   minute-long sync would happen on *every* cold start, which is a bad user
   experience for a chat bot. Two ways to handle it:
   - `--min-instances=1` (used above) keeps one instance warm permanently —
     a small always-on cost outside the free tier but cheap (a fraction of
     a fraction of a cent/hour for the smallest Cloud Run tier) — so the
     sync only re-runs on `SYNC_INTERVAL_HOURS` in the background, never
     blocking a user.
   - Mount a Cloud Storage bucket as a volume (Cloud Run gen2 supports
     `--add-volume`) at the `data/` path so the cache survives across cold
     starts, letting you go back to `--min-instances=0` and stay fully free
     — more setup, not included in this guide.

---

## 6. Known limitations / things to revisit

- **Regulatory content is deliberately general, not authoritative.** The
  `/glossary` explanations describe *concepts* (what MOP or a resale levy
  is) without stating specific durations, dollar amounts, or percentages,
  since those vary by flat type/scheme and change over time — the bot
  points users to HDB, CEA, and MND for current specifics rather than
  risking a stale or case-specific figure being presented as universal.
  This bot is not a substitute for professional or official advice.
- **The automatic map is town-centroid, not per-block.** The datasets only
  carry a `town` field, not exact coordinates, so the pin sent right after
  stats marks the general town area — matches the data's own granularity.
  Use **📍 Plot blocks on map** for actual per-block pins (see below).
- **Price can't be printed directly on a pin.** Google Static Maps marker
  labels are a single character only; a future enhancement could render a
  custom marker icon (e.g. via a text-to-image service) with the price baked
  in, at the cost of an extra external dependency.
- **Block-map geocoding is capped at `MAX_BLOCK_VENUES` (10, in
  `conversation.py`)**, picking the most-transacted blocks first, to keep
  the button's latency and the number of venue messages reasonable — a
  closing message says how many of the total were actually plotted.
- **Carpark "nearest town" is approximate.** The carpark dataset has no
  `town` field either, only coordinates — each carpark is assigned to
  whichever of the 26 HDB town centroids is numerically closest, which is
  usually right but can be off for carparks near a town boundary.
- **Carpark availability is genuinely real-time and never cached** (lots
  change minute to minute), unlike every other dataset the bot uses — so
  that one call at request time is the sole exception to the "no live
  data.gov.sg calls" design, and if that API is briefly down the bot still
  shows facility info, just without live counts.
- **Carpark lot-type labels are conservative on purpose.** Only `"C"` (Car)
  is confidently documented across public sources; other codes the feed
  uses (`H`, `Y`, `S`, ...) don't have a consistently corroborated meaning,
  so the breakdown shows them as their raw code rather than a guessed full
  name — an inaccurate label would be worse than an unlabelled one.
- **Carpark selection is capped at `MAX_CARPARK_BUTTONS` (10, in
  `conversation.py`)** — only the top 10 (by live availability) are offered
  as pick buttons, even if the text listing above shows more.
- **Compare Districts is resale-only** (average *resale price*, not rent) —
  matches the "average prices" framing of the request; a rent-comparison
  chart would be a straightforward extension of the same code if wanted
  later. Capped at `MAX_COMPARE_ENTRIES` (6, in `conversation.py`) areas per
  chart; months with zero transactions for a given area are left as gaps
  in its line rather than interpolated or shown as zero.
- **District → town mapping is approximate.** Singapore's postal districts
  are sector groupings that don't align cleanly with HDB town boundaries;
  a few central districts are mostly private housing and get mapped to the
  nearest HDB town with an explanatory note in the bot's reply.
- **Local dataset cache needs ~90MB of disk** and a minute or two for the
  first sync. Fine for the Oracle VM (persists across restarts); on Cloud
  Run this interacts with cold starts — see the caveat in section 5.
- **Historical resale eras are combined at read time.** The 5 resale-era
  datasets share `month`/`town`/`flat_type`/`resale_price` but differ in a
  few other columns (e.g. `remaining_lease` is absent before 2015, and
  formatted differently even after) — fine since the bot only ever reads
  the 4 shared fields, but worth knowing if you extend `stats.py`.
- **data.gov.sg rate limits**: get a Developer API key (section 1b) if the
  background sync starts hitting 429s; consider a Production key if you run
  many bot instances against the same key.
