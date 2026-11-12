# Jarvis relay (Apricot Digital)

Tiny server that lets a client's phone reach the Jarvis running on their home laptop. It stores only hashed tokens and
forwards **end-to-end encrypted** frames: it cannot read questions, answers or documents (the key lives in the pairing QR's
`#` part, which browsers never send to a server).

## Run
    pip install aiohttp
    python server.py --host 127.0.0.1 --port 8080 --db /data/relay.db

Put it behind HTTPS (required for the phone app's microphone, install-to-home-screen and WebCrypto). Caddy example:

    jarvis.apricotdigital.example {
        reverse_proxy 127.0.0.1:8080
    }

Then set `"phone": {"relay_url": "https://jarvis.apricotdigital.example"}` in `config.json` before building the zip.
Health check: `GET /health`.
