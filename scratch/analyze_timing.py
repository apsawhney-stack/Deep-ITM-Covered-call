import os
import re
from datetime import datetime

def parse_log_durations(log_path):
    if not os.path.exists(log_path):
        return None
        
    durations = []
    current_sweep = None
    start_time = None
    
    # We will read the file and extract timestamps
    # In task logs, each line has no timestamp, but we can look at file creation/modification time,
    # or if there are print statements with times.
    # Wait, the task manager saves stdout. The stdout itself doesn't print timestamps, 
    # but the system logs inside .system_generated/tasks/ or transcript.jsonl might have step times.
    # Let's check transcript.jsonl instead, which lists exact start/end timestamps of every command!
    pass

def analyze_transcript():
    transcript_path = "/Users/aps/.gemini/antigravity/brain/40bec107-7eca-41bc-a38d-db03ae0f5207/.system_generated/logs/transcript.jsonl"
    if not os.path.exists(transcript_path):
        print("Transcript not found")
        return
        
    with open(transcript_path, 'r') as f:
        lines = f.readlines()
        
    # We want to find run_command calls for "main.py"
    import json
    for line in lines:
        try:
            data = json.loads(line)
            if data.get("type") == "RUN_COMMAND" and "main.py" in data.get("content", ""):
                print(f"Task ID: {data.get('step_index') or data.get('taskId')} | Created: {data.get('created_at')} | Status: {data.get('status')}")
            elif data.get("type") == "SYSTEM_MESSAGE" and "finished with result" in data.get("content", ""):
                content = data.get("content", "")
                m = re.search(r'Task id "([^"]+)" finished', content)
                if m:
                    task_id = m.group(1)
                    print(f"  Finished Task: {task_id} | Completed: {data.get('created_at')}")
        except Exception as e:
            continue

if __name__ == "__main__":
    analyze_transcript()
