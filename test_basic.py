import time

import telebot.types  # type: ignore

import models
import tasking
import texts
from dialogue_management import DialogueManager, FakeBot
from states import States

TEST_USER_ID = 123
TEST_PROJECT_ID = 100500
LAST_MESSAGE_ID = 1


def get_test_message(text) -> telebot.types.Message:
    global LAST_MESSAGE_ID
    LAST_MESSAGE_ID += 1

    user = telebot.types.User(
        id=TEST_USER_ID, first_name="David", is_bot=False, username="test_user"
    )
    chat = telebot.types.Chat(id=TEST_USER_ID, type="private")
    message = telebot.types.Message(
        message_id=LAST_MESSAGE_ID,
        from_user=user,
        date=int(time.time()),
        chat=chat,
        content_type="text",
        options={},
        json_string="",
    )
    message.text = text
    return message


def setup_fake_project(db: models.Database):
    project = db.create_project(title="Test project", save=False)
    project.project_id = TEST_PROJECT_ID
    project.min_score = 4
    project.overlap = 1
    project.src_code = 'eng'
    project.tgt_code = 'rus'
    db.save_project(project)
    task1 = db.create_task(
        project=project, prompt="This is a first task prompt", save=True
    )
    src1 = db.create_input(
        project=project,
        task=task1,
        source="First source text",
        save=True,
    )
    src2 = db.create_input(
        project=project,
        task=task1,
        source="Second source text",
        save=True,
    )
    cand1 = db.create_translation(
        user_id=models.NO_USER,
        trans_input=src1,
        text="Первый текст но какая-то ересь",
    )
    db.add_translations([cand1])


def test_basic_scenario():
    db = models.Database.setup(mongo_url=None)
    setup_fake_project(db)

    bot = FakeBot()
    manager = DialogueManager(db=db, bot=bot)

    # Start the dialogue
    msg = get_test_message("/start")
    manager.respond(msg)
    assert texts.HELP in bot.last_message.text

    # Ask for the task and get the first and only one
    manager.respond(get_test_message("/task"))
    assert "first task prompt" in bot.last_message.text

    # Rating the first candidate poorly and being asked to translate it
    manager.respond(get_test_message(texts.RESP_TAKE_TASK))
    assert "First source text" in bot.last_message.text
    assert "какая-то ересь" in bot.last_message.text
    # assert "связн" in bot.last_message.text
    # manager.respond(get_test_message(texts.RESP_INCOHERENT))
    assert "от 1 до 5" in bot.last_message.text
    manager.respond(get_test_message("3"))
    assert "First source text" in bot.last_message.text
    assert "предложите его перевод" in bot.last_message.text

    # Adding the second task before we finish the first one!
    project = db.get_project(project_id=TEST_PROJECT_ID)
    task2 = db.create_task(
        project=project, prompt="This is a second task prompt", save=True
    )
    src3 = db.create_input(
        project=project,
        task=task2,
        source="Third source text",
        save=True,
    )
    cand2 = db.create_translation(
        user_id=models.NO_USER,
        trans_input=src3,
        text="Третий текст",
    )
    db.add_translations([cand2])

    # Immediately producing the second translation and being asked for a new task
    manager.respond(get_test_message("Первый текст"))  # translation of the prev input
    assert "Second source text" in bot.last_message.text
    assert "предложите его перевод" in bot.last_message.text
    task1_id = db.get_user(TEST_USER_ID).curr_task_id
    manager.respond(get_test_message("Второй текст"))
    assert "Хотите взять ещё одно?" in bot.last_message.text

    # Checking that the first task is NOT YET complete
    assert db.get_task(task1_id).completed is False

    # getting the second task, and scoring the third candidate well
    manager.respond(get_test_message(texts.RESP_YES))
    assert "second task prompt" in bot.last_message.text
    manager.respond(get_test_message(texts.RESP_TAKE_TASK))
    assert "Третий текст" in bot.last_message.text
    assert "от 1 до 5" in bot.last_message.text
    manager.respond(get_test_message("5"))
    task2_id = db.get_user(TEST_USER_ID).curr_task_id
    assert "связн" in bot.last_message.text
    manager.respond(get_test_message(texts.RESP_COHERENT))
    assert "Хотите взять ещё одно?" in bot.last_message.text

    # Checking that the second task is already complete
    assert db.get_task(task2_id).completed is True

    # Refusing one more task
    manager.respond(get_test_message(texts.RESP_NO))
    assert "заходите перевести" in bot.last_message.text

    manager.respond(get_test_message("/task"))
    assert "нет никаких заданий" in bot.last_message.text
