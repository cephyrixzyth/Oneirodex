import socket
import time

from sqlalchemy import event
from sqlalchemy.engine import Engine


@event.listens_for(Engine, 'connect')
def _set_postgresql_session_timezone_utc(dbapi_connection, _connection_record):
    """Keep every psycopg connection on UTC, including engines outside Flask.

    ``DateTime`` columns without a timezone are stored as wall time by
    PostgreSQL. If the server session uses a local timezone, an aware UTC value
    is converted to that zone on insert and read back as naive local time. The
    app then cannot reliably compare or format the original instant. The
    connection listener also covers migration and standalone utility engines.
    """
    driver = type(dbapi_connection).__module__.split('.', 1)[0]
    if driver not in {'psycopg', 'psycopg2'}:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET TIME ZONE 'UTC'")
        dbapi_connection.commit()
    finally:
        cursor.close()

def check_postgres_port_open(host, port, retries=5, delay=2):
    """
    Checks if the PostgreSQL port is open by attempting to create a socket connection.
    If the connection attempt fails, it waits for 'delay' seconds and retries.
    
    :param host: The hostname or IP address of the PostgreSQL server.
    :param port: The port number of the PostgreSQL server.
    :param retries: Maximum number of retries.
    :param delay: Delay in seconds between retries.
    :return: True if the port is open, False otherwise.
    """
    for attempt in range(retries):
        try:
            with socket.create_connection((host, port), timeout=10):
                print(f"Connection to PostgreSQL on port {port} successful.")
                return True
        except (socket.timeout, ConnectionRefusedError):
            print(f"Connection to PostgreSQL on port {port} failed. Attempt {attempt + 1} of {retries}.")
            time.sleep(delay)
    return False
