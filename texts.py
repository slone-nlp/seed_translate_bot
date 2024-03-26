from models import INCOHERENT, COHERENT

MENU = """Полезные команды:
/guidelines - инструкции по переводу и его оценке (с этого стоит начать!) 
/task - приступить к новому заданию
/resume - продолжить текущее задание
/help - показать описание бота
/setup - настройка бота
/stats - статистика проекта

По всем вопросам пишите @cointegrated."""

HELP = """Привет! Это бот для сбора переводов, авторства @cointegrated (канал @izolenta_mebiusa). 

В настоящий момент он фокусируется на переводе корпуса NLLB-Seed (https://oldi.org/) с английского на русский.
Корпус NLLB-Seed был собран на основе Википедии (статья: https://aclanthology.org/2023.acl-long.154/) так, чтобы улучшить качество моделей машинного перевода, обученных на нём.
Дальше будет перевод с русского на другие языки, для которых существует мало параллельных текстов на разнообразные темы.

Ваша работа будет состоять из заданий. Каждое задание состоит из нескольких предложений на общую тему (в настоящий момент темы определяются статьями из Википедии).
Вам нужно будет оценивать качество имеющихся переводов этих предложений и/или предлагать ваши собственные переводы.

Если какая-то тема вам неинтересна или не близка, вы отказаться от предложенного задания, и вам будет предложено другое (рандомно).
Если, взявшись за задание, вы передумали, в любой момент командой /task вы можете выбрать другое задание (ваши промежуточные результаты будут сохранены).

Перед началом работы по переводу, пожалуйста, прочитайте гайдлайны проекта OLDI (внизу страницы https://oldi.org/guidelines).
Кроме этого, первое время при каждом вопросе вам будут показываться подробные инструкции по переводу и его оценке.
В любой последующий момент вы можете почитать эти инструкции с помощью команды /guidelines.

Чтобы вернуться к выполнению текущего задания, в любой момент вы можете ввести команду /resume."""

GUIDELINES_HEADER = """У вас будут три вида задач: оценивать связность перевода, оценивать точность перевода, и предлагать собственные переводы."""

DO_NOT_ASSIGN_TASK = """Ничего страшного! Огромное вам спасибо за уже выполненное задание! Когда будут время и силы, заходите перевести ещё кусочек корпуса 😊"""

RESP_TAKE_TASK = "беру это задание"
RESP_SKIP_TASK = "попробовать другое"

RESP_YES = "Да"
RESP_NO = "Нет"

XSTS_PROMPT = """Насколько перевод точен, по шкале от 1 до 5?"""

XSTS_GUIDELINE = """Точность перевода оценивается по пятибалльной шкале:
1 - Непохожие предложения: разные темы или мало общих деталей;
2 - Похожие предложения, но ключевая информация различается;
3 - Ключевой смысл совпадает, но мелкие детали могут различаться;
4 - Смысл практически эквивалентный, но стиль может различаться;
5 - Смысл и стиль переданы 100% верно."""


XSTS_RESPONSES = ["1", "2", "3", "4", "5"]

COHERENCE_PROMPT = """Является ли перевод связным?"""

COHERENCE_GUIDELINE = """Под связностью мы понимаем общее качество текста, без особой привязки к тому, точен ли он как перевод.
Связность перевода оценивается бинарно: связный либо несвязный.

Что может сделать перевод НЕсвязным:
- 50% или более перевода - не на целевом языке (или вообще не является человеческим языком);
- нельзя понять даже примерный смысл перевода из-за ошибок в грамматике или использования несуществующих слов;
- перевод некорректно отображается или вообще пустой.

В случае, если все проблемы перевода унаследованы от исходного текста, он всё ещё считается связным.

Если предложенный перевод не совпадает по смыслу с оригиналом (даже не близко), но написан понятно и грамотно, он всё ещё может считаться связным!"""

RESP_INCOHERENT = "несвязный"
RESP_COHERENT = "связный"
COHERENCE_RESPONSES = [RESP_INCOHERENT, RESP_COHERENT]
COHERENCE_RESPONSES_MAP = {RESP_INCOHERENT: INCOHERENT, RESP_COHERENT: COHERENT}

TRANSLATION_GUIDELINE = """Приступая к собственному переводу, пожалуйста, прочитайте гайдлайны проекта OLDI (внизу страницы https://oldi.org/guidelines).
Из самого важного:
- Старайтесь избегать машинного перевода, а если всё-таки используете его, то переводите отдельные слова или фразы, а не предложения целиком.
- Старайтесь переводить, максимально точно передавая смысл, стиль и форму исходного текста.
- Не пытайтесь конвертировать единицы измерения, просто переводите их.
- Имена людей, названия мест, организаций, произведений и т.п. старайтесь переводить так, как принято в целевом языке."""

NAVIGATION = """Чтобы взяться за новое задание, отправьте команду /task.
Чтобы выйти в основное меню, отправьте команду /help"""

NO_CURRENT_TASK = "В настоящий момент у вас нет активных заданий."

SETUP_ASK_SRC_LANG = """Сейчас я задам вам несколько вопросов для знакомства.
Для начала, пожалуйста, перечислите через запятую языки, С КОТОРЫХ вы готовы переводить.
В ближайшее время мы будем переводить только с английского на русский, но в будущем другие языки могут пригодиться."""

SETUP_ASK_TGT_LANG = """Сейчас, пожалуйста, перечислите через запятую языки, НА КОТОРЫЕ вы готовы переводить.
В ближайшее время мы будем переводить только с английского на русский, но в будущем другие языки могут пригодиться."""

SETUP_ASK_CONTACT_INFO = """Пожалуйста, укажите, как с вами можно связаться (например, email или username в Телеграме).
Если не хотите, чтобы к вам никто не обращался по поводу этих переводов, можно отправить пустое сообщение."""

SETUP_READY = "На этом с вопросами всё!\n" + NAVIGATION

FALLBACK = """
Простите, кажется, я потерял нить разговора.
Если эта ошибка повторяется регулярно, пожалуйста, пожалуйтесь о ней @cointegrated.
Чтобы выйти в основное меню, отправьте команду /help.
"""

RESP_TASK_LOST = (
    "Простите, задание потерялось. Нажмите /help для выхода в основное меню."
)
