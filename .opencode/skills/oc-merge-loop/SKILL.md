---
name: oc-merge-loop
description: Poll OpenCode review deltas and CI checks after PR push — delta fetch for new/edited opencode-agent comments, gh pr checks status, and merge-conflict rebase. Load after gh pr create/push or before gh pr merge.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: post-pr
  author: Ham3dParsa
  author_url: https://github.com/Ham3dParsa
---
# چرخه مرج (OC-only)

این حلقه پی‌آر پوش‌شده را بدون چاپ دوباره متن بدون تغییر به MERGEABLE می‌رساند. فقط نظر `opencode-agent[bot]` را بخوان؛ Kilo خاموش است و نظرهایش نادیده می‌ماند.

اجرا فقط با ساب‌ایجنت جدا برای هر پی‌آر است — نشست اصلی خودش نظرسنجی نمی‌کند، بلکه یک ساب‌ایجنت با همین مهارت برای همان پی‌آر می‌فرستد و گزارش پایانی‌اش (MERGED یا BLOCKED با دلیل) را تحویل می‌دهد.

## زمان بارگذاری
- بعد از `gh pr create` یا `git push` روی پی‌آر
- پیش از `gh pr merge --squash`
- وقتی `mergeable` برابر `CONFLICTING` است

## ۱. دلتای نظرها را بخوان
شناسه و طول متن را سبک بگیر و فیلتر بات را در PowerShell انجام بده (jq پیچیده با select و براکت در PowerShell 5.1 می‌شکند، پس همان tsv ساده):
```powershell
gh api repos/Ham3dParsa/HamZaboonRobot/pulls/<n>/comments --jq '.[] | [.id, (.body|length), .user.login] | @tsv'
gh api repos/Ham3dParsa/HamZaboonRobot/issues/<n>/comments --jq '.[] | [.id, (.body|length), .user.login] | @tsv'
```
در PowerShell فقط ردیف‌های `opencode-agent[bot]` را نگه دار. نگاشت `id->h` را در فایل جداگانه هر پی‌آر نگه دار: `$env:TEMP/opencode/reviewer_seen_<n>.json`. فقط شناسه تازه یا `h` تغییرکرده دلتا است؛ متن کامل را فقط برای دلتا بگیر:
```powershell
gh api repos/Ham3dParsa/HamZaboonRobot/pulls/comments/<id> --jq '.body'
gh api repos/Ham3dParsa/HamZaboonRobot/issues/comments/<id> --jq '.body'
```
اگر فراخوانی `gh api` با کد غیرصفر برگشت، `seen` را به‌روز نکن و در نظرسنجی بعد دوباره تلاش کن. بین نظرسنجی‌ها ۹۰ ثانیه بخواب (بازه مجاز ۹۰ تا ۱۲۰، سقف ۳۰ دقیقه). هر کامیت اصلاحی را پوش کن چون OC فقط بعد از پوش دوباره بررسی می‌کند.
اتمام: هر دلتا یک‌بار خوانده شد، بدون دلتا چیزی چاپ نشد، و خرابی api مبنا را خراب نکرد.

## ۲. چک‌های CI را سبز کن
```powershell
gh pr checks <n>
```
این نام‌ها باید `pass` باشند: `label`، `test (3.10)`، `test (3.13)`، `ram-gate`، `review`. تطبیق را لنگردار انجام بده: `(?m)^\s*<name>(?!\w)\s+pass`. روی `fail` خروجی `gh run view <run> --log-failed` را بگیر و پیش از نظرسنجی بعد اصلاح کن.
اتمام: هر پنج چک `pass` است و هیچ `fail` در خروجی نیست.

## ۳. هر یافته را تعیین تکلیف کن
`[critical]` و `[warning]` با `REQUEST_CHANGES` یعنی must-fix پیش از مرج. `[info]` را اگر در اسکوپ و ساده (≤۵ خط) است همین حالا درست کن؛ وگرنه با دلیل و لینک به تیکت بعدی موکول کن. تعیین‌تکلیف هر `[info]` (اصلاح‌شده، تیکت‌شده با شماره، یا نویز با دلیل یک‌خطی) در گزارش پایانی ثبت می‌شود.
اتمام: صفر must-fix باز مانده و هر `[info]` یا اصلاح شده یا با دلیل و لینک موکول شده است.

## ۴. فقط با سه‌شرط APPROVED مرج کن
هر سه روی یک head برقرار باشد: آخرین نظر OC واژه APPROVED را بگوید، صفر must-fix باز باشد، و چک‌های سبز روی همان head باشند. بعد با `MERGEABLE` و بدون چک failing بزن: `gh pr merge --squash <n>`.
اتمام: هر سه شرط روی یک head ثبت شد و مرج فقط همان‌وقت انجام شد.

## ۵. تعارض را با ریبیس باز کن
```powershell
git fetch origin; git rebase origin/main
```
سیم‌های هر دو شاخه را نگه دار. بعد `python scripts/compile_all.py` و `git diff --check` را سبز کن و با `git push --force-with-lease` پوش کن.
اتمام: ریبیس کامل شد، هر دو اعتبارسنجی سبز است، و پوش موفق ثبت شد.

## خودکارسازی
همین مهارت را این اسکریپت اجرا می‌کند:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/oc_merge_loop.ps1 -PR <n> [-SleepSeconds 90] [-TimeoutMinutes 30]
```
برای هر پی‌آر یک ساب‌ایجنت جدا با فایل state جدا بگذار. اگر اسکریپت را اجرا نکردی، گام‌های دستی بالا معتبر است.
اتمام: هر دلتای OC یک‌بار خوانده و تعیین تکلیف شد، چک‌های لازم سبز است، و `mergeable` برابر `MERGEABLE` است.
