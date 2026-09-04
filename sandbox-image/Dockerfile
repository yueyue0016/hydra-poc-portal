FROM hydrasandboxacr.azurecr.io/hydra-desktop:v1

# 1) Pre-bake self-signed cert (so any leftover ssl reference can resolve)
RUN mkdir -p /config/ssl && \
    openssl req -new -x509 -days 3650 -nodes \
      -out /config/ssl/cert.pem -keyout /config/ssl/cert.key \
      -subj "/C=US/ST=CA/O=Hydra/CN=*" && \
    chmod 644 /config/ssl/cert.pem && chmod 640 /config/ssl/cert.key && \
    chown -R abc:abc /config/ssl

# 2) Media / tooling pre-baked (agent can also apt-get install more at runtime)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg imagemagick sox fonts-dejavu-core && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 3) Self-heal script: injects the /agent/ proxy into the live :3000 nginx config
COPY 90-nginx-fix.sh /custom-cont-init.d/90-nginx-fix.sh

# 4) In-sandbox tooling agent + s6 longrun service (runs as root, supervised)
COPY exec-agent.py /opt/exec-agent.py
COPY svc-execagent-run /etc/s6-overlay/s6-rc.d/execagent/run
RUN mkdir -p /etc/s6-overlay/s6-rc.d/execagent \
             /etc/s6-overlay/s6-rc.d/user/contents.d && \
    printf 'longrun' > /etc/s6-overlay/s6-rc.d/execagent/type && \
    sed -i 's/\r$//' /opt/exec-agent.py /etc/s6-overlay/s6-rc.d/execagent/run && \
    chmod +x /etc/s6-overlay/s6-rc.d/execagent/run && \
    touch /etc/s6-overlay/s6-rc.d/user/contents.d/execagent

# 5) Normalize line endings + perms on the self-heal script
RUN sed -i 's/\r$//' /custom-cont-init.d/90-nginx-fix.sh && \
    chmod +x /custom-cont-init.d/90-nginx-fix.sh

EXPOSE 3000
