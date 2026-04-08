import os

# Function to read and analyze the file
def analyze_file(file_path):
    try:
        # Check if the file exists
        if not os.path.exists(file_path):
            print("File does not exist.")
            return
        
        # Open the file in binary mode
        with open(file_path, 'rb') as file:
            # Read the entire content of the file
            content = file.read()
            
            # Display column names
            columns = content.split('\n')[0].split(',')
            print("Column Names:")
            for col in columns:
                print(col.strip())
            
            # Show first 2-3 rows with truncated cell content
            if len(content) > 1024:
                print("\nFirst 2-3 Rows (50 chars):")
                print(content[:50])
            else:
                print("\nFirst Row:")
                print(content)
            
            # Display index column if it's in the original table
            if 'index' in columns:
                print("\nIndex Column:")
                print(columns[columns.index('index')])
            
            # If failed to open the file, treat it as text file
            else:
                print("File is not a tabular or text file.")
        
        # Decompress the file if necessary
        # For example, if the file is compressed with gzip
        import gzip
        with gzip.open(file_path, 'rb') as f:
            decompressed_content = f.read()
            
            # Display decompressed content
            print("\nDecompressed Content:")
            print(decompressed_content)
        
    except Exception as e:
        print(f"An error occurred: {e}")

# Example usage
analyze_file("/Users/macbookpro/AI4ML/storage/mlzero_runs/irismlz/20260331T142149Z/input/train.csv")