# Єдиний промпт для встановлення або оновлення

Скопіюйте блок у локальний Codex або Claude Code, який має доступ до термінала. Замініть `<АБСОЛЮТНИЙ ШЛЯХ>` повним шляхом до постійного каталогу скілсету. Наприклад, продукт і скілсет можуть бути сусідами в особистій папці Projects.

```text
Встанови або онови SDD Pipeline Skills для локальних Codex і Claude Code. Мій точний постійний каталог скілсету: <АБСОЛЮТНИЙ ШЛЯХ>. Офіційний репозиторій: https://github.com/Ingwarski/sdd-pipeline-skills.git. Канал: stable. Якщо я не вказав один абсолютний шлях, спитай його. Поточний робочий каталог агента не визначає місце встановлення. Папка продукту, будь-яка її підпапка і Git worktree не підходять. Нова папка може бути відсутня або повністю порожня, включно з прихованими файлами.

Дій за docs/installation.md, розділ «Guarded entry point», з тієї самої офіційної ревізії. Спочатку визнач ОС і версію Python. Через git ls-remote прочитай повний SHA refs/heads/stable. Завантаж у тимчасовий файл scripts/install_location.py за адресою https://raw.githubusercontent.com/Ingwarski/sdd-pipeline-skills/<SHA>/scripts/install_location.py, підставивши саме цей SHA. Зупинись, якщо канал або файл недоступний. Не підміняй stable на main. Не запускай звичайний git clone, git pull, git fetch чи старий installer/updater замість захищеної процедури.

Для вже актуального встановлення з підтримуваною Python збережи наявну версію. Якщо потрібне встановлення чи оновлення, дотримуйся чинних вимог docs/installation.md: перевір останню стабільну Python 3 на python.org, за потреби встанови її з офіційного джерела, потім перевір активну версію. Цей промпт дозволяє таке встановлення. Не замінюй системний Python.

Для нового місця запусти:
python3 -B "<завантажений файл>" bootstrap --destination "<мій повний шлях>" --revision "<SHA>" --channel stable
Для наявного самостійного клону в указаному місці запусти ту саму команду з update замість bootstrap. У Windows використовуй python. За замовчуванням встановлюються обидва агенти; вибір одного задається --agent codex або --agent claude. Окремо врахуй фізичний шлях кожної особистої папки реєстрації, включно з --codex-dir, --claude-dir, CODEX_SKILLS_DIR, CODEX_HOME, CLAUDE_SKILLS_DIR, CLAUDE_CONFIG_DIR і батьківськими посиланнями або junction. Не створюй .agents/skills чи .claude/skills у продукті.

Якщо guard відхилив шлях, повідом вибраний і конфліктний шляхи та посилання на «Recover a misplaced installation» у docs/installation.md. Залиш файли на місці. Не очищуй папку, не приховуй зміни через .gitignore й не обирай інший шлях самостійно. Для старої помилкової інсталяції спочатку потрібні інвентаризація з прихованими та невідстежуваними файлами, перевірена приватна резервна копія і погоджений перелік конкретних доданих елементів для карантину. Для непов’язаної старої Git-історії читай HISTORY-REWRITE.md.

Використовуй 13 записів skills-manifest.json вибраної ревізії. Старе ім’я SDD to-prd відповідає to-sdd-prd. Встановлюй канонічне ім’я без дублювання. Сторонній to-prd належить його власнику. Штатна операція може назавжди видалити два імені з retired-skills.txt у перевірених керованих каталогах. Не додавай каталоги старих установок до очищення й не запускай retire-only без окремої вказівки.

Після успіху покажи фізичний шлях клону, повний SHA, канал, точний каталог реєстрації для кожного вибраного агента та всі 13 пар «посилання → фактична ціль» для кожного. Перевір доступ до вкладених ресурсів, зазнач помилки та потребу перезапуску. Якщо встановлення вже актуальне, так і напиши й наведи ті самі шляхи та цілі. Будь-які помилки очищення повідом явно.

Це встановлення скілів. Окреме налаштування доказів для конкретного продукту виконуй за docs/evidence-storage.md лише за явним запитом із точним шляхом продукту. Не використовуй поточну папку як evidence project. Не мігруй продукти, не налаштовуй фонові оновлення і не завантажуй дані проєкту під час встановлення.
```

### English and Polish

A course can use the same procedure and commands in all three languages. Replace the path placeholder before copying either short request. Both refer the agent to the canonical procedure above.

**English**

```text
Install or update SDD Pipeline Skills for my local Codex and Claude Code. My exact standalone checkout destination is <ABSOLUTE PATH>. Use the canonical INSTALL-OR-UPDATE-PROMPT.md and docs/installation.md from the official stable revision of https://github.com/Ingwarski/sdd-pipeline-skills. Run its revision-pinned location guard before cloning or updating. If this path or a registration root is refused, show me the conflict. Report the physical checkout, full SHA, registration directories and all 13 resolved targets per agent in English.
```

**Polski**

```text
Zainstaluj lub zaktualizuj SDD Pipeline Skills dla mojego lokalnego Codex i Claude Code. Wybrana przeze mnie dokładna ścieżka do osobnego katalogu repozytorium to <ŚCIEŻKA BEZWZGLĘDNA>. Zastosuj procedurę z INSTALL-OR-UPDATE-PROMPT.md i docs/installation.md z oficjalnej rewizji stable repozytorium https://github.com/Ingwarski/sdd-pipeline-skills. Przed klonowaniem lub aktualizacją uruchom narzędzie kontroli lokalizacji z tej samej rewizji. Jeśli odrzuci ścieżkę repozytorium lub rejestracji, podaj ścieżki powodujące konflikt. Podaj po polsku fizyczną ścieżkę repozytorium, pełny SHA, katalogi rejestracji i rzeczywiste ścieżki docelowe wszystkich 13 dowiązań dla każdego agenta.
```
