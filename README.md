# Meijer Receipt Splitter Mobile

This is an Android-first Kivy mobile version of the Meijer Receipt Formatter.

## What it does

- Imports a Meijer digital receipt PDF from your phone.
- Parses item names, totals, receipt date, discounts, and product codes.
- Saves the original PDF copy with the saved receipt.
- Lets you assign items to people or split an item between everyone.
- Saves receipt history.
- Shows a totals history tab with total money spent per person across saved receipts.

## Files

- `main.py` — mobile app UI.
- `meijer_receipt_formatter.py` — receipt parser/formatter logic.
- `buildozer.spec` — Android APK build config.
- `requirements.txt` — Python requirements.


## Easier APK build: GitHub Actions, no WSL needed

This version includes `.github/workflows/build-android-apk.yml`. Upload the project to a GitHub repo, open the **Actions** tab, run **Build Android APK**, then download the finished APK artifact.

See `GITHUB_APK_BUILD_STEPS.md` for exact click-by-click instructions.

## Build APK on Windows using WSL/Ubuntu

Buildozer works best on Linux. On Windows, use WSL Ubuntu.

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv git zip unzip openjdk-17-jdk autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install buildozer cython
buildozer android debug
```

The APK will be created in the `bin/` folder.

## Install on Android

Enable USB debugging, plug in your phone, then:

```bash
buildozer android deploy run
```

Or copy the generated APK from `bin/` to your phone and install it manually.

## Notes

This package is Android-first. iPhone/iOS builds require Apple Developer signing and a separate iOS toolchain setup.
