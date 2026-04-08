import os

def read_and_analyze_file(file_path):
    # Check if the file exists
    if not os.path.exists(file_path):
        print("File does not exist.")
        return
    
    try:
        # Open the file in binary mode
        with open(file_path, 'rb') as file:
            # Read the entire content of the file
            data = file.read()
            
            # Check if the file is a CSV or text file
            if b'.' in data:
                # If it's a CSV file, display column names and first 2-3 rows
                columns = data.decode('utf-8').split('\t')
                print("Column Names:")
                for col in columns:
                    print(col.strip())
                
                print("\nFirst 2-3 Rows:")
                for row in data.split(b'\n'):
                    if len(row) > 50:
                        print(row[:512].strip())
                    else:
                        print(row.strip())
            elif b'.txt' in data:
                # If it's a text file, display the first few lines
                print("First Few Lines:")
                for line in data.split('\n'):
                    print(line.strip())
    except Exception as e:
        # Handle any exceptions that occur during file reading or processing
        print(f"An error occurred: {e}")

# Example usage
read_and_analyze_file("/Users/macbookpro/AI4ML/data/samples/iris.csv")