import csv
import datetime as dt
import logging
import os
import re
import sys
import time
from logging.config import fileConfig
from pathlib import Path
from typing import List, Tuple

import requests
import yadisk
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError
from telegram.message import Message

load_dotenv()

fileConfig(fname="log_config.conf", disable_existing_loggers=False)

logger = logging.getLogger(__name__)


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_DIR = Path(__file__).resolve()

'''
def send_message(bot: telegram.bot, message: str) -> telegram.message.Message:
    """Отправка сообщения в телеграм через бота."""
    try:
        sent_message = bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except TelegramError as error:
        logger.exception(f"Ошибка отправки сообщения через бота: {error}")
    else:
        logger.info(f"Бот отправил сообщение с текстом: {message}")
        return sent_message



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


def get_file_from_yadisk(bot: Bot, token: str, path: str):
    disk = yadisk.YaDisk(token=token)
    file_name = "temp.csv"
    if not disk.check_token():
        # add later: generate new token
        error_message = "Invalid yadisk token"
        logger.error(error_message)
        bot._send_message(error_message)
        sys.exit(1)
    try:
        file = disk.download(src_path=path, path_or_file=BASE_DIR / file_name)
    except Exception as e:
        error_message = f"File download failure: {e}"
        logger.error(error_message)
        bot._send_message(error_message)
        sys.exit(1)
    return file_name


TIME_URL = "http://worldtimeapi.org/api/timezone/Europe/Moscow"
DATE_FORMAT = "%Y-%m-%d"
FILE_PATH = "/home/sammi/Dev/bday_telebot/b_days.csv"
DAY_KEY = "Дата"
MONTH_KEY = "месяц"


class BirthdayBotMixin:
    TIME_URL = "http://worldtimeapi.org/api/timezone/Europe/Moscow"
    # FILE_PATH = "/home/sammi/Dev/bday_telebot/b_days.csv"
    DAY_KEY = "Дата"
    MONTH_KEY = "месяц"
    YEAR_KEY = "год"
    NAME_KEY = "ФИО"

    def get_congrat_people(self, file_path: str) -> Tuple[List[dict]]:
        """Get names of people to be congratulated.

        Iterate through rows of a csv file and populate two lists:
        1. People to be congratulated today.
        2. People to be congratulated in three days.

        When something goes wrong, send a message via telegram bot and exit."""

        today_notifications = []
        three_days_notifications = []
        # today = dt.date.today()
        today = self._get_current_date()
        error_message = "Could not parse input file. Wrong format. Need action"

        with open(file_path) as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                day = row[self.DAY_KEY]
                month = self._get_month(row[self.MONTH_KEY].lower())
                if not day.isdecimal() or not isinstance(month, int):
                    continue
                try:
                    date = dt.date(year=today.year, month=month, day=int(day))
                except TypeError as e:
                    logger.error(error_message)
                    self._send_message(error_message)
                    sys.exit(1)
                if date == today:
                    today_notifications.append(
                        self._get_formatted_bday_message(row, today)
                    )
                elif date - today == dt.timedelta(days=2):
                    three_days_notifications.append(
                        self._get_formatted_bday_message(row, today)
                    )
        return today_notifications, three_days_notifications

    def _get_current_date(self) -> dt.date:
        today = dt.date.today()
        try:
            resp = requests.get(self.TIME_URL).json()
        except Exception:
            logger.warning(
                "Не удалось получить ответ от стороннего API. "
                "Текущая дата будет задана операционной системой."
            )
            resp = {}
            # return dt.datetime.today()
        if date := resp.get("datetime"):
            # date = self._truncate_datetime(date)
            # today = dt.date.fromisoformat(date)
            today = self._truncate_datetime(date)
        return today
        # return dt.datetime.fromisoformat(date)

    @staticmethod
    def _truncate_datetime(dt_string: str) -> dt.date:
        """Target format: `2022-12-15T00:03:42.431581+03:00`"""
        regex = "[0-9]{4}-[0-9]{2}-[0-9]{2}T"
        if not re.match(regex, dt_string):
            logger.error(
                "datetime string does not conform to specified format"
            )
            sys.exit(1)
        date, _ = dt_string.split("T")
        return dt.date.fromisoformat(date)

    def _get_month(self, month: str) -> int:
        """Return an integer mapping to a month."""
        return {
            "январь": 1,
            "февраль": 2,
            "март": 3,
            "апрель": 4,
            "май": 5,
            "июнь": 6,
            "июль": 7,
            "август": 8,
            "сентябрь": 9,
            "октябрь": 10,
            "ноябрь": 11,
            "декабрь": 12,
        }.get(month)

    def _send_message(self, message: str) -> Message:
        """Отправка сообщения в телеграм через бота."""
        try:
            sent_message = self.send_message(
                chat_id=TELEGRAM_CHAT_ID, text=message
            )
        except TelegramError as error:
            logger.exception(f"Ошибка отправки сообщения через бота: {error}")
        else:
            logger.info(f"Бот отправил сообщение с текстом: {message}")
            return sent_message

    def _get_formatted_bday_message(
        self, data: dict, today: dt.date = None
    ) -> str:
        """Return a formatted info message."""
        today = today or dt.date.today()
        age = "неизвестно"
        name = data.get(self.NAME_KEY, "Неизвестный партнер")
        day = data.get(self.DAY_KEY)
        month = data.get(self.MONTH_KEY)
        if year := data.get(self.YEAR_KEY):
            if year.isdecimal():
                age = today.year - int(year)
        return "\n" + f"/* {name}, {month}-{day}, возраст: {age} */"


class BirthdayBot(Bot, BirthdayBotMixin):
    pass


# scheduler = BackgroundScheduler()
# @scheduler.scheduled_job(IntervalTrigger(seconds=5))
def main():
    bot = BirthdayBot(TELEGRAM_TOKEN)
    today_notifications, three_days_notifications = bot.get_congrat_people(
        FILE_PATH
    )
    if today_notifications:
        bot._send_message(f"Дни рождения сегодня: {today_notifications}")
    if three_days_notifications:
        three_days_notifications = "\n".join(three_days_notifications)
        # three_days_notifications = "\n" + three_days_notifications
        bot._send_message(
            f"Дни рождения через 3 дня: {three_days_notifications}"
        )


# scheduler.start()
cron = BackgroundScheduler()
cron.start()
cron.add_job(main, "interval", seconds=5)
while True:
    time.sleep(20)
# if __name__ == '__main__':
#    #scheduler = BackgroundScheduler()
#    #scheduler.start()
#    #scheduler.add_job(main, 'interval', seconds=1)
#    print('Press Ctrl+{0} to exit'.format('Break' if os.name == 'nt' else 'C'))
#    #get_congrat_people('/home/sammi/Dev/bday_telebot/b_days.csv')
#    #main()

"""
token='y0_AgAAAAAQgIL4AAj5pAAAAADZFT62L4mOKRpsSS-2q3bU_UhqPi8K68c'

Порядок работы скрипта.
1. Создать экземпляр диска с токеном
2. Проверить токен.
3. Получить файл с диска.
4. Обработать файл.
5. Отправить результаты в ТГ.

"""
