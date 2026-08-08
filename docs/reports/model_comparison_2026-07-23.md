# گزارش مقایسه مدل‌های AI — ۲۰۲۶-۰۷-۲۳

**تولید شده:** 2026-07-23 22:47:08

## ۱. خلاصه

دو مدل Google Generative AI روی ۱۲ واژه/عبارت انگلیسی (سطح intermediate) مقایسه شده‌اند.
تماس‌ها مستقیم به API گوگل از طریق SOCKS5 پروکسی (v2rayn).
قالب کارت: full JSON (`compact=False`).

- **مدل ۱ — gemini-3.6-flash**: 11/12 موفق (۱ خطای rate limit: RSVP)
- **مدل ۲ — gemini-flash-lite-latest**: 12/12 موفق (تمام ۱۲ کارت)

## ۲. جدول مقایسه خروجی

| واژه | **3.6-flash** معنی فارسی | **flash-lite** معنی فارسی |
|------|--------------------------|---------------------------|
| **run** | دویدن، اداره کردن | دویدن، اداره کردن |
| **break a leg** | موفق باشی! | موفق باشی / ان‌شاءالله موفق شوی |
| **actually** | در واقع، حقیقتش | در واقع، راستش را بخواهید |
| **get up** | از خواب بیدار شدن، بلند شدن | بیدار شدن، از خواب بلند شدن |
| **however** | با این حال، اما | با این حال، اما |
| **cozy** | دنج، گرم و راحت | دنج و راحت |
| **procrastinate** | به تعویق انداختن، پشت گوش انداختن | امروزه فردا کردن، به تعویق انداختن |
| **book** | رزرو کردن / کتاب | کتاب / رزرو کردن |
| **ironic** | تناقض‌آمیز، کنایه‌آمیز | کنایه‌آمیز، متناقض‌نما |
| **RSVP** | ❌ | لطفاً پاسخ دهید |
| **couch potato** | آدم تنبل و بی‌تحرک | شخص تنبل و کم‌تحرک |
| **appreciate** | قدردانی کردن، درک کردن | قدردانی کردن، قدر دانستن |

## ۳. جمع‌بندی عددی (از llm_requests)

| مدل | موفق/کل واژه | مجموع pt | مجموع ct | مجموع tt | میانگین ms (موفق) | مجموع هزینه (USD) | مجموع هزینه (IRR) |
|-----|-------------|---------|---------|---------|-----------------|-----------------|-----------------|
| gemini-flash-lite-latest | 12/12 | 5278 | 3111 | 8389 | 2495 | $0.005987 | 11,974 ریال |
| gemini-3.6-flash | 11/12 | 4838 | 3108 | 18747 | 10397 | $0.030567 | 61,134 ریال |

**توضیح:** مدل 3.6-flash برای واژه RSVP سه بار با خطای 429 rate limit مواجه شد (۳ تماس اضافی در مجموع ۱۴ تماس، که ۳ تای آن‌ها هزینه صفر دارند).

**نرخ‌های هزینه:**
- gemini-3.6-flash: input=$1.50/M توکن، output=$7.50/M توکن
- gemini-flash-lite-latest: input=$0.25/M توکن، output=$1.50/M توکن
- ۱ USD ≈ ۲,۰۰۰,۰۰۰ ریال

## ۴. تحلیل کیفی و نتیجه‌گیری

### تفاوت‌های کیفی بین دو مدل

| جنبه | gemini-3.6-flash | gemini-flash-lite-latest |
|------|-----------------|------------------------|
| **عمق توضیحات** | توضیحات کامل‌تر و دقیق‌تر (مثلاً «procrastinate»: اشاره به فرق wake up و get up) | توضیحات کوتاه‌تر اما همچنان مفید |
| **مثال‌ها** | ۲ مثال با ترجمه، گاهی مثال‌های خلاقانه‌تر | ۲ مثال با ترجمه، استاندارد |
| **grammar_tip** | دقیق‌تر (مثلاً فرق wake up و get up برای get up) | کاربردی اما ساده‌تر |
| **دقت تلفظ (IPA)** | هردو مدل دقیق | هردو مدل دقیق |
| **معادل فارسی** | natural, گاهی با دو سبک (ادبی/محاوره) | طبیعی اما گاهی ماشینی‌تر |

