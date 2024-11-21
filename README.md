# Parse Toggl report

Find out how much overtime you have worked in a set time period (default last 30 days) using the Toggl API.

## First time setup

Requires python 3.10 or later. Written with 3.12.7

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

If you want to retrieve your last 30 days of work, simply run the script with the evironment variable `TOGGL_API_KEY` set to your Toggl API key.
```bash
python parse_toggl.py 
```

With options
```bash
python parse_toggl.py --start-date 2022-01-01 --end-date 2022-02-01 --api-key <your-api-key> --description <description> --csv <your_toggl_entries.csv>
```

If the csv is defined, the Toggl API will not be called and the csv will be used instead.

The description is what is currently being filtered on to find the relevant projects to calculate overtime on.