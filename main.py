import os
import requests
from datetime import datetime, date, timedelta
import time
import logging
import argparse
import schedule


token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VySWQiOiI1YzVjZmUwZDhhY2I1MDYwY2E0Y2FlYTciLCJsYXN0QWN0aXZpdHkiOjE3MzkwOTg3NDYsInR5cGUiOiJlbWFpbCIsImxhc3RJZCI6bnVsbH0.iSrQkHESXso6YbTUb4iwyE-SE-J54nS_XzFj0WVPIt0" # os.environ.get('API_TOKEN')
education_id = 243850 # int(os.environ.get('EDUCATION_ID'))
bot_token = "7638168367:AAEuB3Sgs62Sb33XKTY5cwTmYfiyeqaYM2w" # os.environ.get('BOT_TOKEN')
chat_id = "1267600695" # os.environ.get('CHAT_ID')


def get_lessons(date_from: date, date_to: date):
    params = {
        'p_datetime_from': f'{date_from.strftime("%d.%m.%Y")} 00:00:00',
        'p_datetime_to': f'{date_to.strftime("%d.%m.%Y")} 23:59:59',
        'p_page': 1,
        'p_educations[]': education_id,
    }
    lessons = []
    log.debug("Requesting lessons from API...")
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
        log.debug(f"{i}/5")
        lessons = lessons + res['data']['items']
        if res['data']['current'] >= res['data']['next']:
            break
        params['p_page'] = res['data']['next']
    return lessons


def get_schedule(schedule_date: date):
    params = {
        'p_datetime_from': f'{schedule_date.strftime("%d.%m.%Y")} 00:00:00',
        'p_datetime_to': f'{schedule_date.strftime("%d.%m.%Y")} 23:59:59',
        'p_page': 1,
        'p_educations[]': education_id,
    }
    lessons = []
    log.debug("Requesting schedule from API...")
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
        log.debug(f"{i}/5")
        lessons = lessons + res['data']['items']
        if res['data']['current'] >= res['data']['next']:
            break
        params['p_page'] = res['data']['next']
    return lessons


def get_homework(lessons):
    homework = {}
    time_task = {}

    for elem in lessons:
        subject_name = elem['subject_name']
        log.debug(f"Working on {subject_name}")
        tasks = []
        date = datetime.strptime(elem['datetime_from'], '%d.%m.%Y %H:%M:%S').date()
        for i in elem['tasks']:
            tasks.append(i)

        if homework.get(subject_name) is None:
            log.info("Lesson name is None... Skip")
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


def get_t_schedule(schedule, homework):
    log.debug("Getting rid of tasks that aren't for tomorrow")
    tomorrow = set()
    for element in schedule:
        tomorrow.add(element['subject_name'])

    final_homework = {}

    for subject_name in tomorrow:
        tasks = homework.get(subject_name, [])
        for task in tasks:
            log.debug("Looking for files...")
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


def get_updates(offset):
    res = requests.get(f"https://api.telegram.org/bot{bot_token}/getUpdates")  # , {'offset': offset, "timeout": 60})
    res.raise_for_status()
    return res.json()


def send_text(chat_id, text):
    message = {
        'chat_id': chat_id,
        'text': text
    }
    res = requests.get(f"https://api.telegram.org/bot{bot_token}/sendMessage", data=message)
    logging.debug(res.text)


def send_document(chat_id, document):
    message = {
        'chat_id': chat_id,
    }
    res = requests.get(f"https://api.telegram.org/bot{bot_token}/sendDocument", data=message,
                       files={'document': document})
    logging.debug(res.text)


def send_homework(subjects, chat_id):
    text = 'Отчет:\n\n'
    for subject_name, tasks in subjects.items():
        text += (subject_name + ':\n')
        for task in tasks:
            if task.get('task_name') is not None:
                text += (task['task_name'] + ' ')
        text += '\n\n'
    send_text(chat_id, text)

    for subject_name, tasks in subjects.items():
        for task in tasks:
            for document in task.get('files', []):
                send_document(chat_id, document)


def bot_job(is_single_run = False):
    if is_single_run:
        log.debug("Doing a single run")
    else:
        log.info("Doing a scheduled run")
    try:
        if date.weekday(date.today()) == 4:
            log.debug("Today is Friday, will get homework for Monday.")
            delta_days = 3
        else:
            log.debug("Today is not Friday, will get homework for tomorrow")
            delta_days = 1
        log.debug("Getting lessons...")
        lessons = get_lessons(date.today() - timedelta(days=delta_days), date.today())

        log.debug(f"Got {len(lessons)} lessons! Getting schedule...")
        schedule = get_schedule(date.today() + timedelta(days=delta_days))

        log.info("Got schedule! No exceptions for now")
    except Exception as err:
        log.error("Don't worry! Please let us know via github!")
        log.exception(err)
        send_text(chat_id, u'Ahtung, Ahtung! Shit happens... Зовите санитаров: @FJSAGS, @Fiatikin')
        exit(1)

    log.debug("Playing with homework...")
    homework = get_homework(lessons)
    final_tasks = get_t_schedule(schedule, homework)
    log.info("Finalized your homework. Sending...")
    if len(final_tasks) > 0 and (date.weekday(date.today()) < 5 or is_single_run):
        send_homework(final_tasks, chat_id)
        log.info(f'{len(final_tasks)}/{len(homework)} total homeworks sent.')
        if is_single_run:
            log.info("Done! Exiting...")
        else:
            log.info("Done! Next run will occur in 24 hours.")
    else:
        log.warning("No tasks for the next day found! Skipping...")


def main(action = schedule):
    log.warning("Starting up...")

    if action == 'run':
        log.warning("Argument run detected! Bot will do a SINGLE run immediately, then close. Use 'schedule' to run continuously")
        bot_job(True)
        exit(0)
    schedule.every().day.at("16:00", "Europe/Moscow").do(bot_job)
    log.info('Scheduler started.')
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == '__main__':
    log = logging.getLogger("Bot")
    parser = argparse.ArgumentParser()
    parser.add_argument('action', default="schedule", choices=['schedule', 'run'])
    parser.add_argument('-v', default=False, action='store_true')
    args = parser.parse_args()
    if args.v:
        logging.basicConfig(level=logging.DEBUG)
        log.debug("Debug mode! More log messages will show up.")
    else:
        logging.basicConfig(level=logging.INFO)
        log.info("Normal mode. Use '-v' for debug.")
    main(args.action)