### خلاصه

- **هر دو مدل از نظر کیفی قابل‌قبول و نزدیک به هم** هستند — فارسی طبیعی، مثال‌های مناسب، IPA درست.
- **gemini-3.6-flash** کیفیت بالاتری در grammar_tip و توضیحات دارد ولی **۵ برابر گران‌تر** (۶۱٬۱۳۴ ریال در مقابل ۱۱٬۹۷۴ ریال برای ۱۲ واژه).
- **gemini-flash-lite-latest** از نظر **قیمت، سرعت (۲٫۵ ثانیه در مقابل ۱۰ ثانیه) و پایداری** برتر است. بهترین گزینه برای تولید انبوه کارت‌های روزانه.

### توصیه

برای تولید کارت‌های روزمره (daily cards): **gemini-flash-lite-latest** گزینه مناسب‌تر است.
برای محتوای ویژه یا کاربران premium در صورت نیاز به کیفیت بالاتر: **gemini-3.6-flash** را در نظر بگیرید (با مکانیزم fallback به flash-lite در صورت خطا).

---

## ۵. پیوست: خروجی خام تمام کارت‌ها

### gemini-3.6-flash

#### run

```json
{
  "word": "run",
  "phonetic": {
    "ipa": "/rʌn/",
    "persian": "رَن"
  },
  "fa_meaning": "دویدن، اداره کردن",
  "fa_explanation": "این واژه پرکاربرد افزون بر معنای دویدن با پا، به معنای اداره کردن یک کسب‌وکار یا جریان داشتن مایعات نیز به کار می‌رود.",
  "synonyms": [
    "jog",
    "manage",
    "operate"
  ],
  "antonyms": [
    "walk",
    "stop"
  ],
  "examples": [
    "She runs five miles every morning to stay in shape.",
    "He has been running his own business for three years."
  ],
  "example_translations": [
    "او هر روز صبح برای روی فرم ماندن پنج مایل می‌دود.",
    "او سه سال است که کسب‌وکار خودش را اداره می‌کند."
  ],
  "grammar_tip": "فعل run بی‌قاعده است (گذشته: ran، اسم مفعول: run). هنگام استفاده از این فعل به معنای «اداره کردن»، نیازی به حرف اضافه نیست (مانند: run a company)."
}
```

#### break a leg

```json
{
  "word": "break a leg",
  "phonetic": {
    "ipa": "/breɪk ə leɡ/",
    "persian": "برِیک اَ لِگ"
  },
  "fa_meaning": "موفق باشی!",
  "fa_explanation": "اصطلاحی رایج برای آرزوی موفقیت کردن، به‌ویژه قبل از اجرا، امتحان یا سخنرانی.",
  "synonyms": [
    "good luck",
    "best of luck"
  ],
  "antonyms": [
    "bad luck"
  ],
  "examples": [
    "You have a big presentation today, break a leg!",
    "I know you are nervous about the play, but go out there and break a leg."
  ],
  "example_translations": [
    "امروز یک ارائه‌ی مهم داری، موفق باشی!",
    "می‌دانم برای تئاتر استرس داری، اما برو روی صحنه و بترکون (موفق باش)."
  ],
  "grammar_tip": "این عبارت یک اصطلاح (Idiom) است و نباید به صورت تحت‌اللفظی (شکستن پا) ترجمه شود. معمولاً به عنوان یک جمله امری کوتاه برای تشویق استفاده می‌شود."
}
```

#### actually

