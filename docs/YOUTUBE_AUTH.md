# YouTube Authentication for Cloud VMs

When running Stashcast on cloud VMs (Oracle Cloud, AWS, GCP, Azure, etc.), you may encounter this error:

```
ERROR: [youtube] Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies for the authentication.
```

This happens because YouTube flags datacenter IP ranges as potential bots. This guide covers several workarounds.

## Quick Summary

| Method | Pros | Cons |
|--------|------|------|
| **Residential Proxy** | No login required, reliable | Monthly cost ($5-20+) |
| **Tailscale Exit Node** | Free, uses your home IP | Requires home machine running 24/7 |
| **Cookies File** | Free, simple setup | Requires YouTube login, cookies expire |
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

## Option 3: Cookies File

Export cookies from a browser where you're logged into YouTube.

### Setup

1. **Install a cookies export extension:**
   - Chrome: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - Firefox: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)

2. **Export cookies:**
   - Go to [youtube.com](https://youtube.com) and ensure you're logged in
   - Click the extension icon
   - Export/download the cookies.txt file

3. **Upload to your VM:**
   ```bash
   scp cookies.txt user@your-vm:/path/to/cookies.txt
   ```

4. **Configure Stashcast:**
   ```bash
   STASHCAST_YTDLP_COOKIES_FILE=/path/to/cookies.txt
   ```

5. Restart Stashcast

### Important Notes

- Cookies expire periodically (weeks to months)
- You'll need to re-export when they expire
- The cookies are tied to your Google account
- Consider using a dedicated/throwaway Google account

## Option 4: Rate Limiting

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

## Option 5: Different Player Client

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

This option has mixed results and YouTube frequently changes their API behavior.

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

# Test with cookies
yt-dlp --cookies /path/to/cookies.txt "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
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

- [yt-dlp FAQ on cookies](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)
- [yt-dlp extractors documentation](https://github.com/yt-dlp/yt-dlp/wiki/Extractors)
- [Tailscale exit nodes documentation](https://tailscale.com/kb/1103/exit-nodes/)
