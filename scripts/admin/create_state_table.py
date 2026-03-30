import os
from dotenv import load_dotenv
from azure.data.tables import TableClient
from azure.core.exceptions import ResourceExistsError

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(PROJECT_ROOT, "config", ".env"))

# Replace with your actual connection string
connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
if not connection_string:
    raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is not set in environment variables.")
table_name = "SECProcessingState"

# Initialize the client
table_client = TableClient.from_connection_string(connection_string, table_name)

# Create the table if it doesn't exist
try:
    table_client.create_table()
    print(f"Table '{table_name}' created.")
except ResourceExistsError:
    print(f"Table '{table_name}' already exists.")

data = [
    {"blob_name": "raw/html/AEP/0000004904-26-000013/10-K.html", "accession_key": "0000004904-26-000013", "cik": "0000004904", "conformed_name": "AMERICAN ELECTRIC POWER CO INC."},
    {"blob_name": "raw/html/CEG/0001868275-26-000032/10-K.html", "accession_key": "0001868275-26-000032", "cik": "0001868275", "conformed_name": "CONSTELLATION ENERGY CORPORATION"},
    {"blob_name": "raw/html/DUK/0001326160-26-000014/10-K.html", "accession_key": "0001326160-26-000014", "cik": "0001326160", "conformed_name": "DUKE ENERGY CORPORATION"},
    {"blob_name": "raw/html/NEE/0000753308-26-000015/10-K.html", "accession_key": "0000753308-26-000015", "cik": "0000753308", "conformed_name": "NEXTERA ENERGY INC"},
    {"blob_name": "raw/html/SO/0000092122-26-000006/10-K.html", "accession_key": "0000092122-26-000006", "cik": "0000092122", "conformed_name": "The Southern Company"}
]

for item in data:
    entity = {
        "PartitionKey": "Utility_10K_2026",
        "RowKey": item["accession_key"],
        "CIK": item["cik"],
        "CompanyName": item["conformed_name"],
        "SourceBlob": item["blob_name"],
        "Status": "markdown_converted" # ready, pdf_converted, markdown_converted, error.
    }
    table_client.upsert_entity(entity)
    print(f"Populated: {item['conformed_name']}")