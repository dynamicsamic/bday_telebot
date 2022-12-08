#!/home/sammi/.pyenv/shims/python

import logging
import logging.config
import os
import time
import datetime as dt
from typing import List, Tuple
import csv
import sys


import telegram
from dotenv import load_dotenv
from telegram.error import TelegramError



load_dotenv()

logging.config.fileConfig(
    fname='log_config.conf',
    disable_existing_loggers=False
)

logger = logging.getLogger(__name__)


PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')



HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


EXPECTED_HOMEWORK_KEYS = {
    'homework_name',
    'lesson_name',
    'date_updated',
    'id',
    'status',
    'reviewer_comment',
}


def send_message(bot: telegram.bot, message: str) -> telegram.message.Message:
    """Отправка сообщения в телеграм через бота."""
    try:
        sent_message = bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except TelegramError as error:
        logger.exception(f'Ошибка отправки сообщения через бота: {error}')
    else:
        logger.info(f'Бот отправил сообщение с текстом: {message}')
        return sent_message

'''
def get_api_answer(current_timestamp: int) -> dict:
    """
    Функция отправки запроса к API.
    Если статус-код полученного ответа = 200, функциия возвращает
    ответ от API в виде словаря.
    Если код ответа отличается, будет вызвано ислючение.
    """
    timestamp = current_timestamp or int(time.time())
    params = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
    except RequestException as error:
        logger.exception(
            f'Эндпоинт "{ENDPOINT}" недоступен по причине: {error}'
        )
    else:
        raise_if_not_200(response, ENDPOINT)
        return response.json()


def check_response(response: dict) -> list:
    """
    Проверяет полученный ответ от API.
    Вызывает исключение, если ответ от API:
      1. Пустой или не является словарем.
      2. Не содержит ключа "homeworks".
      3. Тип значения по ключу "homeworks" не список.
    При удачной проверке возвращает список домашних работ.
    """
    if not isinstance(response, dict):
        raise TypeError(
            f'Ожидаемый тип данных в ответе API: dict; '
            f'получен тип данных: {type(response).__name__}'
        )

    if len(response) == 0:
        raise EmptyResponseError('Получен пустой ответ от API.')

    homeworks = response.get('homeworks')
    if homeworks is None:
        raise ApiResponseKeyError('Ответ API не содержит ключ "homeworks".')

    if not isinstance(homeworks, list):
        raise ApiResponseTypeError(
            f'Значение по ключу "homeworks" должно иметь тип данных list; '
            f'получен тип данных: {type(homeworks).__name__}'
        )

    return homeworks


def parse_status(homework: dict) -> str:
    """
    Функция проверки одной домашней работы.
    Вызывает исключение, если словарь с домашней работой:
      1. Содержит непредвиденный статус работы.
      2. Содержит ключи, отличающиеся от ожидаемых.
    Возвращает строку (str) c информацией о статусе домашней работы
    для последующей передачи в качестве сообщения для бота.
    """
    recieved_hw_keys = set(homework)
    if recieved_hw_keys != EXPECTED_HOMEWORK_KEYS:
        missing_keys = EXPECTED_HOMEWORK_KEYS - recieved_hw_keys
        unexpected_keys = recieved_hw_keys - EXPECTED_HOMEWORK_KEYS
        raise KeyError(
            f'Ключи поступившей домашней работы отличаются от ожидаемых! '
            f'лишние ключи: {unexpected_keys or None}; '
            f'недостающие ключи: {missing_keys or None}'
        )

    if homework.get('status') not in HOMEWORK_VERDICTS:
        homework_status = homework.get('status')
        raise UnknownHomeworkStatusError(
            f'Получен неизвестный статус домашней работы: {homework_status}.'
        )

    homework_name = homework.get('homework_name')
    homework_status = homework.get('status')
    verdict = HOMEWORK_VERDICTS.get(homework_status)
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def check_tokens() -> bool:
    """Проверяет доступность переменных окружения."""
    return all((PRACTICUM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_TOKEN))


def main():  # noqa: C901
    """
    Основная логика работы программы.
      1. Проверить доступность переменных окружения.
      2. Инициализировать бота.
      3. Полчить ответ от API, из него получить список домашних работ.
      4. Если список домашних работ пуст, ОДИН РАЗ уведомить пользователя.
      5. Если работ одна и больше, пройтись циклом по всем работам и
         сохранить айдишники и статусы работ в словаре.
      6. Если айдишники или статусы меняются,
         КАЖДЫЙ РАЗ уведомлять об этом пользователя.
    """
    if not check_tokens():
        message = (
            'Ошибка доступности переменных окружения. '
            'Работа программы принудительно остановлена.'
        )
        logger.critical(message)
        raise TokenFailure(message)

    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    empty_hw_list_status = ''
    hw_statuses = {}
    error_message = ''
    current_timestamp = int(time.time())

    # Уведомления о неудачной отправке сообщения через бота
    # будут возникать в логах постоянно
    bot_sent_message = True

    while True:
        try:
            if not bot_sent_message:
                logger.error(
                    'Ошибка отправки сообщения!'
                    'Проверьте рабоспособность бота.'
                )

            response = get_api_answer(current_timestamp)
            homeworks = check_response(response)
            if len(homeworks) == 0:
                current_hw_status = 'Список домашних заданий пуст.'
                if current_hw_status != empty_hw_list_status:
                    empty_hw_list_status = current_hw_status
                    bot_sent_message = send_message(bot, empty_hw_list_status)
                else:
                    logger.info(
                        'Изменений в статусе домашних работ не происходило.'
                    )
            else:
                # создаем словарь для хранения айдишников работ и их статусов
                current_hw_statuses = {
                    homework['id']: parse_status(homework) for homework
                    in homeworks
                }

                # если полученные айдишники или статусы работ
                # не совпадают с ранее сохраненными, то
                # сохраняем новые айдишники или статусы и отправляет сообщение
                for hw_id in current_hw_statuses:
                    if (
                        hw_statuses.get(hw_id) != current_hw_statuses.get(
                            hw_id
                        )
                    ):
                        hw_statuses[hw_id] = current_hw_statuses[hw_id]
                        send_message(bot, hw_statuses[hw_id])
                    else:
                        logger.info(
                            'Изменений в статусе домашних работ '
                            'не происходило.'
                        )

            current_timestamp = int(time.time())
            time.sleep(RETRY_TIME)

        except (KeyError, TypeError, RequestException, TelegramError,
                HomeworkException) as error:
            message = f'Сбой в работе программы: {error}'
            logger.exception(message)
            if message != error_message:
                error_message = message
                send_message(bot, error_message)
            time.sleep(RETRY_TIME)

'''