```json
{
  "word": "actually",
  "phonetic": {
    "ipa": "/ˈæk.tʃu.ə.li/",
    "persian": "اَکچوئَلی"
  },
  "fa_meaning": "در واقع، حقیقتش",
  "fa_explanation": "این قید برای تأکید بر حقیقت یک موضوع، تصحیح یک اشتباه یا بیان یک خبر غیرمنتظره استفاده می‌شود.",
  "synonyms": [
    "in fact",
    "as a matter of fact",
    "truly"
  ],
  "antonyms": [
    "hypothetically",
    "theoretically"
  ],
  "examples": [
    "I thought he was joking, but he actually meant it.",
    "Actually, I have a meeting at three, so I need to leave soon."
  ],
  "example_translations": [
    "فکر می‌کردم شوخی می‌کند، اما در واقع منظورش جدی بود.",
    "حقیقتش این است که من ساعت سه جلسه دارم، بنابراین باید به زودی بروم."
  ],
  "grammar_tip": "کلمه actually معمولاً قبل از فعل اصلی (یا بعد از فعل be) می‌آید، اما اگر برای تصحیح محترمانه حرف دیگران استفاده شود، در ابتدای جمله قرار می‌گیرد."
}
```

#### get up

```json
{
  "word": "get up",
  "phonetic": {
    "ipa": "/ɡɛt ʌp/",
    "persian": "گِت آپ"
  },
  "fa_meaning": "از خواب بیدار شدن، بلند شدن",
  "fa_explanation": "این فعل عبارتی به معنی برخاستن از رختخواب پس از بیدار شدن یا ایستادن بر روی پا است.",
  "synonyms": [
    "arise",
    "stand up",
    "wake up"
  ],
  "antonyms": [
    "go to bed",
    "sit down",
    "lie down"
  ],
  "examples": [
    "I usually get up at 7 o'clock every morning.",
    "He got up from his chair to greet the guests."
  ],
  "example_translations": [
    "من معمولاً هر روز صبح ساعت ۷ از خواب بیدار می‌شوم.",
    "او از صندلی‌اش بلند شد تا به مهمانان خوش‌آمد بگوید."
  ],
  "grammar_tip": "تفاوت wake up و get up در این است که wake up یعنی هوشیار شدن و باز کردن چشم‌ها، اما get up یعنی عمل فیزیکیِ خارج شدن از رختخواب."
}
```

#### however

```json
{
  "word": "however",
  "phonetic": {
    "ipa": "/haʊˈev.ər/",
    "persian": "هاو اِوِر"
  },
  "fa_meaning": "با این حال، اما",
  "fa_explanation": "این واژه برای بیان تضاد بین دو جمله یا فکری متضاد به کار می‌رود و نسبت به کلمه but رسمی‌تر است.",
  "synonyms": [
    "nevertheless",
    "nonetheless",
    "yet"
  ],
  "antonyms": [],
  "examples": [
    "The weather was very cold; however, we decided to go for a walk.",
    "She studied hard for the exam. However, she did not get a high grade."
  ],
  "example_translations": [
    "هوا بسیار سرد بود؛ با این حال، ما تصمیم گرفتیم به پیاده‌روی برویم.",
    "او برای امتحان خیلی درس خواند. با این حال، نمره بالایی نگرفت."
  ],
  "grammar_tip": "اگر اما (however) در شروع جمله بیاید، بعد از آن کاما (,) قرار می‌گیرد. همچنین می‌توانید قبل از آن از نقطه‌ویرگول (;) و بعد از آن از کاما استفاده کنید تا دو جمله مستقل را به هم وصل کنید."
}
```

#### cozy

```json
{
  "word": "cozy",
  "phonetic": {
    "ipa": "/ˈkəʊzi/",
    "persian": "کوزی"
  },
  "fa_meaning": "دنج، گرم و راحت",
  "fa_explanation": "این صفت برای توصیف مکانی کوچک، گرم و آرام‌بخش به کار می‌رود که به انسان احساس راحتی و امنیت می‌دهد.",
  "synonyms": [
    "comfortable",
    "snug",
    "warm"
  ],
  "antonyms": [
    "uncomfortable",
    "cold"
  ],
  "examples": [
    "We spent a cozy evening by the fireplace listening to music.",
    "She lives in a small but cozy apartment in the city center."
  ],
  "example_translations": [
    "ما یک عصر دنج را کنار شومینه با گوش دادن به موسیقی گذراندیم.",
    "او در یک آپارتمان کوچک اما دنج در مرکز شهر زندگی می‌کند."
  ],
  "grammar_tip": "توجه داشته باشید که املای cozy در انگلیسی آمریکایی و cosy در انگلیسی بریتانیایی رایج است."
}
```

