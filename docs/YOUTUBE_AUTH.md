# YouTube Authentication and Download Errors

When running Stashcast on cloud VMs (Oracle Cloud, AWS, GCP, Azure, etc.), you may encounter these errors:

```
ERROR: [youtube] Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies for the authentication.
```

```
ERROR: unable to download video data: HTTP Error 403: Forbidden
```

The first happens because YouTube flags datacenter IP ranges as potential bots. The
second is different: metadata extraction succeeded, but the actual media download was
rejected. See [Fixing HTTP Error 403](#fixing-http-error-403-forbidden) for that one.

This guide covers several workarounds.

## Fixing HTTP Error 403: Forbidden

A 403 during the download phase (not during extraction) almost always means the stream
URL yt-dlp obtained is not valid for this request. Work through these in order.

### 1. Make sure a JavaScript runtime is installed

This is the most common cause. YouTube protects its stream URLs with a JavaScript
challenge in the player. Without a JS runtime yt-dlp cannot solve it, falls back to
player clients whose URLs are frequently rejected, and the download 403s. The log shows:

```
WARNING: [youtube] No supported JavaScript runtime could be found.
```

The Docker image ships Deno, so **rebuild the image** if you are on an older one:

```bash
docker compose build --no-cache && docker compose up -d
```

For a bare-metal install, `bootstrap.sh` installs Deno, or do it by hand:

```bash
curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s -- --yes
deno --version
```

yt-dlp finds `deno` on `PATH` automatically. If you already have another runtime
(node, bun, quickjs), point Stashcast at it instead:

```bash
STASHCAST_YTDLP_JS_RUNTIMES=node
# or with an explicit path
STASHCAST_YTDLP_JS_RUNTIMES=node:/usr/local/bin/node
```

### 2. Update yt-dlp

YouTube changes its player regularly, and an outdated yt-dlp fails in exactly this way.
The version in use is written to the download log of every item, so check it there first.

```bash
# Inside the container
docker compose exec web pip install --upgrade yt-dlp
# Or permanently, by rebuilding the image
docker compose build --no-cache
```

### 3. Let the automatic player-client fallback do its job

Stashcast retries a failed download with alternative YouTube player clients before
giving up, clearing yt-dlp's player cache between attempts. The chain is configurable:

```bash
STASHCAST_YTDLP_PLAYER_CLIENTS=default,tv,web_safari,mweb,tv_embedded
```

`default` means "whatever yt-dlp picks on its own". Setting a single value disables
the fallback. Pinning a client yourself via
`--extractor-args "youtube:player_client=..."` also disables it, since your choice wins.

### 4. Supply cookies from a logged-in session

The most reliable fix, and the one that also clears "Sign in to confirm you're not a
bot". Export cookies for youtube.com in Netscape format (a browser extension such as
"Get cookies.txt" does this), put the file where the app can read it, and set:

```bash
STASHCAST_YTDLP_COOKIES_FILE=/data/cookies.txt
```

In Docker, mount it read-only:

```yaml
volumes:
  - ./cookies.txt:/data/cookies.txt:ro
```

Use a throwaway Google account: yt-dlp requests can get the account rate-limited.
Cookies also expire, so refresh the file when 403s return.

If Stashcast runs directly on a machine with a browser, read them live instead:

```bash
STASHCAST_YTDLP_COOKIES_FROM_BROWSER=firefox
# or a specific profile
STASHCAST_YTDLP_COOKIES_FROM_BROWSER=chrome:Default
```

### 5. Impersonate a browser TLS fingerprint

Some CDN edges reject the default Python HTTP fingerprint. `curl_cffi` ships with the
image, so this only needs enabling:

```bash
STASHCAST_YTDLP_IMPERSONATE=chrome
```

Leave it empty to disable. An unavailable target makes yt-dlp fail at startup with
"Impersonate target is not available", which means `curl_cffi` is missing.

### 6. Route around a flagged IP

