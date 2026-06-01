"""
Email validation via MX-record lookup.
Не требует внешних API — работает через DNS.
"""
import socket
import re

# Известные валидные домены — не проверяем через DNS (быстрее)
KNOWN_VALID = {
    'gmail.com', 'googlemail.com',
    'yandex.ru', 'ya.ru', 'yandex.com',
    'mail.ru', 'bk.ru', 'list.ru', 'inbox.ru',
    'outlook.com', 'hotmail.com', 'live.com', 'live.ru', 'msn.com',
    'yahoo.com', 'yahoo.co.uk',
    'rambler.ru', 'lenta.ru', 'autorambler.ru', 'myrambler.ru',
    'icloud.com', 'me.com', 'mac.com',
    'protonmail.com', 'proton.me',
}

# Заведомо мёртвые / сомнительные домены
KNOWN_INVALID = {
    'example.com', 'example.ru', 'test.com', 'test.ru',
    'localhost', 'localhost.localdomain', 'invalid.com',
}

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


def _check_mx_dns(domain: str, timeout: float = 4.0) -> bool:
    """
    Проверяет наличие MX или A-записи домена через системный DNS.
    Returns True если домен резолвится (есть почтовый сервер), False иначе.
    """
    try:
        # Пробуем dnspython если установлен (точнее)
        import dns.resolver
        try:
            dns.resolver.resolve(domain, 'MX', lifetime=timeout)
            return True
        except dns.resolver.NoAnswer:
            # Нет MX — проверяем A-запись (некоторые серверы принимают на A)
            try:
                dns.resolver.resolve(domain, 'A', lifetime=timeout)
                return True
            except Exception:
                return False
        except Exception:
            return False
    except ImportError:
        pass

    # Fallback: getaddrinfo через socket
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        socket.getaddrinfo(domain, 25)
        return True
    except (socket.gaierror, OSError):
        return False
    finally:
        socket.setdefaulttimeout(old_timeout)


def validate_email(email: str) -> str:
    """
    Возвращает статус: 'valid' | 'invalid' | 'unknown'
    - valid:   адрес корректен и домен резолвится
    - invalid: формат неверен или домен недоступен
    - unknown: не удалось проверить (таймаут, сетевая ошибка)
    """
    if not email or not isinstance(email, str):
        return 'invalid'

    email = email.strip().lower()

    # Проверка формата
    if not _EMAIL_RE.match(email):
        return 'invalid'

    domain = email.split('@')[1]

    # Известные домены — без DNS-запроса
    if domain in KNOWN_VALID:
        return 'valid'
    if domain in KNOWN_INVALID:
        return 'invalid'

    # DNS проверка
    try:
        result = _check_mx_dns(domain)
        return 'valid' if result else 'invalid'
    except Exception:
        return 'unknown'


def validate_emails_batch(emails: list[str], progress_cb=None) -> dict[str, str]:
    """
    Batch-проверка списка адресов.
    progress_cb(done, total) — опциональный коллбэк прогресса.
    Возвращает {email: status}.
    """
    results = {}
    total = len(emails)
    # Кэш доменов — один домен проверяем один раз
    domain_cache: dict[str, bool] = {}

    for i, email in enumerate(emails):
        if not email:
            results[email] = 'invalid'
            continue

        email = email.strip().lower()
        if not _EMAIL_RE.match(email):
            results[email] = 'invalid'
        else:
            domain = email.split('@')[1]
            if domain in KNOWN_VALID:
                results[email] = 'valid'
            elif domain in KNOWN_INVALID:
                results[email] = 'invalid'
            elif domain in domain_cache:
                results[email] = 'valid' if domain_cache[domain] else 'invalid'
            else:
                try:
                    ok = _check_mx_dns(domain, timeout=3.0)
                    domain_cache[domain] = ok
                    results[email] = 'valid' if ok else 'invalid'
                except Exception:
                    results[email] = 'unknown'

        if progress_cb and (i + 1) % 10 == 0:
            progress_cb(i + 1, total)

    return results
