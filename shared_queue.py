import queue

command_queue = queue.Queue()

import queue

# Create a globally accessible, thread-safe queue.
command_queue = queue.Queue()

def get_parsed_command():
    """
    Safely retrieves and parses the next command from the global queue.
    Uses get_nowait() to ensure the calling thread is never blocked.
    
    Returns:
        str: The lowercased command string if available.
        None: If the queue is empty or the text is invalid.
    """
    try:
        cmd_text = command_queue.get_nowait()
        parts = cmd_text.split()
        
        # Ensure the string wasn't empty before attempting to access the first index
        if parts:
            new_command = parts
            # [0].lower()
            # print("new command is: ", new_command)
            return new_command
            
        return None
        
    except queue.Empty:
        # The queue has no items pending.
        return None