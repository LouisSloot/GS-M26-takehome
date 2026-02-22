import duckdb
import huggingface_hub as hf_hub
from dotenv import load_dotenv
import os

load_dotenv()

token = os.getenv("HF_RTOKEN")
hf_hub.login(token)

# Get the list of parquet files from HF without downloading them
fs = hf_hub.HfFileSystem(token=token)
parquet_files = fs.glob("datasets/allenai/wildguardmix/**/*.parquet")

# Convert HF paths to direct HTTPS URLs
def hf_path_to_url(path):
    # e.g. datasets/allenai/wildguardmix/resolve/main/data/train.parquet
    path = path.removeprefix("datasets/")
    return f"https://huggingface.co/datasets/{path}".replace(
        "/allenai/wildguardmix/", "/allenai/wildguardmix/resolve/main/"
    )

urls = [hf_path_to_url(f) for f in parquet_files]

connection = duckdb.connect()
connection.execute("INSTALL httpfs; LOAD httpfs;")
connection.execute(f"SET s3_access_key_id='';")  # clear any s3 defaults
connection.execute(f"""
    CREATE SECRET hf_secret (
        TYPE HTTP,
        EXTRA_HTTP_HEADERS MAP {{
            'Authorization': 'Bearer {token}'
        }}
    );
""")

# union of all parquet URLs
url_list = ", ".join(f"'{u}'" for u in urls)

categories = [
"sexual_content",

"mental_health_over-reliance_crisis",

"violence_and_physical_harm",

"copyright_violations",

"private_information_individual",

"disseminating_false_or_misleading_information_encouraging_disinformation_campaigns","causing_material_harm_by_disseminating_misinformation","defamation_encouraging_unethical_or_unsafe_actions",

"fraud_assisting_illegal_activities",

"cyberattack","sensitive_information_organization_government",
] # need CBRN still and some dont map exactly

for cat in categories:
    for harm in ["unharmful", "harmful"]:
        query = f"""
        SELECT prompt FROM read_parquet([{url_list}], union_by_name=true)
        WHERE prompt_harm_label = '{harm}' 
        AND adversarial = 'false'
        AND subcategory = '{cat}'
        LIMIT 100
        """
        os.makedirs(f'data/train/{cat}', exist_ok=True)
        connection.execute(f"COPY ({query}) TO 'data/train/{cat}/{harm}_prompts.csv' (HEADER, DELIMITER ',');")

print("success")