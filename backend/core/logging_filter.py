"""
core/logging_filter.py — Masque les valeurs sensibles dans les logs uvicorn.
"""
import re
import logging

SENSITIVE_KEYS = {"email_password", "password", "llm_api_key", "token", "secret"}


class SensitiveFilter(logging.Filter):
    _pattern = re.compile(
        r'((?:' + '|'.join(SENSITIVE_KEYS) + r')=)[^&\s"\']+ ',
        re.IGNORECASE
    )

    def _mask(self, text: str) -> str:
        return self._pattern.sub(r'\1*** ', text)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._mask(str(record.msg))
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    self._mask(a) if isinstance(a, str) else a
                    for a in record.args
                )
            elif isinstance(record.args, str):
                record.args = self._mask(record.args)
        return True


def apply_sensitive_filter():
    """Applique le filtre à tous les loggers uvicorn/fastapi."""
    for name in ("uvicorn.access", "uvicorn", "uvicorn.error", "fastapi"):
        logging.getLogger(name).addFilter(SensitiveFilter())
