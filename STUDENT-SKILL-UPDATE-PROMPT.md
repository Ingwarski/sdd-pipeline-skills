# Prompt для оновлення SDD Pipeline Skills

> Скопіюйте цей prompt і вставте його в Codex або Claude Code.

```text
Онови моє локальне встановлення SDD Pipeline Skills після перейменування репозиторію.

Контекст:
- старий GitHub-репозиторій: https://github.com/Ingwarski/codex-skills
- новий GitHub-репозиторій: https://github.com/Ingwarski/sdd-pipeline-skills
- стара назва: Codex Skills / Codex SDD Skills
- нова назва: SDD Pipeline Skills
- нова локальна назва clone: SDD Pipeline Skills

Виконай оновлення без втрати моїх локальних змін і без зміни стабільних назв скілів.

Вимоги:

1. Знайди фактичний durable clone репозиторію та перевір:
   - `git status`;
   - поточну гілку;
   - `git remote -v`;
   - чи справді це репозиторій SDD Pipeline Skills.

2. Онови `origin` на:
   `https://github.com/Ingwarski/sdd-pipeline-skills.git`

3. Якщо локальні зміни існують, не перезаписуй і не видаляй їх. Спочатку покажи їх і зупинись перед небезпечною операцією. Якщо робоче дерево чисте, онови репозиторій через clean fast-forward з `origin/main`.

4. Прочитай актуальні `README.md`, `AGENTS.md` або `CLAUDE.md`, а також `skills-manifest.json`.

5. Визнач операційну систему та запусти штатний installer із clone:
   - macOS/Linux: `./install.sh --all --repair`
   - Windows: `.\install.ps1 -All -Repair`

   Не копіюй папки скілів вручну і не створюй власну логіку symlink/junction.

6. Переконайся, що встановлено всі 13 SDD Pipeline skills для Codex і Claude Code, якщо обидва інструменти доступні.

7. Запусти installer повторно, щоб перевірити idempotence.

8. Перевір, що такі імена скілів залишилися незмінними:
   - `to-product-idea`
   - `to-sdd-prd`
   - `to-project-context`
   - `to-guardrails`
   - `to-user-journey`
   - `to-screen-map`
   - `to-wireframes`
   - `to-design-brief`
   - `to-architecture`
   - `to-dod-evals`
   - `to-qa-checklist`
   - `to-development-plan`
   - `to-sdd-pipeline`

   Не перейменовуй ці identifiers і не створюй дублікати або compatibility aliases.

9. Перевір усі встановлені `SKILL.md` через фактичні destination paths:
   - чи посилання ведуть на новий clone;
   - чи немає broken links;
   - чи немає старих посилань на `/Codex Skills`;
   - чи всі 13 skills проходять validation.

10. Не видаляй сторонні або непов’язані skills. Зокрема, якщо існує сторонній `to-prd`, збережи його. Власний PRD skill цього репозиторію називається `to-sdd-prd`.

11. У фінальному звіті покажи:
   - фактичний шлях до локального clone;
   - актуальний GitHub remote;
   - гілку та commit;
   - Codex skills destination;
   - Claude Code skills destination;
   - тип встановлення: symlink або Windows junction;
   - результат перевірки `13/13`;
   - чи були локальні конфлікти;
   - чи потрібен restart Codex або Claude Code.

Не змінюй архітектуру SDD Pipeline, manifest, output paths, назви skills або спосіб їх виклику. Потрібно лише оновити джерело репозиторію та коректно перев’язати локальні встановлення на нову назву.
```
