name: Build Android APK

on:
  workflow_dispatch:
  push:
    branches: [ main, master ]

jobs:
  build:
    runs-on: ubuntu-22.04
    timeout-minutes: 90

    steps:
      - name: Checkout project
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Set up Java
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'

      - name: Install system dependencies
        run: |
          sudo apt update
          sudo apt install -y             git zip unzip python3-pip python3-venv             autoconf libtool pkg-config zlib1g-dev             libncurses5-dev libncursesw5-dev libtinfo6             cmake libffi-dev libssl-dev automake autopoint gettext

      - name: Install Buildozer
        run: |
          python -m pip install --upgrade pip setuptools wheel
          python -m pip install buildozer cython==0.29.36

      - name: Show build config
        run: |
          grep -n "^requirements\|^android\.api\|^android\.minapi\|^android\.ndk\|^android\.arch" buildozer.spec || true

      - name: Build debug APK
        run: |
          buildozer -v android debug

      - name: Upload APK artifact
        uses: actions/upload-artifact@v4
        with:
          name: meijer-receipt-splitter-debug-apk
          path: bin/*.apk
          if-no-files-found: error

      - name: Upload Buildozer logs if build failed
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: buildozer-failure-logs
          path: |
            .buildozer/**/*.log
            .buildozer/android/platform/python-for-android/**/*.log
            .buildozer/android/platform/build-*/build.log
          if-no-files-found: ignore
