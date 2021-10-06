import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from chat_utils import chat_time_utils

if __name__ == "__main__":
    print(str(chat_time_utils.add_minutes(5)))