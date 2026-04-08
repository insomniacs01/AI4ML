import os

def read_and_analyze_file(file_path):
    try:
        # Check if the file exists
        if not os.path.exists(file_path):
            print("File does not exist.")
            return
        
        # Open the file in binary mode
        with open(file_path, 'rb') as file:
            # Read the entire content of the file
            content = file.read()
            
            # Check if the content is a CSV or text file
            if b'csv' in content:
                print("File is a CSV file.")
                # Display column names and first 2-3 rows with truncated cell content
                columns = content.decode('utf-8').split('\n')[0].strip().split(',')
                for i, col in enumerate(columns):
                    if len(col) > 20:
                        print(f"Column {i+1}: {col[:50]}...")
                    else:
                        print(f"Column {i+1}: {col}")
            elif b'text' in content:
                print("File is a text file.")
                # Display the first few lines
                print(content.decode('utf-8').split('\n')[0].strip())
            else:
                print("Unsupported file type.")
        
        # Decompress the file if it's compressed
        if b'.gz' in content:
            import gzip
            with gzip.open(file_path, 'rb') as f_in:
                decompressed_content = f_in.read()
            print(decompressed_content.decode('utf-8'))
        elif b'.bz2' in content:
            import bz2
            with bz2.open(file_path, 'rb') as f_in:
                decompressed_content = f_in.read()
            print(decompressed_content.decode('utf-8'))
        else:
            print("Unsupported file type.")
    
    except Exception as e:
        print(f"An error occurred: {e}")

# Example usage
read_and_analyze_file("/Users/macbookpro/AI4ML/storage/force_llm_small_input/tiny.csv")