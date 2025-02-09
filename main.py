import os
import requests
from datetime import datetime, date, timedelta
import time
import logging
import argparse
import schedule


token = os.environ.get('API_TOKEN')
education_id = int(os.environ.get('EDUCATION_ID'))
bot_token = os.environ.get('BOT_TOKEN')
chat_id = os.environ.get('CHAT_ID')


def get_lessons(date_from: date, date_to: date):
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


def get_schedule(schedule_date: date):
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


def get_homework(lessons):
    homework = {}
    time_task = {}

    for elem in lessons:
        subject_name = elem['subject_name']
        tasks = []
        date = datetime.strptime(elem['datetime_from'], '%d.%m.%Y %H:%M:%S').date()
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


def get_t_schedule(schedule, homework):
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


def bot_job():
    logging.info('Started bot job')
    homework = {}
    try:
        if date.weekday(date.today()) == 4:
            delta_days = 3
        else:
            delta_days = 1
        lessons = get_lessons(date.today() - timedelta(days=delta_days), date.today())
        schedule = get_schedule(date.today() + timedelta(days=delta_days))
    except:
        logging.exception('Error from petersburgedu API')
        send_text(chat_id, u'Ahtung, Ahtung! Shit happens... Зовите санитаров(@Fiatikin или @FJSAGS)')
        return

    homework = get_homework(lessons)
    final_tasks = get_t_schedule(schedule, homework)
    if len(final_tasks) > 0 and date.weekday(date.today()) != 6:
        send_homework(final_tasks, chat_id)
    logging.info(f'{len(final_tasks)} total homeworks sended')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', default="schedule", choices=['schedule', 'run'])
    parser.add_argument('-v', default=False, action='store_true')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO)

    if args.action == 'run':
        bot_job()
        return

    schedule.every().day.at("16:00", "Europe/Moscow").do(bot_job)
    logging.info('Scheduler started')
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == '__main__':
    main()
