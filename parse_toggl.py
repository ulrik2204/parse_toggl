import os
from pathlib import Path
from tracemalloc import start
from dateutil.parser import parse
from dotenv import load_dotenv
from matplotlib import pyplot as plt
from datetime import datetime, timedelta
from requests.auth import HTTPBasicAuth
import pandas as pd
import click
import requests

from typing import TypedDict, List, Optional

class TogglTimeEntry(TypedDict):
    at: str  # Last updated timestamp
    billable: bool  # Whether the time entry is marked as billable
    client_name: Optional[str]  # Client name, if requested
    description: Optional[str]  # Description of the time entry
    duration: int  # Time entry duration, negative for running entries
    duronly: bool  # Deprecated field for duration-only entries
    id: int  # Time Entry ID
    permissions: List[str]  # List of permissions
    pid: Optional[int]  # Project ID (legacy field)
    project_active: Optional[bool]  # Whether the project is active
    project_billable: Optional[bool]  # Whether the project is billable
    project_color: Optional[str]  # Project color
    project_id: Optional[int]  # Project ID
    project_name: Optional[str]  # Project name
    shared_with: Optional[List[dict]]  # Who the entry has been shared with
    start: str  # Start time in UTC
    stop: Optional[str]  # Stop time in UTC, null if running
    tag_ids: Optional[List[int]]  # Tag IDs, null if not provided
    tags: Optional[List[str]]  # Tag names, null if not provided
    task_id: Optional[int]  # Task ID, null if not assigned
    task_name: Optional[str]  # Task name, if any
    tid: Optional[int]  # Task ID (legacy field)
    uid: int  # Time Entry creator ID (legacy field)
    user_avatar_url: Optional[str]  # URL of the user avatar
    user_id: int  # Time Entry creator ID
    user_name: Optional[str]  # User's name
    wid: Optional[int]  # Workspace ID (legacy field)
    workspace_id: int  # Workspace ID

TOGGL_API_BASE_URL = "https://api.track.toggl.com/api/v9"

def fetch_toggl_entries(api_token: str, start_time: datetime, end_time: datetime) -> List[TogglTimeEntry]:
    """
    Fetch detailed time entries from the Toggl API filtered by the project name.
    """
    # Authenticate using API token
    auth = HTTPBasicAuth(api_token, "api_token")
    
    # Fetch all time entries

    # params={"start_date": start_time.strftime("%Y-%m-%d"), "end_date": end_time.strftime("%Y-%m-%d")}
    response = requests.get(f"{TOGGL_API_BASE_URL}/me/time_entries", auth=auth, )
    response.raise_for_status()
    time_entries: list[TogglTimeEntry] = response.json()
    return time_entries

def format_toggl_entries(entries: List[TogglTimeEntry]) -> pd.DataFrame:
    """
    Formats the Toggl time entries into a Pandas DataFrame.
    """
    df = pd.DataFrame(entries)
    df["start"] = pd.to_datetime(df["start"]).dt.tz_localize(None)
    df["stop"] = pd.to_datetime(df["stop"]).dt.tz_localize(None)
    df['duration'] = pd.to_timedelta(df['duration'], unit="s")
    return df 

    
def calculate_overtime_by_toggl_api(api_token, description, start_date: datetime, end_date: datetime):
    """
    Fetches time entries from the Toggl API and calculates the overtime.
    """
    entries = fetch_toggl_entries(api_token, start_date, end_date)
    df = format_toggl_entries(entries)

    calculate_overtime_in_df(df, description, start_date, end_date)



def convert_windows_path_to_wsl(path: str) -> Path:
    """
    Converts a Windows-style file path (e.g., C:\\Users\\...) into
    a WSL-compatible path (/mnt/c/users/...).
    """
    if ":" in path:  # Detect Windows-style path
        drive, rest = path.split(":", 1)
        wsl_path = f"/mnt/{drive.lower()}{rest.replace('\\', '/')}"
        return Path(wsl_path)
    return Path(path)

def calculate_overtime_by_filepath(csv: Path, description: str, start_date: datetime, end_date: datetime):
    """
    Reads a quoted CSV file, calculates the time difference between 'Duration'
    and 8 hours, and outputs the sum of the time differences (overtime).
    """
    df = pd.read_csv(csv, sep=",", quotechar='"')

    # Convert 'Duration' to timedelta (assuming format is HH:MM:SS or similar)
    df['duration'] = pd.to_timedelta(df['Duration'])
    calculate_overtime_in_df(df, description, start_date, end_date)    


def calculate_overtime_in_df(df: pd.DataFrame, description: str, start_date: datetime, end_date: datetime):
    df = df[(df["description"].str.lower().str.contains(description.lower()))]

    # Convert 'duration' to timedelta (assuming format is HH:MM:SS or similar)
    # Filter by Gjensidige project

    durations = df["duration"]
    # Filter entries that are lower than 0
    durations_seconds = durations[durations > pd.Timedelta(0)].apply(lambda x: x.seconds)
    # Calculate the time_diff_seconds column (difference from 8 hours)
    eight_hours = pd.Timedelta(hours=8).seconds
    # Calcualte the time difference in seconds
    df['time_diff_seconds'] = (durations_seconds - eight_hours)
    print(df[["project_id", "description", "start", "stop", "duration", "time_diff_seconds"]])

    # Calculate total overtime
    total_overtime = df['time_diff_seconds'].sum()
    # Convert from seconds to hours and minutes
    total_overtime = timedelta(seconds=total_overtime)

    # Output the result
    print(f"Total overtime: {total_overtime}")
    df["time_diff_seconds"].plot(kind="line")
    time = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    plt.savefig(f"overtime-{time}.png")
    ## Add a title to the figure about the anount of overtime
    plt.title(f"Overtime per day (total overtime: {total_overtime})")


class Env:
    load_dotenv()
    csv: str | None = os.getenv("CSV", default=None)
    start_date: str | None = os.getenv("START_DATE", default=None)
    end_date: str | None = os.getenv("END_DATE", default=None)
    api_token: str | None = os.getenv("TOGGL_API_TOKEN", default=None)
    description: str | None = os.getenv("DESCRIPTION", default=None)
    
   
def safe_date_parse(date: str | None) -> datetime | None:
    if date:
        return parse(date)
    return None

@click.command()
@click.option('--csv', type=str)
@click.option("--start_date", type=click.DateTime())
@click.option("--end_date", type=click.DateTime())
@click.option("--api_token", type=str)
@click.option("--description", type=str)
def calculate_overtime(csv: str | None, start_date: datetime | None, end_date: datetime | None, api_token: str | None, description: str | None):
    """
    Reads a quoted CSV file, calculates the time difference between 'Duration'
    and 8 hours, and outputs the sum of the time differences (overtime).
    """
    start = start_date or safe_date_parse(Env.start_date) or datetime.now()
    end = end_date or safe_date_parse(Env.end_date) or datetime.now() - timedelta(days=30)
    project = description or Env.description or "Jobb"
    token = api_token or Env.api_token 
    if not csv:
        if not token:
            raise ValueError("API token was not set in arguments or in .env file")
        calculate_overtime_by_toggl_api(token, project, start, end)
    else:
        calculate_overtime_by_filepath(convert_windows_path_to_wsl(csv), project, start, end)

if __name__ == "__main__":
    calculate_overtime()
