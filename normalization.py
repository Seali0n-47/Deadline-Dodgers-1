import os
import time
import csv
import json
from google import genai
from google.genai import types

# 1. Initialize Gemini Client
# Ensure you have set your API key in your environment or replace 'YOUR_API_KEY' below.
client = genai.Client()
MODEL_ID = "gemini-3-flash-preview"

def process_and_save_expenses(input_files, output_csv):
    all_extracted_data = []

    # The mapping prompt with your specific base categories and criteria
    mapping_instructions = """
    Extract every 'Expense Name' and 'Expense Amount' from this file.
    
    CRITICAL CATEGORIZATION RULES:
    You must categorize every expense found into one of the following 8 'Base Categories'. 
    If an expense name in the document does not match these exactly, map it based on the criteria below:
    
    1. Raw Materials: cost of inputs, iron ore, scrap, pellets.
    2. Labor: wages, overtime, contract workers, technicians.
    3. Machine Maintenance: repairs, servicing, spare parts.
    4. Utilities: electricity, water, fuel, power.
    5. Inventory Holding: storage, obsolescence, warehousing.
    6. Logistics: transportation, shipping, freight, delivery.
    7. Quality Costs: rework, scrap, inspection, audits.
    8. Capital Expenditure: new machines, upgrades, large equipment purchases.
    
    Examples: 
    - 'Shipping fee' -> 'Logistics'
    - 'Welder Overtime' -> 'Labor'
    - 'Electricity bill' -> 'Utilities'
    
    Return ONLY a JSON list of objects with these exact keys:
    [{"Expense Name": "Base Category Name", "Expense Amount": 123.45}]
    """

    for file_path in input_files:
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}. Skipping...")
            continue

        print(f"--- Analyzing: {file_path} ---")
        
        # Determine MIME type based on extension
        ext = os.path.splitext(file_path)[1].lower()
        mime_type = {
            ".pdf": "application/pdf",
            ".csv": "text/csv",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png"
        }.get(ext, "application/octet-stream")

        try:
            # FIX: Using 'file=' as the argument for the path to avoid TypeError
            uploaded_file = client.files.upload(
                file=file_path, 
                config=types.UploadFileConfig(mime_type=mime_type)
            )

            # Wait for the file to process (important for PDFs and high-res images)
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(2)
                uploaded_file = client.files.get(name=uploaded_file.name)

            # 2. Call the Model with the Mapping Instructions
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[uploaded_file, mapping_instructions],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0  # High precision for extraction
                )
            )

            # 3. Parse JSON response
            items = json.loads(response.text)
            if isinstance(items, list):
                all_extracted_data.extend(items)
                print(f"Successfully mapped {len(items)} items from {file_path}.")
            
            # Cleanup uploaded file from the cloud
            client.files.delete(name=uploaded_file.name)

        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    # 4. Generate the Final CSV File
    if all_extracted_data:
        with open(output_csv, mode='w', newline='') as csvfile:
            fieldnames = ['Expense Name', 'Expense Amount']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            writer.writerows(all_extracted_data)

        print(f"\nSuccess! Consolidated data saved to: {output_csv}")
    else:
        print("\nNo data was extracted. CSV not created.")

# --- Configuration ---
# Update these names to match your actual file names
files_to_scan = ["WhatsApp Image 2026-03-25 at 3.16.03 PM.jpeg"]
output_filename = "extracted_expenses_normalized.csv"

# Run the integration
if __name__ == "__main__":
    process_and_save_expenses(files_to_scan, output_filename)