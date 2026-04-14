FROM python:3.12-slim

# System deps for PyQt6 (X11 forwarding from host) + Xvfb for headless test profile
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libgl1 \
    libegl1 \
    libglib2.0-0 \
    libxkbcommon0 \
    libxkbcommon-x11-0 \
    libdbus-1-3 \
    libfontconfig1 \
    libx11-xcb1 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-keysyms1 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxcb-randr0 \
    libxcb-image0 \
    x11-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV QT_QPA_PLATFORM=xcb

# Entrypoint: use host display if available (X11 forwarding), otherwise fall back to Xvfb
CMD ["sh", "-c", "\
  if [ -n \"$DISPLAY\" ] && xdpyinfo -display \"$DISPLAY\" >/dev/null 2>&1; then \
    echo 'Using host display' && python main.py; \
  else \
    echo 'No host display — starting Xvfb' && \
    rm -f /tmp/.X99-lock && \
    Xvfb :99 -screen 0 1280x720x24 -nolisten tcp & \
    sleep 1 && \
    DISPLAY=:99 python main.py; \
  fi"]
