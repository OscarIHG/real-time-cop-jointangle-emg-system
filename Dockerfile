FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QT_X11_NO_MITSHM=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
       libbluetooth3 \
       libgl1 \
       libglib2.0-0 \
       libsm6 \
       libusb-1.0-0 \
       libxext6 \
       libxrender1 \
       libxcb-xinerama0 \
       libxkbcommon-x11-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
       "PyQt5==5.15.*" "pyqtgraph==0.14.*" -r requirements.txt

COPY acquisition_systems ./acquisition_systems
COPY scripts ./scripts
COPY config.yaml README.md ./
RUN mkdir -p sessions

CMD ["python", "-m", "acquisition_systems.app_gui"]
