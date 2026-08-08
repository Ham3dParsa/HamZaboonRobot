# گزارش مقایسه مدل‌های AI — 2026-07-22

تولید شده در: 2026-07-22 16:34:49
مدت اجرا: 40.6 ثانیه

## خلاصه

این گزارش خروجی ۴ مدل مختلف AI روی ۱۲ واژه/عبارت انگلیسی را مقایسه می‌کند.
هر کارت با استفاده از `custom_word_system_prompt` برای زبان انگلیسی در سطح intermediate تولید شده است.

### جدول مقایسه

| واژه | 3.6-flash معنی | 3.5-flash معنی | flash-lite معنی | gemma-4 معنی | 3.6-flash توکن | 3.5-flash توکن | flash-lite توکن | gemma-4 توکن | 3.6-flash ms | 3.5-flash ms | flash-lite ms | gemma-4 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **run** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 754 | 637 | 625 | 1601 |
| **break a leg** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 647 | 620 | 608 | 680 |
| **actually** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 1513 | 1468 | 624 | 1552 |
| **get up** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 661 | 630 | 627 | 680 |
| **however** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 615 | 603 | 624 | 683 |
| **cozy** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 642 | 629 | 660 | 677 |
| **procrastinate** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 639 | 643 | 624 | 668 |
| **book** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 631 | 1550 | 639 | 667 |
| **ironic** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 625 | 647 | 662 | 1651 |
| **RSVP** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 623 | 628 | 635 | 690 |
| **couch potato** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 1583 | 611 | 2868 | 691 |
| **appreciate** | ❌ | ❌ | ❌ | ❌ | 0 | 0 | 0 | 0 | 1517 | 632 | 667 | 692 |

## جمع‌بندی عددی به تفکیک مدل

| مدل | موفق | مجموع توکن ورودی | مجموع توکن خروجی | مجموع کل توکن | میانگین latency (ms) | مجموع هزینه (USD) |
|-----|------|----------------|-----------------|-------------|---------------------|-----------------|
| gemini-3.6-flash | 0/12 | 0 | 0 | 0 | 0 | $0.000000 |
| gemini-3.5-flash | 0/12 | 0 | 0 | 0 | 0 | $0.000000 |
| gemini-flash-lite-latest | 0/12 | 0 | 0 | 0 | 0 | $0.000000 |
| gemma-4-31b-it | 0/12 | 0 | 0 | 0 | 0 | $0.000000 |

## جزئیات تمام تماس‌ها از llm_requests

