import imaplib
import email
import os

def check_emails(host, user, password, upload_dir):
    try:
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select('inbox')

        # Chercher les messages non lus avec pièces jointes
        status, messages = mail.search(None, 'UNSEEN')
        for num in messages[0].split():
            status, data = mail.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(data[0][1])

            for part in msg.walk():
                if part.get_content_maintype() == 'multipart': continue
                if part.get('Content-Disposition') is None: continue

                filename = part.get_filename()
                if filename:
                    filepath = os.path.join(upload_dir, filename)
                    with open(filepath, 'wb') as f:
                        f.write(part.get_payload(decode=True))
                    print(f"Email attachment saved: {filename}")
        mail.logout()
    except Exception as e:
        print(f"Email monitor error: {e}")