If none of the above helps, the IP itself is the problem - continue with
[Option 1: Residential Proxy](#option-1-residential-proxy-recommended) below.

### Reference: 403-related settings

| Variable | Default | Purpose |
|----------|---------|---------|
| `STASHCAST_YTDLP_JS_RUNTIMES` | (auto-detect `deno`) | JS runtime for player challenges |
| `STASHCAST_YTDLP_PLAYER_CLIENTS` | `default,tv,web_safari,mweb,tv_embedded` | Clients retried after a 403 |
| `STASHCAST_YTDLP_COOKIES_FILE` | (none) | Netscape cookies.txt path |
| `STASHCAST_YTDLP_COOKIES_FROM_BROWSER` | (none) | Read cookies from a local browser |
| `STASHCAST_YTDLP_IMPERSONATE` | (none) | Browser TLS fingerprint, e.g. `chrome` |
| `STASHCAST_YTDLP_PROXY` | (none) | Proxy for all yt-dlp traffic |
| `STASHCAST_YTDLP_RETRIES` | `10` | Download retries |
| `STASHCAST_YTDLP_FRAGMENT_RETRIES` | `10` | Fragment retries |
| `STASHCAST_YTDLP_EXTRACTOR_RETRIES` | `3` | Extraction retries |

## Quick Summary

| Method | Pros | Cons |
|--------|------|------|
| **Residential Proxy** | No login required, reliable | Monthly cost ($5-20+) |
| **Tailscale Exit Node** | Free, uses your home IP | Requires home machine running 24/7 |
| **Rate Limiting** | Free, no setup | May not work for heavily flagged IPs |

## Option 1: Residential Proxy (Recommended)

Route yt-dlp requests through a residential IP address using a proxy service.

### Setup

1. Sign up for a residential proxy service:
   - [Bright Data](https://brightdata.com/) - Enterprise grade
   - [Smartproxy](https://smartproxy.com/) - Good balance of price/features
   - [IPRoyal](https://iproyal.com/) - Budget option
   - [Oxylabs](https://oxylabs.io/) - Enterprise grade

2. Get your proxy credentials (host, port, username, password)

3. Configure Stashcast in your `.env` file:

```bash
# HTTP proxy
STASHCAST_YTDLP_PROXY=http://user:pass@proxy.example.com:8080

# SOCKS5 proxy (often better for streaming)
STASHCAST_YTDLP_PROXY=socks5://user:pass@proxy.example.com:1080
```

4. Restart Stashcast

### Testing

Test your proxy with yt-dlp directly:
```bash
yt-dlp --proxy "socks5://user:pass@host:port" "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

## Option 2: Tailscale/WireGuard Exit Node (Free)

Route traffic through your home network using Tailscale.

### Requirements
- A machine at home that can stay on (Raspberry Pi, old laptop, NAS, etc.)
- Tailscale account (free tier works)

### Setup

1. **Install Tailscale on both machines:**

   On your home machine:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   tailscale up --advertise-exit-node
   ```

   On your Oracle VM:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   tailscale up --exit-node=<home-machine-name>
   ```

2. **Approve the exit node** in [Tailscale admin console](https://login.tailscale.com/admin/machines)

3. **Verify routing:**
   ```bash
   curl ifconfig.me  # Should show your home IP
   ```

All traffic from your VM now routes through your home IP. No Stashcast configuration needed.

### Alternative: Route only yt-dlp traffic

If you don't want all traffic through your home:

1. Set up a SOCKS5 proxy on your home machine:
   ```bash
   # Install and run a simple SOCKS5 proxy
   ssh -D 1080 -f -C -q -N user@localhost
   ```

2. Configure Stashcast to use the Tailscale IP:
   ```bash
   STASHCAST_YTDLP_PROXY=socks5://100.x.x.x:1080  # Your home machine's Tailscale IP
   ```

## Option 3: Rate Limiting

Add delays between requests to reduce bot detection triggers.

### Setup

Add to your yt-dlp args in `.env`:

```bash
STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO=--audio-format m4a --sleep-interval 5 --max-sleep-interval 30
STASHCAST_DEFAULT_YTDLP_ARGS_VIDEO=--format "bv*[height<=720]+ba" --sleep-interval 5 --max-sleep-interval 30
```

This adds 5-30 second random delays between requests.

### Effectiveness

- May work for lightly flagged IPs
- Often not sufficient for heavily flagged cloud provider ranges
- Can be combined with other methods

## Option 4: Different Player Client

YouTube has different API endpoints. Some may be less strict.

### Setup

Add extractor args to your yt-dlp configuration:

```bash
# Try Android client
STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO=--audio-format m4a --extractor-args "youtube:player_client=android"

# Or try web client explicitly
STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO=--audio-format m4a --extractor-args "youtube:player_client=web"
```

### Note

Stashcast already cycles through these clients automatically after a 403 (see
[Fixing HTTP Error 403](#fixing-http-error-403-forbidden)), so pinning one by hand is
rarely needed - and it *disables* the automatic fallback. YouTube also changes its API
behaviour frequently, so results vary.

## Combining Methods

You can combine multiple methods for better reliability:

```bash
# Proxy + rate limiting
STASHCAST_YTDLP_PROXY=socks5://user:pass@host:port
STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO=--audio-format m4a --sleep-interval 3 --max-sleep-interval 10
```

## Troubleshooting

### Test yt-dlp directly

```bash
# Test without any auth
yt-dlp "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Test with proxy
yt-dlp --proxy "socks5://user:pass@host:port" "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Check your IP reputation

```bash
# Get your current public IP
curl ifconfig.me

# Check if it's in a datacenter range (these are often blocked)
whois $(curl -s ifconfig.me) | grep -i "orgname\|netname"
```

### Verify proxy is working

```bash
# Without proxy
curl ifconfig.me

# With proxy (should show different IP)
curl --proxy socks5://user:pass@host:port ifconfig.me
```

## Additional Resources

- [yt-dlp extractors documentation](https://github.com/yt-dlp/yt-dlp/wiki/Extractors)
- [Tailscale exit nodes documentation](https://tailscale.com/kb/1103/exit-nodes/)
