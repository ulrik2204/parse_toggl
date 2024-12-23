import os
from datetime import datetime, timedelta
from pathlib import Path
from tracemalloc import start
from typing import List, Optional, TypedDict

import click
import pandas as pd
import requests
from dateutil.parser import parse
from dotenv import load_dotenv
from matplotlib import pyplot as plt
from requests.auth import HTTPBasicAuth


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


def fetch_toggl_entries(
    api_token: str, start_time: datetime, end_time: datetime
) -> List[TogglTimeEntry]:
    """
    Fetch detailed time entries from the Toggl API filtered by the project name.
    """
    # Authenticate using API token
    auth = HTTPBasicAuth(api_token, "api_token")

    # Fetch all time entries

    params = {
        "start_date": start_time.strftime("%Y-%m-%d"),
        "end_date": end_time.strftime("%Y-%m-%d"),
    }
    response = requests.get(
        f"{TOGGL_API_BASE_URL}/me/time_entries", auth=auth, params=params
    )
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
    df["duration"] = pd.to_timedelta(df["duration"], unit="s")
    return df


def filter_by_date(
    df: pd.DataFrame, start_date: datetime, end_date: datetime
) -> pd.DataFrame:
    return df[(df["start"] >= start_date) & (df["stop"] <= end_date)]


def calculate_overtime_by_toggl_api(
    api_token,
    description,
    start_date: datetime,
    end_date: datetime,
    workday_hours: int = 8,
    fig_dir: Path | None = None,
):
    """
    Fetches time entries from the Toggl API and calculates the overtime.
    """
    entries = fetch_toggl_entries(api_token, start_date, end_date)
    df = format_toggl_entries(entries)
    df = filter_by_date(df, start_date, end_date)

    calculate_overtime_in_df(df, description, workday_hours, fig_dir)


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


def calculate_overtime_by_filepath(
    csv: Path,
    description: str,
    start_date: datetime,
    end_date: datetime,
    workday_hours: int = 8,
    fig_dir: Path | None = None,
):
    """
    Reads a quoted CSV file, calculates the time difference between 'Duration'
    and 8 hours, and outputs the sum of the time differences (overtime).
    """
    df = pd.read_csv(csv, sep=",", quotechar='"')

    # Convert 'Duration' to timedelta (assuming format is HH:MM:SS or similar)
    df["duration"] = pd.to_timedelta(df["Duration"])
    df = filter_by_date(df, start_date, end_date)
    calculate_overtime_in_df(df, description, workday_hours, fig_dir)


def calculate_overtime_in_df(
    df: pd.DataFrame,
    description: str,
    workday_hours: int = 8,
    fig_dir: Path | None = None,
):
    # TODO: Filter by project
    # Filter by description
    df = df[(df["description"].str.lower().str.contains(description.lower()))].copy()
    df["duration_seconds"] = df["duration"].dt.total_seconds()
    # Resample to daily
    df = df.resample("D", on="start").agg(
        {
            "project_id": "first",
            "description": "first",
            "start": "first",
            "stop": "last",
            "duration_seconds": "sum",
        }
    )
    # remote nan
    df = df.dropna()
    durations_seconds = df.loc[:, "duration_seconds"]
    work_hours = pd.Timedelta(hours=workday_hours).seconds
    df.loc[:, "time_diff_seconds"] = durations_seconds - work_hours
    print(
        df[
            [
                "project_id",
                "description",
                "start",
                "stop",
                "duration_seconds",
                "time_diff_seconds",
            ]
        ]
    )

    # Calculate total overtime
    total_overtime = float(df["time_diff_seconds"].sum())
    # Convert from seconds to hours and minutes
    total_overtime = timedelta(seconds=total_overtime)

    # Output the result
    print(f"Total overtime: {total_overtime}")
    df["time_diff_seconds"].plot(kind="line")
    time = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    name = f"overtime-{time}.png"
    fig_path = fig_dir / name if fig_dir else Path(name)
    plt.savefig(fig_path.as_posix())
    ## Add a title to the figure about the anount of overtime
    plt.title(f"Overtime per day (total overtime: {total_overtime})")


class Env:
    load_dotenv()
    csv: str | None = os.getenv("CSV", default=None)
    start_date: str | None = os.getenv("START_DATE", default=None)
    end_date: str | None = os.getenv("END_DATE", default=None)
    api_token: str | None = os.getenv("TOGGL_API_TOKEN", default=None)
    description: str | None = os.getenv("DESCRIPTION", default=None)
    fig_dir: str | None = os.getenv("FIG_DIR", default=None)
    workday_hours: int = int(os.getenv("WORKDAY_HOURS", default=8))


def safe_date_parse(date: str | None) -> datetime | None:
    if date:
        return parse(date)
    return None


@click.command()
@click.option("--csv", type=str)
@click.option("--start_date", type=click.DateTime())
@click.option("--end_date", type=click.DateTime())
@click.option("--api_token", type=str)
@click.option("--description", type=str)
@click.option("--fig_dir", type=str)
@click.option("--workday_hours", type=int, default=8)
def calculate_overtime(
    csv: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
    api_token: str | None,
    description: str | None,
    fig_dir: str | None,
    workday_hours: int = 8,
):
    """
    Reads a quoted CSV file, calculates the time difference between 'Duration'
    and 8 hours, and outputs the sum of the time differences (overtime).
    """
    start = (
        start_date
        or safe_date_parse(Env.start_date)
        or datetime.now() - timedelta(days=30)
    )
    end = end_date or safe_date_parse(Env.end_date) or datetime.now()
    project = description or Env.description or "Jobb"
    token = api_token or Env.api_token
    fig_dir_str = fig_dir or Env.fig_dir or "plots"
    fig_path = Path(fig_dir_str)
    if not fig_path.exists():
        fig_path.mkdir(parents=True)
    workday = workday_hours or Env.workday_hours or 8
    if not csv:
        if not token:
            raise ValueError("API token was not set in arguments or in .env file")
        calculate_overtime_by_toggl_api(
            token, project, start, end, workday_hours=workday, fig_dir=fig_path
        )
    else:
        calculate_overtime_by_filepath(
            convert_windows_path_to_wsl(csv),
            project,
            start,
            end,
            workday_hours=workday,
            fig_dir=fig_path,
        )


if __name__ == "__main__":
    calculate_overtime()