#### procrastinate

```json
{
  "word": "procrastinate",
  "phonetic": {
    "ipa": "/prəʊˈkræstɪneɪt/",
    "persian": "پروکْرَسْتینِیت"
  },
  "fa_meaning": "به تعویق انداختن، پشت گوش انداختن",
  "fa_explanation": "به معنای به تأخیر انداختن کارهایی است که باید انجام شوند، به‌ویژه از روی تنبلی یا بی‌حوصلگی.",
  "synonyms": [
    "postpone",
    "delay",
    "put off"
  ],
  "antonyms": [
    "expedite",
    "advance"
  ],
  "examples": [
    "If you procrastinate, you will miss the deadline for the project.",
    "She tends to procrastinate when faced with difficult tasks."
  ],
  "example_translations": [
    "اگر کارها را به تعویق بیندازی، مهلت انجام پروژه را از دست خواهی داد.",
    "او معمولاً وقتی با کارهای سخت روبرو می‌شود، آن‌ها را پشت گوش می‌اندازد."
  ],
  "grammar_tip": "اگر بعد از این فعل، فعل دیگری بکار رود، باید به صورت ing-دار (Gerund) باشد؛ مانند: procrastinate doing homework."
}
```

#### book

```json
{
  "word": "book",
  "phonetic": {
    "ipa": "/bʊk/",
    "persian": "بوُک"
  },
  "fa_meaning": "رزرو کردن / کتاب",
  "fa_explanation": "این واژه علاوه بر نقش اسمی (کتاب)، در سطح متوسط بیشتر به عنوان فعل به معنای رزرو کردن هتل، بلیت یا صندلی استفاده می‌شود.",
  "synonyms": [
    "reserve",
    "schedule"
  ],
  "antonyms": [
    "cancel"
  ],
  "examples": [
    "I need to book a hotel room for my trip next week.",
    "Did you book the flight tickets online?"
  ],
  "example_translations": [
    "من باید برای سفر هفته آینده‌ام یک اتاق در هتل رزرو کنم.",
    "آیا بلیت‌های پرواز را آنلاین رزرو کردی؟"
  ],
  "grammar_tip": "فعل book باقاعده است (گذشته: booked) و مستقیماً بعد از آن مفعول می‌آید، مانند: book a table."
}
```

#### ironic

```json
{
  "word": "ironic",
  "phonetic": {
    "ipa": "/aɪˈrɑːnɪk/",
    "persian": "آیرانیک"
  },
  "fa_meaning": "تناقض‌آمیز، کنایه‌آمیز",
  "fa_explanation": "به وضعیتی گفته می‌شود که نتیجه‌ی آن کاملاً برخلاف انتظار است، یا به لحنی که شامل طعنه و کنایه باشد اشاره دارد.",
  "synonyms": [
    "sarcastic",
    "paradoxical",
    "mocking"
  ],
  "antonyms": [
    "sincere",
    "expected"
  ],
  "examples": [
    "It is ironic that the fire station burned down yesterday.",
    "She noticed the ironic smile on his face during the meeting."
  ],
  "example_translations": [
    "این تناقض‌آمیز است که ایستگاه آتش‌نشانی دیروز آتش گرفت.",
    "او متوجه لبخند کنایه‌آمیز روی صورت او در طول جلسه شد."
  ],
  "grammar_tip": "صفت ironic اغلب برای توصیف موقعیت‌ها یا لحن بیان استفاده می‌شود. شکل قیدی آن ironically به معنای «از قضا» یا «به‌طور تناقض‌آمیزی» است."
}
```

#### RSVP

> **خطا:** Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/g

#### couch potato

