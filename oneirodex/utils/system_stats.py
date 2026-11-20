import logging
import os
import platform

import psutil

logger = logging.getLogger(__name__)

def get_cpu_usage():
    """Get CPU usage percentage"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count_physical = psutil.cpu_count(logical=False)
        cpu_count_logical = psutil.cpu_count(logical=True)
        return {
            'percent': cpu_percent,
            'cores_physical': cpu_count_physical,
            'cores_logical': cpu_count_logical
        }
    except Exception as e:
        print(f"Error getting CPU usage: {e}")
        return None

def get_memory_usage():
    """Get memory usage statistics"""
    try:
        memory = psutil.virtual_memory()
        return {
            'total': memory.total,
            'available': memory.available,
            'used': memory.used,
            'percent': memory.percent
        }
    except Exception as e:
        print(f"Error getting memory usage: {e}")
        return None

def get_disk_usage():
    """Get disk usage for the application's base folder"""
    try:
        from config import Config

        base_path = Config.BASE_FOLDER_WINDOWS if os.name == 'nt' else Config.BASE_FOLDER_POSIX
        if not os.path.exists(base_path):
            return None
        
        disk_usage = psutil.disk_usage(base_path)
        return {
            'total': disk_usage.total,
            'used': disk_usage.used,
            'free': disk_usage.free,
            'percent': disk_usage.percent
        }
    except Exception as e:
        print(f"Error getting disk usage: {e}")
        return None

def get_games_folder_usage():
    """Get disk usage for the games folder."""
    try:
        from config import Config

        games_path = Config.DATA_FOLDER_GAMES
        if not os.path.exists(games_path):
            return None

        disk_usage = psutil.disk_usage(games_path)
        return {
            'total': disk_usage.total,
            'used': disk_usage.used,
            'free': disk_usage.free,
            'percent': disk_usage.percent
        }
    except Exception as e:
        print(f"Error getting games folder disk usage: {e}")
        return None


def format_bytes(bytes_value):
    """Convert bytes to human readable format"""
    if bytes_value is None:
        return "N/A"
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024
    return f"{bytes_value:.2f} PB"

def get_load_average():
    """Return 1/5/15-minute load averages when the OS exposes them.

    Linux/macOS via ``os.getloadavg``; Windows and restricted hosts return None.
    """
    try:
        one, five, fifteen = os.getloadavg()
        return {
            '1': round(float(one), 2),
            '5': round(float(five), 2),
            '15': round(float(fifteen), 2),
        }
    except (AttributeError, OSError) as e:
        # Windows has no getloadavg; some containers deny /proc/loadavg.
        logger.debug("Load average unavailable: %s", e)
        return None
    except Exception as e:
        logger.warning("Error getting load average: %s", e)
        return None


def get_process_memory():
    """Return this process RSS (bytes) when cheaply available via psutil."""
    try:
        proc = psutil.Process()
        rss = int(proc.memory_info().rss)
        return {
            'pid': proc.pid,
            'rss_bytes': rss,
        }
    except (psutil.Error, OSError, AttributeError) as e:
        logger.debug("Process memory unavailable: %s", e)
        return None
    except Exception as e:
        logger.warning("Error getting process memory: %s", e)
        return None


# --- GPU (INSP-44 / MISS-OPS-3) ------------------------------------------------
#
# Two honest sources and nothing bundled: NVIDIA's own management library when
# the optional ``pynvml`` package is importable *and* a device answers (the
# Docker host on the Unraid box usually has neither), else a BYO sensor reader
# on a household PC -- LibreHardwareMonitor / HWiNFO-class JSON at
# ``TELEMETRY_READER_URL`` -- polled read-only. No kernel driver, no sensor
# tool in the image, and the Ops tile says ``n/a`` when both are silent.

_GPU_READER_TIMEOUT = 3


def _gpu_via_nvml():
    try:
        import pynvml  # optional extra
    except Exception:  # noqa: BLE001
        return None
    try:
        pynvml.nvmlInit()
    except Exception as e:  # noqa: BLE001 -- no driver / no device
        logger.debug("NVML unavailable: %s", e)
        return None
    try:
        count = int(pynvml.nvmlDeviceGetCount())
        gpus = []
        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode('utf-8', 'replace')
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            try:
                temp = int(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
            except Exception:  # noqa: BLE001
                temp = None
            gpus.append({
                'name': str(name),
                'util_percent': float(util.gpu),
                'mem_used': int(mem.used),
                'mem_total': int(mem.total),
                'temp_c': temp,
            })
        return {'source': 'nvml', 'gpus': gpus} if gpus else None
    except Exception as e:  # noqa: BLE001
        logger.debug("NVML read failed: %s", e)
        return None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass


def _walk(node, path=()):
    """Yield (path_names, node) for every dict in a LibreHardwareMonitor-style tree."""
    if isinstance(node, dict):
        text = str(node.get('Text') or node.get('text') or node.get('name') or '')
        here = path + ((text,) if text else ())
        yield here, node
        for child in node.get('Children') or node.get('children') or node.get('sensors') or []:
            yield from _walk(child, here)
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child, path)


