import os
import csv
import re
import yaml
import smtplib
import shutil
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import logging
from datetime import datetime

HEADERS = ['lender_institution', 'borrower_institution', 'full_name', 'user_email', 'expiry_date', 'remaining_amount', 'active_loan_count']
CONFIGFILE = "config.yaml"
SCHOOLS_FILE = "schools.yaml"
OUTPUT_DIR = "SortedFiles"

INPUT_ENCODING = 'utf-16'
INPUT_DELIMITER = '\t'
OUTPUT_DELIMITER = '\t'


def setup_logger():
    log_dir = "Logs"
    os.makedirs(log_dir, exist_ok=True)

    log_filename = datetime.now().strftime("%Y-%m-%d_%H_%M.log")
    log_file_path = os.path.join(log_dir, log_filename)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return log_file_path


def load_config(configfile=CONFIGFILE):
    try:
        with open(configfile, 'r') as stream:
            return yaml.safe_load(stream)
    except FileNotFoundError:
        logging.error(f"Config file '{configfile}' not found")
        raise
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML from {configfile}: {e}")
        raise


def load_schools(schools_file=SCHOOLS_FILE):
    """Load schools config. Returns (lookup_dict, schools_list).

    lookup_dict maps every school name and alias to its output filename.
    schools_list is the raw list of school entries.
    """
    try:
        with open(schools_file, 'r') as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Schools file '{schools_file}' not found")
        raise
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML from {schools_file}: {e}")
        raise

    schools_list = data.get('schools', [])
    lookup = {}

    for school in schools_list:
        name = school['name']
        output_file = school['output_file']
        lookup[name] = output_file
        for alias in school.get('aliases', []):
            lookup[alias] = output_file

    logging.info(f"Loaded {len(schools_list)} schools ({len(lookup)} names/aliases)")
    return lookup, schools_list


def match(directory):
    """Find input files in al-* subdirectories."""
    matches = []
    pattern = re.compile(r"^al-")

    for root, dirnames, _ in os.walk(directory):
        for dirname in dirnames:
            if pattern.match(dirname):
                holdingdir = os.path.join(root, dirname)
                for root2, _, filenames in os.walk(holdingdir):
                    for filename in filenames:
                        filepath = os.path.join(root2, filename)
                        matches.append(filepath)

    logging.info(f"Found {len(matches)} input files in {directory}")
    return matches


def check_file_headers(matcheslist):
    """Validate file headers. Returns list of files with correct headers."""
    correctfiles = []

    for filename in matcheslist:
        ext = os.path.splitext(filename)[-1].lower()

        if ext not in ('.txt', '.csv'):
            logging.warning(f"Skipping {filename}: unsupported extension '{ext}'")
            continue

        try:
            with open(filename, encoding=INPUT_ENCODING) as f:
                reader = csv.reader(f, delimiter=INPUT_DELIMITER)
                headers = next(reader)

                if headers != HEADERS:
                    logging.warning(f"Header mismatch in {filename}: {headers}")
                else:
                    correctfiles.append(filename)
        except Exception as e:
            logging.error(f"Error reading {filename}: {e}")

    logging.info(f"{len(correctfiles)}/{len(matcheslist)} files passed header check")
    return correctfiles


def process_reports(school_lookup, config, output_dir=OUTPUT_DIR):
    """Read input files, split by borrowing school, sort by email, and write reports."""
    directorypath = config["scriptpath"]
    correctfiles = check_file_headers(match(directorypath))

    if not correctfiles:
        logging.warning("No valid input files found, nothing to process")
        return

    # Step 1: Read all input files and collect rows per school
    logging.info("Reading input files and splitting rows by borrowing school...")
    school_rows = {}
    error_rows = []

    for filename in correctfiles:
        logging.info(f"  Reading: {filename}")
        with open(filename, encoding=INPUT_ENCODING) as f:
            reader = csv.reader(f, delimiter=INPUT_DELIMITER)
            next(reader)  # skip header
            for row in reader:
                borrower = row[1].strip() if len(row) > 1 else ''

                if borrower and borrower in school_lookup:
                    school_rows.setdefault(school_lookup[borrower], []).append(row)
                elif borrower:
                    logging.warning(f"  Unknown borrower '{borrower}' in {os.path.basename(filename)}")
                    error_rows.append(row)
                else:
                    logging.warning(f"  Empty borrower in {os.path.basename(filename)}")
                    error_rows.append(row)

    total = sum(len(r) for r in school_rows.values())
    logging.info(f"Read {total} rows across {len(school_rows)} schools, {len(error_rows)} errors")

    # Step 2: Sort each school's rows by email and write to output directory
    logging.info(f"Sorting by email and writing reports to {output_dir}/...")
    os.makedirs(output_dir, exist_ok=True)

    for output_file, rows in school_rows.items():
        sorted_rows = sorted(rows, key=lambda row: row[3].lower() if len(row) > 3 else '')
        filepath = os.path.join(output_dir, output_file)
        with open(filepath, 'w', encoding='utf-8', newline='') as wf:
            writer = csv.writer(wf, delimiter=OUTPUT_DELIMITER)
            writer.writerow(HEADERS)
            writer.writerows(sorted_rows)

    if error_rows:
        with open(os.path.join(output_dir, 'errors.csv'), 'w', encoding='utf-8', newline='') as wf:
            csv.writer(wf, delimiter=OUTPUT_DELIMITER).writerows(error_rows)

    logging.info(f"Wrote {len(school_rows)} sorted report files to {output_dir}/")


