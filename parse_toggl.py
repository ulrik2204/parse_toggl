import os
from dataclasses import dataclass
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


class ReportBody(TypedDict, total=False):
    billable: bool
    client_ids: List[int]
    description: str
    end_date: str
    enrich_response: bool
    first_id: int
    first_row_number: Optional[int]
    first_timestamp: int
    group_ids: List[int]
    grouped: bool
    hide_amounts: bool
    max_duration_seconds: int
    min_duration_seconds: int
    order_by: str
    order_dir: str
    page_size: int
    project_ids: List[int]
    rounding: int
    rounding_minutes: int
    startTime: str
    start_date: str
    tag_ids: List[int]
    task_ids: List[int]
    time_entry_ids: List[int]
    user_ids: List[int]


class ReportTimeEntry(TypedDict):
    id: int
    seconds: int
    start: str
    stop: str
    at: str
    at_tz: str


class ReportResponse(TypedDict):
    user_id: int
    username: str
    project_id: int
    task_id: Optional[int]
    billable: bool
    description: str
    tag_ids: List[int]
    billable_amount_in_cents: Optional[int]
    hourly_rate_in_cents: Optional[int]
    currency: str
    time_entries: List[ReportTimeEntry]
    row_number: int


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


def fetch_toggl_report_page(
    api_token: str,
    workspace_id: str,
    description: str,
    start_date: datetime,
    end_date: datetime,
    first_row_number: Optional[int] = None,
) -> tuple[list[ReportResponse], Optional[int]]:
    """
    Fetch detailed time entries from the Toggl API filtered by the project name.
    """
    # Authenticate using API token
    auth = HTTPBasicAuth(api_token, "api_token")
    body: ReportBody = {
        # "date_format": "YYYY-MM-DD",
        # "display_mode": "date_and_time",
        # "duration_format": "improved",
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "first_row_number": None,
        "grouped": False,
        "order_by": "date",
        "order_dir": "asc",
        "grouped": False,
        "description": description,
    }
    if first_row_number:
        body["first_row_number"] = first_row_number
    response = requests.post(
        f"https://track.toggl.com/reports/api/v3/workspace/{workspace_id}/search/time_entries",
        auth=auth,
        json=body,
    )
    next_row_number = response.headers.get("X-Next-Row-Number", None)
    response.raise_for_status()
    return response.json(), int(next_row_number) if next_row_number else None


def fetch_toggl_report(
    api_token: str,
    workspade_id: str,
    description: str,
    start_date: datetime,
    end_date: datetime,
) -> list[ReportResponse]:
    """
    Fetch detailed time entries from the Toggl API filtered by the project name.
    """
    entries, next_row_number = fetch_toggl_report_page(
        api_token, workspade_id, description, start_date, end_date
    )
    max_calls = 20
    num_calls = 0
    while next_row_number:
        new_entries, next_row_number = fetch_toggl_report_page(
            api_token, workspade_id, description, start_date, end_date, next_row_number
        )
        entries.extend(new_entries)
        num_calls += 1
        if num_calls > max_calls:
            print(
                f"Max number of recurrent api-calls reached. Current max is {max_calls}."
            )
            break
    return entries


def format_toggl_entries(entries: List[TogglTimeEntry]) -> pd.DataFrame:
    """
    Formats the Toggl time entries into a Pandas DataFrame.
    Returns:
        pd.DataFrame: A DataFrame with the keys:
            - project_id: Project ID of the time entry
            - start: Start time of the time entry
            - stop: Stop time of the time entry
            - duration: Duration of the time entry
            - description: Description of the time entry
    """
    df = pd.DataFrame(entries)
    df["start"] = pd.to_datetime(df["start"]).dt.tz_localize(None)
    df["stop"] = pd.to_datetime(df["stop"]).dt.tz_localize(None)
    df["duration"] = pd.to_timedelta(df["duration"], unit="s")
    return df


def format_toggl_report(report: List[ReportResponse]) -> pd.DataFrame:
    """
    Formats the Toggl time entries into a Pandas DataFrame.
    Returns:
        pd.DataFrame: A DataFrame with the keys:
            - project_id: Project ID of the time entry
            - start: Start time of the time entry
            - stop: Stop time of the time entry
            - duration: Duration of the time entry
            - description: Description of the time entry
    """
    df = pd.DataFrame()
    df["project_id"] = [entry["project_id"] for entry in report]
    df["start"] = pd.to_datetime(
        pd.Series([entry["time_entries"][0]["start"] for entry in report])
    ).dt.tz_localize(None)
    df["stop"] = pd.to_datetime(
        pd.Series([entry["time_entries"][0]["stop"] for entry in report])
    ).dt.tz_localize(None)
    df["duration"] = pd.to_timedelta(
        [entry["time_entries"][0]["seconds"] for entry in report], unit="s"
    )
    df["description"] = [entry["description"] for entry in report]
    return df