```json
{
  "word": "couch potato",
  "phonetic": {
    "ipa": "/kaʊtʃ pəˈteɪtoʊ/",
    "persian": "کاوچ پُتِیتو"
  },
  "fa_meaning": "آدم تنبل و بی‌تحرک",
  "fa_explanation": "این اصطلاح به فردی اشاره دارد که بیشتر وقت خود را به نشستن، تماشای تلویزیون و کم‌تحرکی می‌گذراند.",
  "synonyms": [
    "slacker",
    "idler",
    "lazybones"
  ],
  "antonyms": [
    "active person",
    "go-getter"
  ],
  "examples": [
    "Since he lost his job, he has turned into a real couch potato.",
    "I don't want to be a couch potato this weekend, so let's go for a hike."
  ],
  "example_translations": [
    "از زمانی که کارش را از دست داده، به یک آدم واقعاً تنبل و خانه‌نشین تبدیل شده است.",
    "من نمی‌خواهم این آخر هفته یک آدم تنبل و بی‌تحرک باشم، پس بیا برویم پیاده‌روی."
  ],
  "grammar_tip": "این عبارت یک اصطلاح (idiom) و اسم قابل شمارش است، بنابراین می‌توانید قبل از آن از حرف تعریف (a couch potato) یا حالت جمع (couch potatoes) استفاده کنید."
}
```

#### appreciate

```json
{
  "word": "appreciate",
  "phonetic": {
    "ipa": "/əˈpriː.ʃi.eɪt/",
    "persian": "اَپری‌شی‌ئِیت"
  },
  "fa_meaning": "قدردانی کردن، درک کردن",
  "fa_explanation": "تشکر و قدردانی از لطف یا کمک دیگران، یا فهمیدن ارزش و اهمیت واقعی یک موضوع.",
  "synonyms": [
    "value",
    "acknowledge",
    "be grateful for"
  ],
  "antonyms": [
    "disregard",
    "undervalue"
  ],
  "examples": [
    "I really appreciate your help with my project.",
    "I would appreciate receiving your reply as soon as possible."
  ],
  "example_translations": [
    "من واقعاً از کمک شما در پروژه‌ام قدردانی می‌کنم.",
    "ممنون می‌شوم اگر پاسخ خود را در اسرع وقت برایم ارسال کنید."
  ],
  "grammar_tip": "فعل appreciate معمولاً با اسم یا اسم مصدر (فعل همراه با ing) به‌کار می‌رود و نباید بعد از آن از مصدر با to استفاده کرد."
}
```

### gemini-flash-lite-latest

#### run

```json
{
  "word": "run",
  "phonetic": {
    "ipa": "/rʌn/",
    "persian": "ران"
  },
  "fa_meaning": "دویدن، اداره کردن",
  "fa_explanation": "حرکت سریع با پاها، یا مدیریت و کنترل کردن یک کسب‌وکار یا ماشین.",
  "synonyms": [
    "jog",
    "sprint",
    "manage"
  ],
  "antonyms": [
    "walk",
    "stop"
  ],
  "examples": [
    "I like to run in the park every morning.",
    "She runs a small coffee shop downtown."
  ],
  "example_translations": [
    "من دوست دارم هر روز صبح در پارک بدوم.",
    "او یک کافی‌شاپ کوچک در مرکز شهر را اداره می‌کند."
  ],
  "grammar_tip": "فعل run بی‌قاعده است و شکل گذشته آن ran و اسم مفعول آن خودش یعنی run است (run - ran - run)."
}
```

#### break a leg

```json
{
  "word": "break a leg",
  "phonetic": {
    "ipa": "/breɪk ə leɡ/",
    "persian": "بریک اِ لگ"
  },
  "fa_meaning": "موفق باشی / ان‌شاءالله موفق شوی",
  "fa_explanation": "یک اصطلاح رایج که معمولاً قبل از شروع اجرای روی صحنه، امتحان یا مصاحبه به کسی می‌گویند تا برایش آرزوی موفقیت کنند (در واقع برعکس معنای ظاهری‌اش است!).",
  "synonyms": [
    "good luck",
    "best of luck"
  ],
  "antonyms": [],
  "examples": [
    "Break a leg at your job interview tomorrow!",
    "All the actors hugged before going on stage and said, 'Break a leg!'"
  ],
  "example_translations": [
    "فردا در مصاحبه کاری‌ات موفق باشی!",
    "همه بازیگران قبل از رفتن روی صحنه همدیگر را بغل کردند و گفتند: «موفق باشید!»"
  ],
  "grammar_tip": "این یک اصطلاح (Idiom) ثابت است؛ یعنی نباید زمان فعل را عوض کنید یا ضمیر آن را تغییر دهید، همیشه دقیقاً به همین شکل «break a leg» استفاده می‌شود."
}
```

