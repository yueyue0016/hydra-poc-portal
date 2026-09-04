FROM lscr.io/linuxserver/webtop:ubuntu-xfce

ENV TITLE="Hydra Desktop"

# CLI tools + FileZilla (GUI file transfer) + deps for Chrome
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      wget curl ca-certificates gnupg \
      filezilla \
      git vim nano htop tmux \
      zip unzip tar rsync openssh-client \
      jq python3 python3-pip \
      fonts-noto-cjk && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Google Chrome (stable, official .deb)
RUN wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get update && \
    apt-get install -y --no-install-recommends /tmp/chrome.deb && \
    rm /tmp/chrome.deb && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Container-safe Chrome flags (no user namespaces / small /dev/shm in ACA)
RUN sed -i 's|Exec=/usr/bin/google-chrome-stable|Exec=/usr/bin/google-chrome-stable --no-sandbox --disable-dev-shm-usage --disable-gpu|g' \
      /usr/share/applications/google-chrome.desktop && \
    printf '#!/bin/bash\nexec /usr/bin/google-chrome-stable --no-sandbox --disable-dev-shm-usage --disable-gpu "$@"\n' \
      > /usr/local/bin/chrome && \
    chmod +x /usr/local/bin/chrome

EXPOSE 3000
