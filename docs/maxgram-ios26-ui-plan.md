# Maxgram — редизайн UI/UX под Telegram на iOS 26 (Liquid Glass)

База: `26.25.0-1.5.2` (apktool-декомпиляция MAX, smali + res).
Референсы: 4 скриншота Telegram iOS 26 — чат, список чатов, таб-бар, профиль.

> ⚠️ Ключевой факт архитектуры: интерфейс MAX (OneMe design system) в основном
> построен **программно в smali** (кастомные View, runtime-темы), а не в XML-layout.
> Поэтому редизайн делится на «ресурсную» часть (быстро, безопасно) и «smali» часть
> (глубокая работа). Добавление **новых** имён ресурсов ломает `public.xml` —
> переопределяем существующие значения, новые id не вводим без необходимости.

---

## 1. Дизайн-токены (из референсов)

| Токен | Значение | Где применяется |
|---|---|---|
| Accent / system blue | `#007AFF` | активная вкладка, send-кнопка, ссылки, чекбоксы |
| Badge red | `#FF3B30` | счётчики непрочитанного, бейдж на табе Chats |
| Фон списка чатов | `#FFFFFF` / night `#000000` | chat list |
| Разделители | `#C6C6C8`, 0.5 dp | список чатов |
| Входящий пузырь | `#FFFFFF` + мягкая тень | чат |
| Исходящий пузырь | градиент `#5AC8FA → #007AFF` (или solid `#0A84FF`) | чат |
| Стекло (glass) | `#B3FFFFFF` (70% white) + blur | таб-бар, шапка чата, инпут-бар, кнопки профиля |
| Радиус пузырей | 18 dp | сообщения |
| Радиус карточек | 16 dp | профиль (mobile/username/date of birth) |
| Радиус «капсул» | 28 dp (fully rounded) | таб-бар, шапка, инпут-бар, кнопки действий |
| Отступы капсул от краёв | 12–16 dp | floating-элементы |

## 2. Разбор по экранам

### 2.1 Список чатов (скрин 3)
- [ ] Stories-рейл сверху (кружки с градиентным кольцом) — **research**: у MAX нет stories; варианты: скрыть, либо показывать «недавние контакты». Тег: `smali-hard`
- [ ] Строка папок-чипов: `All Chats / New / Family / Church / Work / People` — у MAX нет папок как в Telegram; реалистично: статичный ChipRow + фильтрация по «избранное/каналы/группы». Тег: `smali-hard`
- [ ] Закреплённый «Saved Messages» с иконкой-закладкой. Тег: `smali-medium`
- [ ] Бейджи непрочитанного: серые `#8E8E93` для muted, синие `#007AFF` для обычных. Тег: `res`+`smali`
- [ ] Тонкие разделители 0.5 dp с отступом от аватара. Тег: `res`

### 2.2 Плавающий таб-бар (скрин 2)
- [ ] Заменить Material bottom bar на floating-капсулу: margins 12 dp, radius 28 dp, elevation 8 dp, фон `#B3FFFFFF` (+ `RenderEffect` blur на API 31+, fallback — полупрозрачный белый). Тег: `smali-medium`
- [ ] Вкладки: Contacts / Calls / Chats / Settings; активная — `#007AFF`, бейдж красный. Тег: `smali-medium`
- [ ] Высота 56 dp (`design_bottom_navigation_height` уже есть в `res/values/dimens.xml` — переопределить/использовать). Тег: `res`
- Поиск точки входа: строки вкладок в `res/values-ru/strings.xml` → id в `public.xml` → использование id в smali (класс главного экрана OneMe).

### 2.3 Экран чата (скрин 1)
- [ ] Шапка: floating glass-капсула (назад | аватар + имя + статус online | аватарка справа). Тег: `smali-hard`
- [ ] Пузыри: входящие белые radius 18 dp с тенью; исходящие — синий градиент, время внутри пузыря, галочки. Тег: `smali-medium` (OneMe рисует пузыри кастомной View — искать класс message/bubble view, цвета из runtime-темы)
- [ ] Инпут-бар: glass-капсула — скрепка, поле ввода, эмодзи, синяя круглая send-кнопка со стрелкой. Тег: `smali-medium`
- [ ] Фон чата: светлый паттерн-wallpaper (drawable). Тег: `res`
- [ ] Дата-чипы и сервисные сообщения — серые glass-пилюли. Тег: `smali-medium`

### 2.4 Профиль (скрин 4)
- [ ] Фото на весь экран сверху + градиентный скрим, кнопки «назад» и «Edit» — glass-круги. Тег: `smali-medium`
- [ ] Ряд действий glass-кругами: call / video / mute / search / more. Тег: `smali-medium`
- [ ] Инфо-карточки (канал, mobile, username, date of birth) — белые карточки radius 16 dp, сгруппированные. Тег: `res`+`smali`

## 3. Ребрендинг → Maxgram (stage 0)
- [ ] Имя приложения: `res/values/strings.xml`, `res/values-ru/strings.xml`, `values-en` — ключ из `android:label` в `AndroidManifest.xml` → `Maxgram`. Тег: `res`
- [ ] Иконка: `mipmap-*/ic_launcher*` (генерим adaptive icon локально, через API бинарники не залить). Тег: `local`
- [ ] Переименовать репозиторий: Settings → General → Repository name → `Maxgram` (API форка не позволяет задать имя). Тег: `manual`

## 4. Порядок работ (ветки)
1. `maxgram/rebrand` — имя, иконка, README. Риск: низкий.
2. `maxgram/ios26-tokens` — палитра/размеры в `res/values*/colors.xml`, `dimens.xml`, `color-night`. Риск: низкий (но OneMe красит многое в runtime — см. п.5).
3. `maxgram/ios26-tabbar` — floating glass таб-бар. Риск: средний.
4. `maxgram/ios26-chat` — пузыри, инпут-бар, шапка. Риск: средний-высокий.
5. `maxgram/ios26-profile` — профиль. Риск: средний.
6. `maxgram/ios26-folders-stories` — чипы папок, stories-рейл. Риск: высокий / research.

## 5. Технические заметки
- **Runtime-тема OneMe**: если изменение `colors.xml` не даёт эффекта — цвет зашит константой в smali. Поиск: `search_code` по hex (например `0xff007aff` / `const v…, -0xff0001`-стиль) или по имени цвета из `public.xml` → usage в smali.
- **Blur на Android**: настоящего «liquid glass» нет; эмуляция = полупрозрачный фон + `RenderEffect` (API 31+). В smali это ~10–15 инструкций на View. Fallback для API < 31: `#E6F2F2F7`.
- **Сборка**: `apktool b 26.25.0-1.5.2 -o maxgram.apk` → `zipalign` → `apksigner`. После каждого stage — smoke-тест: запуск, список чатов, чат, профиль.
- **Anti-tamper**: модифицированный клиент может получать проблемы с логином/пушами — тестировать на отдельном аккаунте.
- **CI**: добавить `.github/workflows/build.yml` (apktool + apksigner, артефакт APK) — отдельной задачей.

## 6. Definition of Done (MVP «как на скринах»)
- [ ] Таб-бар — floating glass-капсула с 4 вкладками и красным бейджем
- [ ] Список чатов — белый фон, тонкие разделители, синие/серые бейджи
- [ ] Чат — белые/синие пузыри 18 dp, glass-инпут, glass-шапка
- [ ] Профиль — full-bleed фото + 5 glass-кнопок + карточки 16 dp
- [ ] Имя пакета отображается как Maxgram, новая иконка
