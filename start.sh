#!/bin/bash
# Запуск ABCENTRUM Outreach Platform
cd "$(dirname "$0")"
echo "Запускаю ABCENTRUM Outreach Platform..."
echo "Адрес: http://127.0.0.1:5050"
echo "Логин: admin | Пароль: admin"
echo "Нажмите Ctrl+C для остановки"
echo "---"
python3 app.py
