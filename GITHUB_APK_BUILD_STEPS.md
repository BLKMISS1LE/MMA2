# Build the Android APK without WSL

This project includes a GitHub Actions workflow that builds the APK for you in the cloud.

## One-time setup

1. Go to https://github.com and sign in.
2. Click **New repository**.
3. Name it something like `meijer-receipt-mobile`.
4. Choose **Private** if you do not want anyone else to see it.
5. Click **Create repository**.

## Upload this project

1. Open the new repository on GitHub.
2. Click **Add file** → **Upload files**.
3. Drag everything inside this folder into GitHub, including:
   - `main.py`
   - `meijer_receipt_formatter.py`
   - `buildozer.spec`
   - `.github/workflows/build-android-apk.yml`
4. Click **Commit changes**.

## Build the APK

1. Open the repository.
2. Click the **Actions** tab.
3. Click **Build Android APK** on the left.
4. Click **Run workflow**.
5. Click the green **Run workflow** button.
6. Wait for the build to finish.

## Download the APK

1. Open the completed workflow run.
2. Scroll to **Artifacts**.
3. Download `meijer-receipt-splitter-debug-apk`.
4. Unzip it.
5. Send the `.apk` file to your Android phone.
6. Tap the APK on your phone and allow **Install unknown apps** if Android asks.

## If the build fails

Open the failed workflow run, click the failed step, and copy the red error text. Paste it into ChatGPT and ask for a fix.
