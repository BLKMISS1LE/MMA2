[app]
title = Meijer Receipt Splitter
package.name = meijerreceiptsplitter
package.domain = com.danh032497
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,json,txt,pdf
version = 0.1
requirements = python3,kivy,plyer,requests,pypdf,pyjnius
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 35
android.minapi = 23
android.ndk = 25b
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