def filter_by_date(
    df: pd.DataFrame, start_date: datetime, end_date: datetime
) -> pd.DataFrame:
    return df[(df["start"] >= start_date) & (df["stop"] <= end_date)]


def calculate_overtime_by_toggl_report(
    api_token: str,
    workspace: str,
    description: str,
    start_date: datetime,
    end_date: datetime,
    workday_hours: int = 8,
    fig_dir: Path | None = None,
):
    report = fetch_toggl_report(api_token, workspace, description, start_date, end_date)
    df = format_toggl_report(report)
    df = filter_by_date(df, start_date, end_date)
    calculate_overtime_in_df(df, description, workday_hours, fig_dir)


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


def seconds_to_timedelta(seconds):
    hours, remainder = divmod(abs(seconds), 3600)
    minutes, _ = divmod(remainder, 60)
    sign = "-" if seconds < 0 else ""
    return f"{sign}{int(hours):02}:{int(minutes):02}"


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
    # convert the time_diff_seconds, which can be negative to hours and minutes (which can be negative)
    df.loc[:, "time_diff_str"] = df["time_diff_seconds"].apply(seconds_to_timedelta)
    df.loc[:, "duration_str"] = df["duration_seconds"].apply(seconds_to_timedelta)
    print(
        df[
            [
                "project_id",
                "description",
                "start",
                "stop",
                "duration_str",
                "time_diff_str",
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
    workspace: str | None = os.getenv("WORKSPACE", default=None)


def safe_date_parse(date: str | None) -> datetime | None:
    if date:
        return parse(date)
    return None


@dataclass
class Options:
    start_date: datetime
    end_date: datetime
    api_token: str
    description: str
    fig_dir: Path
    workday_hours: int
    workspace: str
    csv: Path | None


def setup_options(
    *,
    csv: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
    api_token: str | None,
    description: str | None,
    fig_dir: str | None,
    workday_hours: int,
    workspace: str | None,
):
    start = (
        start_date
        or safe_date_parse(Env.start_date)
        or datetime.now() - timedelta(days=30)
    )
    end = end_date or safe_date_parse(Env.end_date) or datetime.now()
    csv_param: Path | None = None
    if csv_path := csv or Env.csv:
        csv_param = convert_windows_path_to_wsl(csv_path)
    desc = description or Env.description or "Jobb"
    token = api_token or Env.api_token
    fig_dir_str = fig_dir or Env.fig_dir or "plots"
    workspace_var = workspace or Env.workspace or None
    fig_path = Path(fig_dir_str)
    if not token:
        raise ValueError("API token was not set in arguments or in .env file")
    if not fig_path.exists():
        fig_path.mkdir(parents=True)
    if not workspace_var:
        raise ValueError("Workspace was not set in arguments or in .env file")

    return Options(
        start_date=start,
        end_date=end,
        api_token=token,
        description=desc,
        fig_dir=fig_path,
        workday_hours=workday_hours,
        workspace=workspace_var,
        csv=csv_param,
    )


@click.command()
@click.option("--csv", type=str)
@click.option("--start_date", type=click.DateTime())
@click.option("--end_date", type=click.DateTime())
@click.option("--api_token", type=str)
@click.option("--description", type=str)
@click.option("--fig_dir", type=str)
@click.option("--workday_hours", type=int, default=8)
@click.option("--workspace", type=str)
def calculate_overtime(
    csv: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
    api_token: str | None,
    description: str | None,
    fig_dir: str | None,
    workday_hours: int = 8,
    workspace: str | None = None,
):
    """
    Reads a quoted CSV file, calculates the time difference between 'Duration'
    and 8 hours, and outputs the sum of the time differences (overtime).
    """
    options = setup_options(
        start_date=start_date,
        end_date=end_date,
        api_token=api_token,
        description=description,
        fig_dir=fig_dir,
        workday_hours=workday_hours,
        workspace=workspace,
        csv=csv,
    )
    if not options.csv:
        if not options.api_token:
            raise ValueError("API token was not set in arguments or in .env file")
            # https://track.toggl.com/api/v9/workspaces/4867825/project_users?user_id=6338723
        calculate_overtime_by_toggl_report(
            options.api_token,
            options.workspace,
            options.description,
            options.start_date,
            options.end_date,
            options.workday_hours,
            options.fig_dir,
        )
        return
        calculate_overtime_by_toggl_api(
            token, desc, start, end, workday_hours=workday, fig_dir=fig_path
        )
    else:
        calculate_overtime_by_filepath(
            options.csv,
            options.description,
            options.start_date,
            options.end_date,
            options.workday_hours,
            options.fig_dir,
        )


if __name__ == "__main__":
    calculate_overtime()
