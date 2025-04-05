import os
import logging
import telebot
import requests
import datetime
import sqlite3
import argparse

STATE_NEED_TOKEN = 'token'
STATE_NEED_EDUCATION = 'education'
STATE_COMPLETE = 'complete'

BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

database = sqlite3.connect('dnevnik.db')
database.row_factory = sqlite3.Row


def init_database():
    try:
        res = database.execute('select count(*) from users').fetchone()
    except sqlite3.OperationalError:
        database.execute('CREATE TABLE users ('
                         '  user_id INTEGER PRIMARY KEY, '
                         '  state TEXT NOT NULL, '
                         '  token TEXT, '
                         '  education_id INTEGER, '
                         '  chat_id INTEGER NOT NULL'
                         ')')

        database.execute('CREATE TABLE educations ('
                         '  education_id INTEGER PRIMARY KEY, '
                         '  user_id INTEGER NOT NULL REFERENCES users(user_id), '
                         '  firstname TEXT NOT NULL, '
                         '  lastname TEXT NOT NULL, '
                         '  school TEXT NOT NULL, '
                         '  class TEXT NOT NULL'
                         ')')

        database.execute('CREATE TABLE schedules ('
                         '  id INTEGER PRIMARY KEY AUTOINCREMENT, '
                         '  user_id INTEGER REFERENCES users(user_id), '
                         '  day INTEGER NOT NULL, '
                         '  time TEXT NOT NULL'
                         ')')
        database.commit()

        res = database.execute('select count(*) from users').fetchone()
    logging.info(f'Total {res[0]} users registered')


def get_user(user_id) -> dict:
    return database.execute('SELECT * FROM users WHERE user_id=?', (user_id,)).fetchone()


@bot.message_handler(commands=['start'])
def send_welcome(message: telebot.types.Message):
    user_id = message.chat.id
    user = get_user(user_id)

    if user is not None:
        database.execute(
            'UPDATE users SET state=?, token=null, chat_id=user_id, education_id=null WHERE user_id=?',
            (STATE_NEED_TOKEN, user_id)
        )

        database.execute('DELETE FROM schedules WHERE user_id=?', (user_id,))
        database.commit()

    else:
        database.execute(
            'INSERT INTO users (user_id, state, chat_id) VALUES (?, ?, ?)',
            (user_id, STATE_NEED_TOKEN, user_id)
        )

    for day in range(7):
        database.execute(
            'INSERT INTO schedules (user_id, day, time) VALUES (?, ?, ?)',
            (user_id, day, "16:00")
        )
    database.commit()

    bot.send_message(
        user_id,
        "Привет, это твой электронный дневник. Для продолжения настройки пришли токен от твоего электронного дневника"
    )
    return


@bot.message_handler(commands=['token'])
def send_token(message: telebot.types.Message):
    user_id = message.chat.id

    user = get_user(user_id)
    if user is None:
        bot.send_message(user_id, u"Сначала используй команду /start")
        return

    if user['state'] not in [STATE_NEED_TOKEN, STATE_NEED_EDUCATION, STATE_COMPLETE]:
        database.execute(
            'DELETE FROM educations WHERE user_id=?',
            (user_id, )
        )
        database.execute(
            'UPDATE users SET token=null WHERE user_id=?',
            (user_id, )
        )
        database.commit()

    token = message.text.split(" ")[-1]
    req = requests.get('https://dnevnik2.petersburgedu.ru/api/journal/person/related-child-list',
                       headers={'X-Jwt-Token': token})
    if req.status_code == 200:
        res = req.json()

        bot.send_message(
            user_id,
            "Токен сохранен. Можешь выбрать время, удобное для отправки дз. Формат: /time weekday HH:MM"
        )
        database.execute("UPDATE users SET state=?, token=? WHERE user_id=?", (STATE_COMPLETE, token, user_id))
        database.execute('DELETE FROM educations WHERE user_id=?', (user_id, ))

        for i in res['data']['items']:
            for j in i['educations']:

                database.execute(
                    'INSERT INTO educations (education_id, user_id, firstname, lastname, school, class) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (j['education_id'], user_id, i['firstname'], i['surname'], j['institution_name'], j['group_name'])
                )
                database.commit()
        return

    bot.send_message(user_id, "Токен некорректный. Попробуй заново")
    return


@bot.message_handler(commands=["time"])
def set_time(message: telebot.types.Message):
    user_id = message.chat.id
    user = get_user(user_id)

    if user is None:
        bot.send_message(user_id, u"Сначала используй команду /start")
        return

    if user['state'] not in [STATE_COMPLETE]:
        bot.send_message(user_id, 'Сначала заверши настройку бота')
        return

    try:
        weekdays = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

        words = message.text.split(" ")
        time_send = words[-1]
        weekday = weekdays[words[-2]]

        if time_send != "25:00":
            datetime.datetime.strptime(time_send, "%H:%M")
            database.execute("UPDATE schedules SET time=? WHERE user_id=? AND day=?", (time_send, user_id, weekday))
            database.commit()
            if weekday == 6:
                bot.send_message(
                    user_id,
                    "Отлично, поздраевляю, настройка окончена, теперь ты будешь получать домашнее задание в Telegram. "
                    "Если возникнут технические проблемы, то обращайся к моим создателям (@Fiatkin или @FJSAGS)"
                )
        else:
            database.execute("DELETE FROM schedules WHERE user_id=? AND day=?", (user_id, weekday))

        database.commit()

    except:
        bot.send_message(
            user_id,
            "Время указано в неверном формате, оно должно быть в HH:MM"
        )
    return


