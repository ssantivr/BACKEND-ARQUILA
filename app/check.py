import smtplib
import sys

from app.ai import get_assistant
from app.env import ENV_FILE, load_env_file
from app.errors import AIUnavailableError, NotConfiguredError
from app.mailer import ConsoleMailer, get_mailer

ASSISTANT_SYSTEM = "Responde en español con una sola frase corta."
ASSISTANT_QUESTION = "Saluda al equipo de ARQUILA."
MAIL_SUBJECT = "ARQUILA: prueba de correo"
MAIL_BODY = "Si recibes este mensaje, el correo de ARQUILA está bien configurado."


def check_assistant() -> tuple[bool, str]:
    try:
        reply = get_assistant().reply(
            ASSISTANT_SYSTEM, [{"role": "user", "content": ASSISTANT_QUESTION}]
        )
    except AIUnavailableError as error:
        return False, str(error)

    return True, reply


def check_mailer(recipient: str) -> tuple[bool, str]:
    try:
        mailer = get_mailer()
    except NotConfiguredError:
        return False, "Mail is not configured: set SMTP_HOST"

    if isinstance(mailer, ConsoleMailer):
        return False, "Mail is not configured: set SMTP_HOST in .env"

    try:
        mailer.send(recipient, MAIL_SUBJECT, MAIL_BODY)
    except (smtplib.SMTPException, OSError) as error:
        return False, f"Could not send the message: {error}"

    return True, f"Test message sent to {recipient}"


def main() -> None:
    load_env_file(ENV_FILE)

    results = [("AI assistant", check_assistant())]

    if len(sys.argv) > 1:
        results.append(("Mail", check_mailer(sys.argv[1])))
    else:
        print("Mail: skipped, pass a recipient address to test it")

    for name, (passed, detail) in results:
        print(f"{name}: {'OK' if passed else 'FAILED'} - {detail}")

    if not all(passed for _, (passed, _) in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
