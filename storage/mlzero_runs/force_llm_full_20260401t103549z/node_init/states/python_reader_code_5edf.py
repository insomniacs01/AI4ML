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
            if b'.' in content:
                # If it's a CSV file, read and display column names
                import pandas as pd
                df = pd.read_csv(file_path)
                print("Column Names:")
                print(df.columns)
                
                # Display first 2-3 rows with truncated cell content
                print("\nFirst 2-3 Rows:")
                print(df.head(2))
                
                # Show index column if it's not in the original table
                if 'index' not in df.columns:
                    print("Index Column Not Found.")
                else:
                    print("\nIndex Column:")
                    print(df['index'])
                    
            elif b'txt' in content:
                # If it's a text file, display the first few lines
                print("\nFirst Few Lines (Up to 160 Characters):")
                print(content[:160])
                
        else:
            # If it's not a CSV or text file, treat it as text file
            print("File is neither a CSV nor a text file.")
    
    except Exception as e:
        print(f"An error occurred: {e}")

# Example usage
read_and_analyze_file("/Users/macbookpro/AI4ML/storage/force_llm_small_input/tiny.csv")