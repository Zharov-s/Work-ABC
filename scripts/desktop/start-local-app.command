#!/bin/bash
cd "$(dirname "$0")/../.."
echo "Запуск Work-ABC..."
echo "Адрес: http://127.0.0.1:5050"
echo "Для остановки нажмите Ctrl+C"
python3 app.py
