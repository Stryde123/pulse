import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import logging
logging.basicConfig(level=logging.INFO)

from agents.salesforce_mcp import query_account

print("Querying...")
record = query_account("Edge Communications")
print(f"RESULT: {record}")