def _num(raw):
    """``"57.0 %"`` / ``"7,892 MB"`` / ``57`` -> float, else None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).replace(',', '').strip()
    out = ''
    for ch in text:
        if ch.isdigit() or ch in '.-':
            out += ch
        elif out:
            break
    try:
        return float(out) if out else None
    except ValueError:
        return None


def parse_telemetry_reader(payload):
    """A generous read of a LibreHardwareMonitor / HWiNFO-class JSON tree.

    Finds GPU nodes (any node whose name or image mentions a GPU vendor, or
    whose children include a *GPU Core* load), then the load, memory and
    temperature sensors under them. Missing pieces stay ``None``; no GPU
    node at all returns ``None`` -- never an empty list dressed as data.
    """
    gpus = []
    for names, node in _walk(payload):
        text = (names[-1] if names else '') or ''
        image = str(node.get('ImageURL') or node.get('image') or '').lower()
        looks_gpu = any(v in image for v in ('nvidia', 'amd', 'ati', 'intel')) and 'cpu' not in image
        looks_gpu = looks_gpu or any(v in text.lower() for v in ('geforce', 'radeon', 'rtx', 'gtx', 'arc a', 'arc b', 'quadro'))
        if not looks_gpu:
            continue
        util = mem_used = mem_total = temp = None
        for sub_names, sensor in _walk(node):
            label = (sub_names[-1] if sub_names else '').lower()
            value = sensor.get('Value') if 'Value' in sensor else sensor.get('value')
            if value is None:
                continue
            parent = ' '.join(sub_names[-2:-1]).lower() if len(sub_names) >= 2 else ''
            if label in ('gpu core', 'gpu', 'd3d 3d') and 'load' in parent and util is None:
                util = _num(value)
            elif label in ('gpu memory used', 'gpu memory', 'd3d dedicated memory used') and 'load' not in parent and mem_used is None:
                v = _num(value)
                mem_used = int(v * 1024 * 1024) if v is not None and 'mb' in str(value).lower() else (int(v) if v is not None else None)
            elif label in ('gpu memory total',) and 'load' not in parent and mem_total is None:
                v = _num(value)
                mem_total = int(v * 1024 * 1024) if v is not None and 'mb' in str(value).lower() else (int(v) if v is not None else None)
            elif label in ('gpu core', 'gpu hot spot', 'gpu') and 'temperature' in parent and temp is None:
                t = _num(value)
                temp = int(t) if t is not None else None
        gpus.append({
            'name': text or 'GPU',
            'util_percent': util,
            'mem_used': mem_used,
            'mem_total': mem_total,
            'temp_c': temp,
        })
    return {'source': 'reader', 'gpus': gpus} if gpus else None


def _gpu_via_reader():
    url = (os.getenv('TELEMETRY_READER_URL') or '').strip()
    if not url:
        return None
    try:
        from oneirodex.utils.http_safe import safe_request
        from oneirodex.utils.security import validate_user_outbound_http_url

        resp = safe_request('GET', url, validator=validate_user_outbound_http_url, timeout=_GPU_READER_TIMEOUT)
        if resp.status_code != 200:
            logger.debug("Telemetry reader HTTP %s", resp.status_code)
            return None
        parsed = parse_telemetry_reader(resp.json())
        if parsed:
            parsed['reader_url'] = url
        return parsed
    except Exception as e:  # noqa: BLE001 -- offline reader is "no data"
        logger.debug("Telemetry reader unavailable: %s", e)
        return None


def get_gpu_usage():
    """GPU pulse for Ops: ``{'source': 'nvml'|'reader', 'gpus': [...]}`` or
    ``None`` when neither NVML nor a BYO reader answers. Never bundles a
    sensor tool or a driver; never raises."""
    try:
        return _gpu_via_nvml() or _gpu_via_reader()
    except Exception as e:  # noqa: BLE001
        logger.warning("Error getting GPU usage: %s", e)
        return None
