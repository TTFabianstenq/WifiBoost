# WifiBoost 1.0.0

Windows 11 helper for Wi-Fi adapter power settings and the TCP stack.

It is **not** a signal booster. It cannot raise ISP speed, legal TX power, or punch through walls.

## Download the exe (GitHub Actions)

Repo: https://github.com/TTFabianstenq/WifiBoost

1. Open **Actions** → **Build Windows exe**.
2. Open the latest successful run.
3. Download artifact **WifiBoost-windows** (`WifiBoost.exe`).
4. SmartScreen will likely warn — unsigned PyInstaller binary. That is expected.
5. Right-click → Run as administrator.

The workflow builds on `windows-latest`. It does **not** prove the optimizer made your Wi-Fi faster.

## Run from source

```bat
py -3 -m pip install -r requirements.txt
py -3 src\wifiboost.py
```
