"""\
Contains a utility method to send an e-mail based on a Django template.
"""

from django.template import Context, loader
from django.core.mail import EmailMessage
from django.conf import settings

def send_email(request, context, template_name, cls=None, to_email=None):

    if to_email is not None:
        pass
    elif cls and hasattr(cls.conf, 'to_email'):
        to_email = cls.conf.to_email
    else:
        to_email = ('%s <%s>' % admin for admin in settings.MANAGERS)

    if cls and hasattr(cls.conf, 'from_email'):
        from_email = cls.conf.from_email
    else:
        from_email = settings.DEFAULT_FROM_EMAIL

    email_context = Context({
        'session_key': request.session.session_key,
        'devid': request.device.devid,
        'ua': request.META['HTTP_USER_AGENT'],
        'lon': request.session.get('geolocation:location', (None, None))[0],
        'lat': request.session.get('geolocation:location', (None, None))[1],
        'from_email': from_email,
        'host': request.META.get('HTTP_HOST'),
        'to_email': to_email,
        'request': request,
    })
    email_context.update(context)

    template = loader.get_template(template_name)
    email = template.render(email_context)

    headers, last_header = {}, None
    headers_section, body = email.split('\n\n', 1)
    for header in headers_section.split('\n'):
        if header.startswith(' '):
            headers[last_header] += ' ' + header.strip()
        else:
            key, value = header.split(': ', 1)
            headers[key] = value
            last_header = key

    subject = headers.pop('Subject', '[no subject]')
    from_email = headers.pop('from_email', from_email)
    if 'to_email' in headers:
        to_email = (e.strip() for e in headers.pop('to_email').split(';'))

    email = EmailMessage(
        subject = subject,
        body = body,
        from_email = from_email,
        to = to_email,
        headers = headers,
    )

    print "E-mail", email
    print "      ", email.recipients()
    print email.send()