#### actually

```json
{
  "word": "actually",
  "phonetic": {
    "ipa": "/ˈæktʃuəli/",
    "persian": "اکچوالی"
  },
  "fa_meaning": "در واقع، راستش را بخواهید",
  "fa_explanation": "این کلمه برای بیان حقیقت، غافلگیری یا اصلاح یک حرف استفاده می‌شود.",
  "synonyms": [
    "really",
    "in fact",
    "truly"
  ],
  "antonyms": [],
  "examples": [
    "I thought the movie would be boring, but it was actually very good.",
    "Are you actually going to quit your job?"
  ],
  "example_translations": [
    "فکر می‌کردم فیلم خسته‌کننده باشد، اما در واقع خیلی خوب بود.",
    "آیا واقعاً می‌خواهی کار خود را رها کنی؟"
  ],
  "grammar_tip": "بر خلاف تصور رایج، کلمه actually به معنی «اکنون» نیست، بلکه به معنی «در واقع» یا «راستش» است."
}
```

#### get up

```json
{
  "word": "get up",
  "phonetic": {
    "ipa": "/ɡɛt ʌp/",
    "persian": "گِت آپ"
  },
  "fa_meaning": "بیدار شدن، از خواب بلند شدن",
  "fa_explanation": "این اصطلاح معمولاً زمانی استفاده می‌شود که فرد از رختخواب خود برمی‌خیزد یا از حالت نشسته به ایستاده درمی‌آید.",
  "synonyms": [
    "wake up",
    "rise",
    "stand up"
  ],
  "antonyms": [
    "lie down",
    "sit down",
    "go to bed"
  ],
  "examples": [
    "I usually get up at 7 AM every day.",
    "She got up early to study for her exam."
  ],
  "example_translations": [
    "من معمولاً هر روز ساعت ۷ صبح از خواب بیدار می‌شوم.",
    "او زود بیدار شد تا برای امتحانش درس بخواند."
  ],
  "grammar_tip": "عبارت get up یک فعل دوقسمتی (phrasal verb) جداشدنی نیست، یعنی نمی‌توانیم ضمیر را وسط آن بیاوریم؛ مثلاً بگوییم get me up نادرست است (مگر در معنای بیدار کردن دیگری)."
}
```

#### however

```json
{
  "word": "however",
  "phonetic": {
    "ipa": "/haʊˈevər/",
    "persian": "هاوِوِر"
  },
  "fa_meaning": "با این حال، اما",
  "fa_explanation": "کلمه‌ای برای بیان تضاد یا غافلگیری بین دو جمله است و معمولاً با کاما استفاده می‌شود.",
  "synonyms": [
    "nevertheless",
    "yet",
    "still"
  ],
  "antonyms": [
    "therefore",
    "consequently"
  ],
  "examples": [
    "It was raining heavily; however, we still went for a walk.",
    "She studied hard for the test; however, she didn't pass."
  ],
  "example_translations": [
    "باران شدیدی می‌بارید؛ با این حال، ما باز هم برای پیاده‌روی رفتیم.",
    "او سخت برای امتحان درس خواند؛ اما قبول نشد."
  ],
  "grammar_tip": "واژه however معمولاً در ابتدای جمله دوم می‌آید و بعد از آن از کاما (,) استفاده می‌شود."
}
```

#### cozy

