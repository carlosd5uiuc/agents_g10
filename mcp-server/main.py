import json
import os
from mcp.server.fastmcp import FastMCP
from pathlib import Path

mcp = FastMCP("Personal Task Tools")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "resource_data"

# -------------------------
# T1: Travel Arrangement
# -------------------------

def load_json_file(file_path: Path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

@mcp.resource("transportation://list")
def get_ride_options() -> str:
    """
    Get available transportation options

    Returns:
        str: A list of rides with ID, arrival time, cost, surge pricing, and rideshare availability.
    """
    INITIAL_TASK_DATA = DATA_DIR / "task_01.json"
    flights = load_json_file(INITIAL_TASK_DATA)
    return str(flights)


@mcp.resource("travel://confirmation/{confirmation_id}")
def get_travel_confirmation(confirmation_id: str) -> str:
    """
    Get travel confirmation ID and calendar entry.

    Args:
        confirmation_id (str): The confirmation ID.

    Returns:
        str: Travel confirmation details.
    """
    return (
        f"Confirmation ID: {confirmation_id}\n"
        f"Calendar Entry: Travel arrangement scheduled."
    )


@mcp.tool()
def create_travel_arrangement(flight_id: str, include_rideshare: bool) -> str:
    """
    Create a travel arrangement.

    Args:
        flight_id (str): Selected flight ID.
        include_rideshare (bool): Whether to include rideshare.

    Returns:
        str: Confirmation message.
    """
    return (
        f"Travel arrangement created for flight {flight_id}. "
        f"Rideshare included: {include_rideshare}. "
        f"Confirmation ID: TRAVEL-{flight_id}"
    )


# -------------------------
# T2: Repair Appointment
# -------------------------

@mcp.resource("repair://options")
def get_repair_options() -> str:
    """
    Get repair options.

    Returns:
        str: Repair options with type, network, deductible, and day of week.
    """
    INITIAL_TASK_DATA = DATA_DIR / "task_02.json"
    repairs = load_json_file(INITIAL_TASK_DATA)
    return str(repairs)


@mcp.resource("repair://confirmation/{confirmation_id}")
def get_repair_confirmation(confirmation_id: str) -> str:
    """
    Get repair confirmation.

    Args:
        confirmation_id (str): The confirmation ID.

    Returns:
        str: Repair confirmation details.
    """
    return f"Repair appointment confirmed. Confirmation ID: {confirmation_id}"


@mcp.tool()
def set_up_repair_appointment(type_of_repair: str, day_of_week: str) -> str:
    """
    Set up a repair appointment.

    Args:
        type_of_repair (str): Type of repair needed.
        day_of_week (str): Preferred day of week.

    Returns:
        str: Confirmation message.
    """
    return (
        f"Repair appointment scheduled for {type_of_repair} on {day_of_week}. "
        f"Confirmation ID: REPAIR-{day_of_week.upper()}"
    )


# -------------------------
# T3: Catering + Invitations
# -------------------------

SENT_INVITATIONS = []

@mcp.resource("catering://options")
def get_catering_options() -> str:
    """
    Get catering options.

    Returns:
        str: Catering options with price, menu options, and number of people.
    """
    INITIAL_TASK_DATA = DATA_DIR / "task_03.json"
    catering_options = load_json_file(INITIAL_TASK_DATA)
    return str(catering_options)


@mcp.resource("catering://invitations")
def get_sent_invitations() -> str:
    """
    Get sent invitations.

    Returns:
        str: Sent invitations.
    """
    return str(SENT_INVITATIONS) if SENT_INVITATIONS else "No invitations sent yet."


@mcp.resource("catering://confirmation/{confirmation_id}")
def get_catering_confirmation(confirmation_id: str) -> str:
    """
    Get catering order confirmation.

    Args:
        confirmation_id (str): The confirmation ID.

    Returns:
        str: Catering confirmation details.
    """
    return f"Catering order confirmed. Confirmation ID: {confirmation_id}"


@mcp.tool()
def send_invitations(guests: list[dict]) -> str:
    """
    Send invitations.

    Args:
        guests (list[dict]): List of guests, each with name and email.

    Returns:
        str: Confirmation message.
    """
    SENT_INVITATIONS.extend(guests)
    return f"Sent invitations to {len(guests)} guests."


@mcp.tool()
def set_catering_appointment(menu_option: str, number_of_people: int) -> str:
    """
    Set catering appointment.

    Args:
        menu_option (str): Selected menu option.
        number_of_people (int): Number of people.

    Returns:
        str: Confirmation message.
    """
    return (
        f"Catering appointment set for {number_of_people} people "
        f"with menu option: {menu_option}. "
        f"Confirmation ID: CATERING-{number_of_people}"
    )


# -------------------------
# T4: Doctor Appointment
# -------------------------

@mcp.resource("doctor://list")
def get_doctor_list() -> str:
    """
    Get doctor list.

    Returns:
        str: Doctors with type, name, specializations, copay, and availability.
    """
    INITIAL_TASK_DATA = DATA_DIR / "task_04.json"
    doctors = load_json_file(INITIAL_TASK_DATA)
    return str(doctors)


@mcp.resource("doctor://appointment/{confirmation_id}")
def get_doctor_appointment(confirmation_id: str) -> str:
    """
    Get doctor appointment.

    Args:
        confirmation_id (str): The confirmation ID.

    Returns:
        str: Doctor appointment confirmation.
    """
    return f"Doctor appointment confirmed. Confirmation ID: {confirmation_id}"


@mcp.tool()
def set_up_doctor_appointment(doctor_name: str, appointment_time: str) -> str:
    """
    Set up doctor appointment.

    Args:
        doctor_name (str): Name of doctor.
        appointment_time (str): Desired appointment time.

    Returns:
        str: Confirmation message.
    """
    return (
        f"Appointment scheduled with {doctor_name} at {appointment_time}. "
        f"Confirmation ID: DOCTOR-{doctor_name.replace(' ', '-').upper()}"
    )


# -------------------------
# T5: Troubleshooting + Repair Guy
# -------------------------

@mcp.resource("troubleshoot://guide")
def get_troubleshoot_guide() -> str:
    """
    Get troubleshooting guide.

    Returns:
        str: Troubleshooting guide with symptoms and likely causes.
    """
    INITIAL_TASK_DATA = DATA_DIR / "task_05_01.json"
    troubleshoot_guide = load_json_file(INITIAL_TASK_DATA)
    return str(troubleshoot_guide)


@mcp.resource("troubleshoot://repair")
def get_repair_guy() -> str:
    """
    Get appliance repair providers.

    Returns:
        str: Repair providers with appliance type, distance, and price.
    """
    INITIAL_TASK_DATA = DATA_DIR / "task_05_02.json"
    repair_providers = load_json_file(INITIAL_TASK_DATA)
    return str(repair_providers)

# -------------------------
# T6: Household Bills
# -------------------------

@mcp.resource("household-bills://list")
def get_household_bills() -> str:
    """
    Get pending bills

    Returns:
        str: Get list of bills
    """
    return str(load_json_file(DATA_DIR / "task_06.json"))

# -------------------------
# T7: Exercise Routing
# -------------------------

## No resources for task #7

# -------------------------
# T8: Reduce expenses
# -------------------------

## No resources for task #8

# -------------------------
# T9: Online purchase return
# -------------------------

@mcp.resource("online-purchase://return_options")
def get_return_options() -> str:
    """
    Get return options for an item purchased online

    Returns:
        str: Get list of return options
    """
    return str(load_json_file(DATA_DIR / "task_09.json"))

# -------------------------
# T10: Online purchase return
# -------------------------

@mcp.resource("pending-bills://list")
def get_pending_bills() -> str:
    """
    Get a list of pending bills with their corresponding ammounts and due dates

    Returns:
        str: Get list of pending bills
    """
    return str(load_json_file(DATA_DIR / "task_10.json"))