def get_lessons(date_from: datetime.date, date_to: datetime.date, token, education_id):
    params = {
        'p_datetime_from': f'{date_from.strftime("%d.%m.%Y")} 00:00:00',
        'p_datetime_to': f'{date_to.strftime("%d.%m.%Y")} 23:59:59',
        'p_page': 1,
        'p_educations[]': education_id,
    }
    lessons = []
    for i in range(5):
        req = requests.get(
            'https://dnevnik2.petersburgedu.ru/api/journal/lesson/list-by-education',
            params=params,
            headers={
                'x-jwt-token': token
            }
        )
        req.raise_for_status()
        res = req.json()
        lessons = lessons + res['data']['items']
        if res['data']['current'] >= res['data']['next']:
            break
        params['p_page'] = res['data']['next']
    return lessons


def get_schedule(schedule_date: datetime.date, token, education_id):
    params = {
        'p_datetime_from': f'{schedule_date.strftime("%d.%m.%Y")} 00:00:00',
        'p_datetime_to': f'{schedule_date.strftime("%d.%m.%Y")} 23:59:59',
        'p_page': 1,
        'p_educations[]': education_id,
    }
    lessons = []
    for i in range(5):
        req = requests.get(
            'https://dnevnik2.petersburgedu.ru/api/journal/schedule/list-by-education',
            params=params,
            headers={
                'x-jwt-token': token
            }
        )
        req.raise_for_status()
        res = req.json()
        lessons = lessons + res['data']['items']
        if res['data']['current'] >= res['data']['next']:
            break
        params['p_page'] = res['data']['next']
    return lessons


def make_homework(lessons: list) -> dict:
    homework = {}
    time_task = {}

    for elem in lessons:
        subject_name = elem['subject_name']
        tasks = []
        date = datetime.datetime.strptime(elem['datetime_from'], '%d.%m.%Y %H:%M:%S').date()
        for i in elem['tasks']:
            tasks.append(i)

        if homework.get(subject_name) is None:
            time_task.update({subject_name: date})
            homework.update({subject_name: tasks})
        else:
            if date > time_task[subject_name]:
                time_task[subject_name] = date
                homework[subject_name].clear()
                homework.update({subject_name: tasks})
            elif date == time_task[subject_name]:
                homework[subject_name] = homework[subject_name] + tasks
    return homework


def get_homework(schedule: list, lessons : list) -> dict:
    homework = make_homework(lessons)

    tomorrow = set()
    for element in schedule:
        tomorrow.add(element['subject_name'])

    final_homework = {}

    for subject_name in tomorrow:
        tasks = homework.get(subject_name, [])
        for task in tasks:
            files = []
            for file in task.get('files', []):
                url = f'https://dnevnik2.petersburgedu.ru/api/filekit/file/download?p_uuid={file["uuid"]}'
                res = requests.get(url)
                res.raise_for_status()
                files.append((file['file_name'], res.content, file.get('file_type')))
            task['files'] = files

            if final_homework.get(subject_name) is None:
                final_homework.update({subject_name: [task]})
            else:
                final_homework[subject_name] += [task]

    return final_homework


def send_homework_report(subjects, chat_id, firstname, lastname):
    text = f'Отчет для {lastname} {firstname}:\n\n'
    for subject_name, tasks in subjects.items():
        text += (subject_name + ':\n')
        for task in tasks:
            if task.get('task_name') is not None:
                text += (task['task_name'] + ' ')
        text += '\n\n'
    bot.send_message(chat_id, text)

    for subject_name, tasks in subjects.items():
        for task in tasks:
            for document in task.get('files', []):
                bot.send_document(chat_id, document)


def send_homework(user_id):
    logging.info(f'Send homework for chat_id={user_id}')
    try:
        user = get_user(user_id)
        if user is None:
            bot.send_message(user_id, u"Сначала используй команду /start")
            return

        if user['state'] not in [STATE_COMPLETE]:
            bot.send_message(user_id, u"Сначала заверши настройку бота")
            return

        token = user['token']
        educations = database.execute('SELECT * FROM educations WHERE user_id=?', (user_id, )).fetchall()
        for education in educations:
            education_id = education['education_id']

            logging.info(f'Get homework for education #{education_id} ')
            try:
                lessons = get_lessons(
                    datetime.date.today() - datetime.timedelta(days=31), datetime.date.today(), token,
                    education['education_id']
                )

                schedule = []
                for day in range(1, 14):
                    schedule = get_schedule(
                        datetime.date.today() + datetime.timedelta(days=day), token, education['education_id']
                    )
                    if len(schedule) > 0:
                        break

                tasks = get_homework(schedule, lessons)
                send_homework_report(tasks, user_id, education['firstname'], education['lastname'])

                logging.info(f'{len(tasks)} total homeworks sent for #{education_id}')
            except:
                logging.exception('Error while get homework')
                bot.send_message(user_id, u'Произошла ошибка, напишите @Fiatikin')
    except:
        logging.exception('Error in send_homework')
    return


@bot.message_handler(commands=['homework'])
def send_func(message: telebot.types.Message):
    send_homework(message.chat.id)


def send_on_time():
    weekday = datetime.date.weekday(datetime.date.today())
    time = datetime.datetime.time(datetime.datetime.now()).strftime("%H:%M")
    res = database.execute('SELECT user_id FROM schedules WHERE day=? AND time=?', (weekday, time))

    users = res.fetchall()
    for user in users:
        send_homework(user["user_id"])

    return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', default=False, action='store_true')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO)
    last_update_id = -1

    init_database()
    logging.info("Bot started work")
    while True:
        updates = bot.get_updates(offset=last_update_id)
        for i in updates:
            last_update_id = max(i.update_id + 1, last_update_id)

        bot.process_new_updates(updates)
        send_on_time()


if __name__ == '__main__':
    main()
