#!/bin/bash
# Ensure the live nginx (whatever file serves :3000) proxies /agent/ -> exec-agent.
echo "[nginx-fix] uid=$(id -u)"

inject() {
  local f="$1"
  [ -f "$f" ] || return
  grep -q "listen[^;]*3000" "$f" || return
  grep -q "location /agent/" "$f" && return
  python3 - "$f" <<'PY'
import sys
f = sys.argv[1]
s = open(f).read()
block = """  location /agent/ {
    proxy_pass http://127.0.0.1:8090;
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    client_max_body_size 3072M;
  }
"""
i = s.find('error_page')
if i == -1:
    i = s.rfind('}')
open(f, 'w').write(s[:i] + block + s[i:])
PY
  echo "[nginx-fix] injected /agent/ into $f"
}

for f in /etc/nginx/sites-enabled/* /etc/nginx/http.d/*.conf \
         /etc/nginx/conf.d/*.conf /config/nginx/site-confs/*; do
  inject "$f"
done

nginx -t 2>&1 | sed 's/^/[nginx-fix] /'
pgrep -f "[n]ginx:" >/dev/null && nginx -s reload 2>&1 | sed 's/^/[nginx-fix] reload: /'
echo "[nginx-fix] === active config (listen/location/proxy_pass) ==="
nginx -T 2>/dev/null | grep -Ein "listen |location |proxy_pass " | sed 's/^/[nginx-fix] /'
echo "[nginx-fix] done"