```json
{
  "word": "cozy",
  "phonetic": {
    "ipa": "/ˈkoʊ.zi/",
    "persian": "کوزی"
  },
  "fa_meaning": "دنج و راحت",
  "fa_explanation": "به مکانی گرم، راحت و کوچک گفته می‌شود که حس آرامش و امنیت می‌دهد.",
  "synonyms": [
    "comfortable",
    "snug",
    "warm"
  ],
  "antonyms": [
    "uncomfortable",
    "cold",
    "uninviting"
  ],
  "examples": [
    "I like to read a book in my cozy corner on rainy days.",
    "Their new apartment is small, but it is very cozy."
  ],
  "example_translations": [
    "من دوست دارم در روزهای بارانی در گوشه دنج خودم کتاب بخوانم.",
    "آپارتمان جدید آن‌ها کوچک است، اما بسیار دنج و راحت است."
  ],
  "grammar_tip": "واژه cozy یک صفت (adjective) است و می‌توانید از آن قبل از اسم (cozy room) یا بعد از فعل‌های ربطی مانند be و feel استفاده کنید (The room feels cozy)."
}
```

#### procrastinate

```json
{
  "word": "procrastinate",
  "phonetic": {
    "ipa": "/prəˈkræstɪneɪt/",
    "persian": "پره-کْرَستین-هِیت"
  },
  "fa_meaning": "امروزه فردا کردن، به تعویق انداختن",
  "fa_explanation": "به تأخیر انداختن انجام کارها، به‌ویژه کارهای مهم، معمولاً به دلیل تنبلی یا ترجیح دادن کارهای راحت‌تر.",
  "synonyms": [
    "delay",
    "postpone",
    "put off"
  ],
  "antonyms": [
    "advance",
    "hurry",
    "proceed"
  ],
  "examples": [
    "I tend to procrastinate when I have a difficult assignment.",
    "Don't procrastinate until the last minute to study for the exam."
  ],
  "example_translations": [
    "وقتی تکلیف سختی دارم، معمولاً کارها را به تعویق می‌اندازم.",
    "برای امتحان تا دقیقه ۹۰ صبر نکن و درس خواندن را عقب نینداز."
  ],
  "grammar_tip": "این واژه یک فعل لازم (intransitive) است و اغلب با حرف اضافه on می‌آید، مثلاً: procrastinate on homework."
}
```

#### book

```json
{
  "word": "book",
  "phonetic": {
    "ipa": "/bʊk/",
    "persian": "بوک"
  },
  "fa_meaning": "کتاب / رزرو کردن",
  "fa_explanation": "این وا هم به عنوان اسم به معنی مجموعه‌ای از صفحات چاپی (کتاب) و هم به عنوان فعل به معنی ثبت کردن یا رزرو کردن جا به کار می‌رود.",
  "synonyms": [
    "reserve",
    "novel",
    "publication"
  ],
  "antonyms": [
    "cancel"
  ],
  "examples": [
    "I like to read a good book before going to sleep.",
    "We need to book our hotel rooms for the summer trip soon."
  ],
  "example_translations": [
    "من دوست دارم قبل از خواب یک کتاب خوب بخوانم.",
    "ما باید به زودی اتاق‌های هتل خود را برای سفر تابستانی رزرو کنیم."
  ],
  "grammar_tip": "واژه book هم می‌تواند اسم قابل شمارش باشد (a book) و هم فعل (to book a ticket)، که در حالت فعل معمولاً برای رزرو بلیط، هتل یا میز استفاده می‌شود."
}
```

#### ironic

```json
{
  "word": "ironic",
  "phonetic": {
    "ipa": "/aɪˈrɒnɪk/",
    "persian": "آی-رُنیک"
  },
  "fa_meaning": "کنایه‌آمیز، متناقض‌نما",
  "fa_explanation": "حالتی که در آن اتفاقی رخ می‌دهد که برعکس انتظار ماست و حالت طنز تلخ یا عجیبی دارد.",
  "synonyms": [
    "paradoxical",
    "contrary",
    "sarcastic"
  ],
  "antonyms": [
    "expected",
    "predictable"
  ],
  "examples": [
    "It is ironic that the fire station burned down last night.",
    "She found it ironic that he called her dishonest."
  ],
  "example_translations": [
    "این کنایه‌آمیز است که ایستگاه آتش‌نشانی دیشب در آتش سوخت.",
    "او این را متناقض دید که آن مرد، او را فردی بی‌صداقت خطاب کرد."
  ],
  "grammar_tip": "پسوند ic- معمولاً اسم‌ها را به صفت تبدیل می‌کند (مثل iron به ironic). حواست باشد که تلفظ آن با واژه iron متفاوت است."
}
```