| ردیف | مدل | واژه | توکن ورودی | توکن خروجی | مجموع | latency (ms) | هزینه (USD) |
|------|-----|------|-----------|------------|-------|-------------|-------------|
| 1 | 3.6-flash | run | 0 | 0 | 0 | 0 | $0.000000 |
| 2 | 3.6-flash | break a leg | 0 | 0 | 0 | 0 | $0.000000 |
| 3 | 3.6-flash | actually | 0 | 0 | 0 | 0 | $0.000000 |
| 4 | 3.6-flash | get up | 0 | 0 | 0 | 0 | $0.000000 |
| 5 | 3.6-flash | however | 0 | 0 | 0 | 0 | $0.000000 |
| 6 | 3.6-flash | cozy | 0 | 0 | 0 | 0 | $0.000000 |
| 7 | 3.6-flash | procrastinate | 0 | 0 | 0 | 0 | $0.000000 |
| 8 | 3.6-flash | book | 0 | 0 | 0 | 0 | $0.000000 |
| 9 | 3.6-flash | ironic | 0 | 0 | 0 | 0 | $0.000000 |
| 10 | 3.6-flash | RSVP | 0 | 0 | 0 | 0 | $0.000000 |
| 11 | 3.6-flash | couch potato | 0 | 0 | 0 | 0 | $0.000000 |
| 12 | 3.6-flash | appreciate | 0 | 0 | 0 | 0 | $0.000000 |
| 13 | 3.5-flash | run | 0 | 0 | 0 | 0 | $0.000000 |
| 14 | 3.5-flash | break a leg | 0 | 0 | 0 | 0 | $0.000000 |
| 15 | 3.5-flash | actually | 0 | 0 | 0 | 0 | $0.000000 |
| 16 | 3.5-flash | get up | 0 | 0 | 0 | 0 | $0.000000 |
| 17 | 3.5-flash | however | 0 | 0 | 0 | 0 | $0.000000 |
| 18 | 3.5-flash | cozy | 0 | 0 | 0 | 0 | $0.000000 |
| 19 | 3.5-flash | procrastinate | 0 | 0 | 0 | 0 | $0.000000 |
| 20 | 3.5-flash | book | 0 | 0 | 0 | 0 | $0.000000 |
| 21 | 3.5-flash | ironic | 0 | 0 | 0 | 0 | $0.000000 |
| 22 | 3.5-flash | RSVP | 0 | 0 | 0 | 0 | $0.000000 |
| 23 | 3.5-flash | couch potato | 0 | 0 | 0 | 0 | $0.000000 |
| 24 | 3.5-flash | appreciate | 0 | 0 | 0 | 0 | $0.000000 |
| 25 | flash-lite | run | 0 | 0 | 0 | 0 | $0.000000 |
| 26 | flash-lite | break a leg | 0 | 0 | 0 | 0 | $0.000000 |
| 27 | flash-lite | actually | 0 | 0 | 0 | 0 | $0.000000 |
| 28 | flash-lite | get up | 0 | 0 | 0 | 0 | $0.000000 |
| 29 | flash-lite | however | 0 | 0 | 0 | 0 | $0.000000 |
| 30 | flash-lite | cozy | 0 | 0 | 0 | 0 | $0.000000 |
| 31 | flash-lite | procrastinate | 0 | 0 | 0 | 0 | $0.000000 |
| 32 | flash-lite | book | 0 | 0 | 0 | 0 | $0.000000 |
| 33 | flash-lite | ironic | 0 | 0 | 0 | 0 | $0.000000 |
| 34 | flash-lite | RSVP | 0 | 0 | 0 | 0 | $0.000000 |
| 35 | flash-lite | couch potato | 0 | 0 | 0 | 0 | $0.000000 |
| 36 | flash-lite | appreciate | 0 | 0 | 0 | 0 | $0.000000 |
| 37 | gemma-4 | run | 0 | 0 | 0 | 0 | $0.000000 |
| 38 | gemma-4 | break a leg | 0 | 0 | 0 | 0 | $0.000000 |
| 39 | gemma-4 | actually | 0 | 0 | 0 | 0 | $0.000000 |
| 40 | gemma-4 | get up | 0 | 0 | 0 | 0 | $0.000000 |
| 41 | gemma-4 | however | 0 | 0 | 0 | 0 | $0.000000 |
| 42 | gemma-4 | cozy | 0 | 0 | 0 | 0 | $0.000000 |
| 43 | gemma-4 | procrastinate | 0 | 0 | 0 | 0 | $0.000000 |
| 44 | gemma-4 | book | 0 | 0 | 0 | 0 | $0.000000 |
| 45 | gemma-4 | ironic | 0 | 0 | 0 | 0 | $0.000000 |
| 46 | gemma-4 | RSVP | 0 | 0 | 0 | 0 | $0.000000 |
| 47 | gemma-4 | couch potato | 0 | 0 | 0 | 0 | $0.000000 |
| 48 | gemma-4 | appreciate | 0 | 0 | 0 | 0 | $0.000000 |

---

## پیوست: خروجی خام تمام کارت‌ها

### gemini-3.6-flash (فعلی فعال)

#### run

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 754 ms

#### break a leg

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 647 ms

#### actually

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 1513 ms

#### get up

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 661 ms

#### however

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 615 ms

#### cozy

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 642 ms

#### procrastinate

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 639 ms

#### book

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 631 ms

#### ironic

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 625 ms

#### RSVP

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 623 ms

#### couch potato

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 1583 ms

#### appreciate

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 1517 ms

### gemini-3.5-flash (نسل قبل)

#### run

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 637 ms

#### break a leg

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 620 ms

#### actually

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 1468 ms

#### get up

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 630 ms

#### however

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 603 ms

#### cozy

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 629 ms

#### procrastinate

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 643 ms

#### book

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 1550 ms

#### ironic

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 647 ms

#### RSVP

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 628 ms

#### couch potato

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 611 ms

#### appreciate

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 632 ms

### gemini-flash-lite-latest (قدیمی .env)

#### run

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 625 ms

#### break a leg

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 608 ms

#### actually

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 624 ms

#### get up

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 627 ms

#### however

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 624 ms

#### cozy

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 660 ms

#### procrastinate

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 624 ms

#### book

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 639 ms

#### ironic

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 662 ms

#### RSVP

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 635 ms

#### couch potato

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 2868 ms

#### appreciate

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 667 ms

### gemma-4-31b-it (مدل قوی‌تر)

#### run

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 1601 ms

#### break a leg

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 680 ms

#### actually

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 1552 ms

#### get up

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 680 ms

#### however

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 683 ms

#### cozy

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 677 ms

#### procrastinate

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 668 ms

#### book

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 667 ms

#### ironic

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 1651 ms

#### RSVP

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 690 ms

#### couch potato

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 691 ms

#### appreciate

> **خطا:** PermissionDeniedError: <!DOCTYPE html>
<html lang=en>
  <meta charset=utf-8>
  <meta name=viewport content="initial-scale=1, minimum-scale=1, width=device-width">
  <title>Error 403 (Forbidden)!!1</title>
  <style>
    *{ma

> latency: 692 ms
