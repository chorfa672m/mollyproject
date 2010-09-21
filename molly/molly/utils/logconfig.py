import logging, inspect, traceback, hashlib, pprint, datetime

from django.http import HttpRequest
from django.conf import settings

from . import email

class EmailHandler(logging.Handler):
    _NOT_EXTRA = (
        'args', 'created', 'exc_info', 'exc_text', 'filename', 'funcName',
        'getMessage', 'levelname', 'levelno', 'lineno', 'msg', 'message',
        'module', 'msecs', 'name', 'pathname', 'process', 'processName',
        'relativeCreated', 'thread', 'threadName'
    )
    
    def emit(self, record):
        if record.name == 'molly.stats.requests':
            return

        for frame in inspect.getouterframes(inspect.currentframe()):
            request = frame[0].f_locals.get('request', None)
            if isinstance(request, HttpRequest):
                break

        extra = {}
        for key in dir(record):
            if key.startswith('_') or key in self._NOT_EXTRA:
                continue
            extra[key] = '    ' + pprint.pformat(getattr(record, key), width=75).replace('\n', '\n    ')

        context = {
            'record': record,
            'level_name': logging._levelNames.get(record.levelno, "L%s" % record.levelno),
            'level_stars': '*' * (record.levelno // 10),
            'priority': 'urgent' if record.levelno >= 40 else 'normal',
            'extra': extra,
            'created': datetime.datetime.fromtimestamp(record.created)
        }

        # hash is a hash of some key details of the log record, specifically
        # the log level, the (unformatted) message, and where it was emitted.
        # If there is an attached exception we take the locations of the first
        # two elements of the traceback.
        hash = hashlib.sha1()
        hash.update('%d' % record.levelno)
        hash.update(record.msg)
        hash.update('%d%s' % (record.lineno, record.pathname))


        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            hash.update('%s%s' % (exc_type.__module__, exc_type.__name__))
            context['traceback'] = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            for i in range(2):
                hash.update('%d%s' % (exc_traceback.tb_lineno, exc_traceback.tb_frame.f_code.co_filename))
                exc_traceback = exc_traceback.tb_next

        context['hash'] = hash.hexdigest()[:8]

        email.send_email(request, context, 'utils/log_record.eml')

def configure_logging(conf):
    if settings.DEBUG:
        return

    logger = logging.getLogger()
    
    handler = EmailHandler()
    handler.setLevel(logging.WARNING)
    logger.addHandler(handler)