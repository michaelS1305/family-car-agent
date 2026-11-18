"""Contact-only configuration and SMTP delivery. Never retry an uncertain send."""
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import SMTP
import os
import re
import smtplib
import ssl
from contact_diagnostics import report


def valid_email(value):
    return (isinstance(value, str) and len(value) <= 254
            and re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", value) is not None)


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)
    sender: str = field(repr=False)
    recipient: str = field(repr=False)
    timeout: float
    turnstile_secret: str = field(repr=False)
    hostname: str = ''

    @classmethod
    def load(cls):
        if os.getenv('CONTACT_ENABLED', '').lower() != 'true':
            return None
        try:
            result = cls(os.environ['CONTACT_SMTP_HOST'], int(os.environ['CONTACT_SMTP_PORT']),
                         os.environ['CONTACT_SMTP_USERNAME'], os.environ['CONTACT_SMTP_PASSWORD'],
                         os.environ['CONTACT_FROM_EMAIL'], os.environ['CONTACT_TO_EMAIL'],
                         float(os.getenv('CONTACT_SMTP_TIMEOUT', '10')),
                         os.environ['CONTACT_TURNSTILE_SECRET'],
                         os.getenv('CONTACT_TURNSTILE_HOSTNAME', ''))
            if (result.port not in (465, 587) or not 1 <= result.timeout <= 30
                    or not result.username or not result.password or not result.turnstile_secret
                    or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', result.host)
                    or not valid_email(result.sender) or not valid_email(result.recipient)):
                return None
            return result
        except (KeyError, ValueError):
            return None


def deliver(config, fields, attachments):
    message = EmailMessage(policy=SMTP)
    message['From'] = config.sender
    message['To'] = config.recipient
    message['Reply-To'] = fields['email']
    message['Subject'] = 'Family Car Agent — ' + fields['subject']
    message.set_content('\n'.join((fields['name'], fields['email'], fields['subject'], fields['description'])))
    for filename, mime, content in attachments:
        major, minor = mime.split('/')
        message.add_attachment(content, maintype=major, subtype=minor, filename=filename)
    wire = message.as_bytes()
    if len(wire) > 14_000_000:
        return 'message_too_large'
    client = None
    sending = False
    stage = 'smtp_connect'
    try:
        context = ssl.create_default_context()
        if config.port == 465:
            client = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=context)
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        stage = 'smtp_auth'
        client.login(config.username, config.password)
        sending = True
        stage = 'smtp_send'
        refused = client.sendmail(config.sender, [config.recipient], wire)
        if refused:
            report('smtp_send', 'smtp_rejected')
        return 'smtp_unavailable' if refused else 'accepted'
    except (smtplib.SMTPResponseException, smtplib.SMTPRecipientsRefused):
        report(stage, {'smtp_connect': 'smtp_connect_failed', 'smtp_auth': 'smtp_auth_failed', 'smtp_send': 'smtp_rejected'}[stage])
        # An explicit rejection is distinguishable from a lost response.
        return 'smtp_unavailable'
    except (OSError, smtplib.SMTPException):
        report('smtp_send' if sending else 'smtp_connect', 'delivery_uncertain' if sending else 'smtp_connect_failed')
        return 'delivery_uncertain' if sending else 'smtp_unavailable'
    except Exception:
        report('smtp_send' if sending else 'request', 'delivery_uncertain' if sending else 'unexpected_failure')
        # Unexpected transport errors after send begins cannot establish rejection.
        return 'delivery_uncertain' if sending else 'smtp_unavailable'
    finally:
        if client is not None:
            try:
                client.close()  # QUIT failure must not undo confirmed acceptance.
            except (OSError, smtplib.SMTPException):
                pass
