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
            
            # Check if the content is a tabular format (e.g., CSV)
            if b'\t' in content:
                # Display column names
                columns = content.split(b'\t')[0].split(',')
                print("Column Names:")
                for col in columns:
                    print(col.strip())
                
                # Show first 2-3 rows with truncated cell content
                start_index = min(1, len(columns))
                end_index = min(start_index + 3, len(columns))
                truncated_content = '\n'.join(content[start_index:end_index].split(b'\t'))
                print("\nFirst 2-3 Rows:")
                print(truncated_content[:50])
                
                # Show index column if it's in the original table
                if start_index == 1:
                    print("Index Column:", columns[1])
                
            elif b'.' in content:
                # Display first few lines (up to 160 characters)
                print("\nFirst Few Lines:")
                for line in content.split(b'.'):
                    print(line[:160])
            
            else:
                # Show the decompressed content
                print("Decompressed Content:")
                print(content.decode('utf-8'))
                
        return True
    
    except Exception as e:
        print(f"An error occurred: {e}")
        return False

# Example usage
file_path = "/Users/macbookpro/AI4ML/storage/force_llm_small_input/task.txt"
if analyze_file(file_path):
    print("File analysis completed successfully.")
else:
    print("Failed to analyze the file.")