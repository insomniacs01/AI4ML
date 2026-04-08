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
            
            # Check if the content is a tabular format (CSV, Excel, Parquet)
            if 'b'\x09' in content:  # BOM for UTF-8
                print("File is a tabular format.")
                
                # Display column names
                columns = content.split('\n')[0].split(',')
                print("Column names:")
                for col in columns:
                    print(col.strip())
                    
                # Show first 2-3 rows with truncated cell content
                start_index = min(1, len(columns))
                end_index = min(start_index + 3, len(columns))
                truncated_content = '\n'.join(content[start_index:end_index])
                print("\nFirst 2-3 rows with truncated cell content:")
                print(truncated_content[:50] + "...")
                
                # Show index column if it's not in the original table
                if 'Index' not in columns:
                    print("Index column is missing.")
                    
            else:
                print("File is a text file.")
                
                # Display first few lines (up to 160 characters)
                print("\nFirst few lines:")
                for line in content[:160]:
                    print(line.strip())
        
        # Decompress the file if it's compressed
        if 'b'\x09' in content:
            import zlib
            decompressed_content = zlib.decompress(content).decode('utf-8')
            print("\nDecompressed content:")
            print(decompressed_content[:160] + "...")
        
    except Exception as e:
        print(f"An error occurred: {e}")

# Example usage
analyze_file("/Users/macbookpro/AI4ML/storage/force_llm_small_input/task.txt")