def copy_to_school_dirs(output_dir, dest_path, schools_list):
    """Copy sorted reports to per-school directories under dest_path."""
    os.makedirs(dest_path, exist_ok=True)
    copied = 0
    run_date = datetime.now().strftime("%Y-%m-%d")

    for school in schools_list:
        output_file = school['output_file']
        src_file = os.path.join(output_dir, output_file)

        if not os.path.exists(src_file):
            continue

        school_dir_name = os.path.splitext(output_file)[0]
        dest_dir = os.path.join(dest_path, school_dir_name)
        os.makedirs(dest_dir, exist_ok=True)

        name, ext = os.path.splitext(output_file)
        dated_file = f"{name}_{run_date}{ext}"
        dest_file = os.path.join(dest_dir, dated_file)
        shutil.copy2(src_file, dest_file)
        copied += 1

    logging.info(f"Copied {copied} reports to per-school directories under {dest_path}")


def build_html_email(school_name, message_text):
    """Build a clean HTML email body from the plain text message."""
    escaped = message_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    paragraphs = ''.join(f'<p style="margin:0 0 12px 0;">{p.strip()}</p>'
                         for p in escaped.split('\n') if p.strip())

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#333;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:20px auto;">
    <tr>
      <td style="padding:24px;background:#ffffff;border:1px solid #e0e0e0;border-radius:4px;">
        <h2 style="margin:0 0 16px 0;font-size:18px;color:#1a1a1a;">
          AFN Fines and Fees Report — {school_name}
        </h2>
        {paragraphs}
        <hr style="border:none;border-top:1px solid #e0e0e0;margin:20px 0;">
        <p style="margin:0;font-size:12px;color:#888;">
          This is an automated message from the Scholars Portal AFN Fines Report system.
          If you believe you received this in error, please contact the system administrator.
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_emails(config, schools_list, output_dir=OUTPUT_DIR):
    """Send notification emails to schools that have reports."""
    schools_to_notify = []
    for school in schools_list:
        emails = school.get('emails', [])
        if not emails:
            continue
        report_file = os.path.join(output_dir, school['output_file'])
        if not os.path.exists(report_file):
            continue
        schools_to_notify.append((school['name'], emails))

    if not schools_to_notify:
        logging.info("No schools have email recipients configured, skipping notifications")
        return

    run_date = datetime.now().strftime("%B %d, %Y")
    email_subject = f"{config['email_subject']} ({run_date})"
    email_source = config["email_source"]
    email_message = config["message"]

    try:
        with smtplib.SMTP(config["smtpserver"], config["port"]) as server:
            server.starttls()

            if config.get("username") and config.get("password"):
                server.login(config["username"], config["password"])

            for school_name, emails in schools_to_notify:
                message = MIMEMultipart("alternative")
                message["From"] = email_source
                message["To"] = ", ".join(emails)
                message["Subject"] = email_subject

                # Plain text first, HTML second (email clients prefer the last part)
                message.attach(MIMEText(email_message, "plain"))
                message.attach(MIMEText(build_html_email(school_name, email_message), "html"))

                server.sendmail(email_source, emails, message.as_string())
                logging.info(f"  Sent notification to {school_name}: {', '.join(emails)}")

        logging.info(f"Sent {len(schools_to_notify)} email notifications")
    except Exception as e:
        logging.error(f"Error sending emails: {e}", exc_info=True)


def send_admin_log(config, log_file_path, success=True):
    """Send the log file to script admins after each run."""
    admins = config.get("script_admins", [])
    if not admins:
        logging.info("No script_admins configured, skipping admin log email")
        return

    email_source = config["email_source"]
    run_date = datetime.now().strftime("%B %d, %Y")
    status = "Completed" if success else "FAILED"
    subject = f"AFN Fines Report Processing - {status} ({run_date})"

    message = MIMEMultipart()
    message["From"] = email_source
    message["To"] = ", ".join(admins)
    message["Subject"] = subject
    message.attach(MIMEText(f"Processing {status.lower()}. Log file attached.", "plain"))

    with open(log_file_path, 'r') as f:
        attachment = MIMEBase('text', 'plain')
        attachment.set_payload(f.read())
        encoders.encode_base64(attachment)
        attachment.add_header('Content-Disposition', 'attachment', filename=os.path.basename(log_file_path))
        message.attach(attachment)

    try:
        with smtplib.SMTP(config["smtpserver"], config["port"]) as server:
            server.starttls()
            if config.get("username") and config.get("password"):
                server.login(config["username"], config["password"])
            server.sendmail(email_source, admins, message.as_string())
        logging.info(f"Sent admin log to: {', '.join(admins)}")
    except Exception as e:
        logging.error(f"Error sending admin log email: {e}", exc_info=True)


def main():
    log_file_path = setup_logger()
    logging.info("=" * 60)
    logging.info("AFN Fines Report Processing - Started")
    logging.info("=" * 60)

    config = None
    success = True

    try:
        config = load_config()
        school_lookup, schools_list = load_schools()

        # Step 1: Read input files, split by school, sort by email, write reports
        process_reports(school_lookup, config)

        # Step 2: Copy reports to per-school pickup directories
        output_path = config.get("output_path")
        if output_path:
            logging.info(f"Copying reports to school pickup directories...")
            copy_to_school_dirs(OUTPUT_DIR, output_path, schools_list)
        else:
            logging.info("No output_path configured, skipping copy to school directories")

        # Step 3: Send email notifications
        logging.info("Checking email notifications...")
        send_emails(config, schools_list)

        logging.info("=" * 60)
        logging.info("AFN Fines Report Processing - Completed")
        logging.info("=" * 60)
    except Exception as e:
        success = False
        logging.error(f"Processing failed: {e}", exc_info=True)
    finally:
        if config:
            send_admin_log(config, log_file_path, success)


if __name__ == "__main__":
    main()
