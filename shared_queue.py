import queue

command_queue = queue.Queue()

def get_parsed_command():
    """
    Safely retrieves and parses the next command from the global queue.
    Uses get_nowait() to ensure the calling thread is never blocked.
    """
    try:
        cmd_text = command_queue.get_nowait()
        parts = cmd_text.split()
        if parts:
            return parts
        return None
    except queue.Empty:
        return None
