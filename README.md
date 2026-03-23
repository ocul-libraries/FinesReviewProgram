# Alma Fines and Outstanding Loans Analytics Report Generation

When students graduate from a CF institution, they may have fines and outstanding loans for books borrowed through AFN from another institution. Currently, there is no way in the Network Zone for a borrowing institution to see which of their graduating students are owing fines or about to abscond with books from AFN schools.

To overcome this problem, a standard analytics report has been created for all institutions to run at the end of each semester, accessible via Alma Analytics. This report provides information on the borrower, their institution (borrowing institution), the institution from which the resource was borrowed (lending institution), along with details on loans and fines. Each lending institution uploads this report to the Scholars Portal SFTP server. The script provided here, main.py, will output a report to be delivered to each borrowing institution on outstanding loans and fees owed by their students to each of the AFN schools.

## Process / Steps

1. Lending institutions upload their Alma Analytics reports (tab-delimited, UTF-16 encoded `.txt` files) to their respective directories on the Scholars Portal SFTP server. The input directory is configured via `scriptpath` in `config.yaml`.

2. main.py scans all `al-*` subdirectories, validates that each file has the expected headers, then reads all rows and splits them by borrowing institution using the school lookup in `schools.yaml`.

   For example, on reading the report produced by lending institution uOttawa, main.py sees a line indicating:
   `University of Ottawa	Queen's University	Ezra Bridger	ezrabridger@queensuni.ca	2024-04-30	150	1`

   The script recognizes the borrower comes from Queen's, and places this row in the report to be handed to Queen's University. Queen's University will read this file and discover Ezra Bridger is owing $150 and has one item outstanding at uOttawa. They will ask Ezra to please give uOttawa back our book and pay his fines :)

3. After collecting all rows, the script sorts each school's rows by email address (case-insensitive) and writes sorted reports with headers to the `SortedFiles/` directory. This makes it easier for borrowing institutions to contact borrowers who have outstanding loans and fines at multiple institutions. Rows with unknown or empty borrowers are written to `SortedFiles/errors.csv`.

4. If `output_path` is configured in `config.yaml`, the sorted reports are copied to per-school subdirectories under that path. When running in Docker, this directory is mounted as a volume.

6. After reports are generated, main.py sends an email notification to each school that has both email recipients configured in `schools.yaml` and a report with data. Schools with no fines records are not notified.

## How to run / test

### General info

This whole process is done in a docker container, so you don't need to worry about setting up a python environment. You can install docker desktop from here: https://www.docker.com/products/docker-desktop. This is a one time job run a few times a year, so you could run from anywhere, and probably don't want to even put on a server.

This way, you don't need to know how to setup a python environment. Once docker is installed, ensure it's running.

### Setup

1. Download and set up Docker Desktop
2. Download or clone the repository
3. Copy `config.yaml.sample` to `config.yaml` and fill in your values (see the sample file for all available options including SMTP settings, input/output paths, etc.)
4. Edit `schools.yaml` to add email recipients for each school.
5. Edit the docker-compose.yml or docker-compose-wsl.yml files to set volume mounts for input data and output directories.

#### Docker Compose commands

1. In the command line run the following to test and run the process: `docker-compose up --build`
2. To perform the process with the -wsl file (or another special case): `docker-compose -f docker-compose-wsl.yml up --build`

### Running locally (without Docker)

```bash
pip install -r requirements.txt
cp config.yaml.sample config.yaml   # edit with your values
python main.py
```

Logs are written to the `Logs/` directory with timestamped filenames.