#### RSVP

```json
{
  "word": "RSVP",
  "phonetic": {
    "ipa": "/ˌɑːr.es.viːˈpiː/",
    "persian": "آر-اس-وی-پی"
  },
  "fa_meaning": "لطفاً پاسخ دهید",
  "fa_explanation": "مخفف یک عبارت فرانسوی است که در دعوت‌نامه‌ها نوشته می‌شود تا از مهمانان خواسته شود حضور یا عدم حضور خود را اطلاع دهند.",
  "synonyms": [
    "reply",
    "respond"
  ],
  "antonyms": [],
  "examples": [
    "Please RSVP by Friday so we can finalize the guest list.",
    "She forgot to RSVP for the wedding, so they don't know if she is coming."
  ],
  "example_translations": [
    "لطفاً تا جمعه پاسخ دهید تا بتوانیم فهرست مهمانان را نهایی کنیم.",
    "او فراموش کرد برای عروسی پاسخ دهد، بنابراین آن‌ها نمی‌دانند که او می‌آید یا نه."
  ],
  "grammar_tip": "این واژه گاهی به عنوان فعل هم استفاده می‌شود؛ مثلاً 'to RSVP to an invitation' به معنای پاسخ دادن به یک دعوت‌نامه است."
}
```

#### couch potato

```json
{
  "word": "couch potato",
  "phonetic": {
    "ipa": "/kaʊtʃ pəˈteɪtoʊ/",
    "persian": "کاوچ پَتِیتو"
  },
  "fa_meaning": "شخص تنبل و کم‌تحرک",
  "fa_explanation": "به کسی گفته می‌شود که وقت زیادی را بدون تحرک روی مبل می‌گذراند و معمولاً تلویزیون تماشا می‌کند.",
  "synonyms": [
    "lazybones",
    "slacker"
  ],
  "antonyms": [
    "workaholic",
    "active person"
  ],
  "examples": [
    "He became a real couch potato after he bought that huge TV.",
    "Instead of being a couch potato, let's go for a walk in the park."
  ],
  "example_translations": [
    "او پس از خرید آن تلویزیون بزرگ، واقعاً آدم تنبلی شد.",
    "به جای تنبلی کردن و نشستن روی مبل، بیایید برویم پیاده‌روی در پارک."
  ],
  "grammar_tip": "این عبارت یک اصطلاح (idiom) است و برای جمع بستن آن، کلمه دوم یعنی potato جمع بسته می‌شود (couch potatoes)."
}
```

#### appreciate

```json
{
  "word": "appreciate",
  "phonetic": {
    "ipa": "/əˈpriːʃieɪt/",
    "persian": "أپریشِیت"
  },
  "fa_meaning": "قدردانی کردن، قدر دانستن",
  "fa_explanation": "درک کردن ارزش یک چیز یا شخص و سپاسگزار بودن برای آن.",
  "synonyms": [
    "value",
    "grateful",
    "recognize"
  ],
  "antonyms": [
    "despise",
    "ignore"
  ],
  "examples": [
    "I really appreciate your help with this project.",
    "She doesn't seem to appreciate good music."
  ],
  "example_translations": [
    "من واقعاً از کمک شما در این پروژه قدردانی می‌کنم.",
    "به نظر می‌رسد او قدر موسیقی خوب را نمی‌داند."
  ],
  "grammar_tip": "این فعل معمولاً بعد از خود مفعول می‌گیرد و با اسم یا ضمیر می‌آید (مثل appreciate your help) و برای تشکر رسمی و نیمه‌رسمی بسیار کاربردی است."
}
```