FILE_PATH = '/home/sammi/Dev/bday_telebot/b_days.csv'
DAY_KEY = 'Дата'
MONTH_KEY = 'месяц'

def get_congrat_people(file_path: str, bot: telegram.Bot) -> Tuple[List[dict]]:
    '''Get names of people to be congratulated.

    Iterate through rows of a csv file and populate two lists:
    1. People to be congratulated today.
    2. People to be congratulated in three days.

    When something goes wrong, send a message via telegram bot and exit.'''

    today_notifications = []
    three_days_notifications = []
    today = dt.date.today()
    error_message = 'Could not parse input file. Wrong format. Need action'

    with open(file_path) as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            day = row[DAY_KEY]
            month = _get_month(row[MONTH_KEY].lower())
            if not day.isdecimal() or not isinstance(month, int):
                continue
            try:
                date = dt.date(year=today.year, month=month, day=int(day))
            except TypeError as e:
                logger.error(error_message)
                send_message(bot, error_message)
                sys.exit(1)
            if date == today:
                today_notifications.append(_get_formatted_bday_message(row))
            elif date - today == dt.timedelta(days=3):
                three_days_notifications.append(_get_formatted_bday_message(row))
    return today_notifications, three_days_notifications

def _get_month(month: str) -> int:
    '''Return an integer mapping to a month.'''
    return {
        'январь': 1,
        'февраль': 2,
        "март": 3,
        "апрель": 4,
        'май': 5,
        "июнь": 6,
        "июль": 7,
        "август": 8,
        "сентябрь": 9,
        "октябрь": 10,
        "ноябрь": 11,
        "декабрь": 12
    }.get(month)

def _get_formatted_bday_message(data: dict) -> str:
    '''Return a formatted info message.'''
    age = 'неизвестно'
    name = data.get('ФИО', 'Неизвестный партнер')
    if year := data.get('год'):
        if year.isdecimal():
            age = dt.date.today().year - int(year)
    return f'ФИО: {name}, возраст: {age}'



def main():
    bot = telegram.Bot(TELEGRAM_TOKEN)
    today_notifications, three_days_notifications = get_congrat_people(FILE_PATH, bot)
    send_message(bot, f'Дни рождения сегодня: {today_notifications}')
    send_message(bot, f'Дни рождения через 3 дня: {three_days_notifications}')



if __name__ == '__main__':
    #get_congrat_people('/home/sammi/Dev/bday_telebot/b_days.csv')
    main()
