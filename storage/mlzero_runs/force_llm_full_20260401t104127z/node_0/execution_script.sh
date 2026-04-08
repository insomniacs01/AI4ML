Certainly! Below is a minimal bash script that sets up the working directory, runs the `python generated_code.py` script, and ensures it exits with an error if any command fails.

```bash
#!/bin/bash

# Set -euo pipefail to exit on errors
set -euo pipefail

# Change to the working directory below
cd /Users/macbookpro/AI4ML/storage/mlzero_runs/force_llm_full_20260401t104127z/node_0

# Run the python script
python generated_code.py

# Check if the script ran successfully
if [ $? -eq 0 ]; then
    echo "Script executed successfully."
else
    echo "Error executing script. Exit code: $?"
fi
```

### Explanation:
- The script starts by setting `set -euo pipefail` to ensure that any errors during execution are caught and treated as failures.
- It changes the current working directory to `/Users/macbookpro/AI4ML/storage/mlzero_runs/force_llm_full_20260401t104127z/node_0`.
- The script then runs `python generated_code.py`.
- Finally, it checks if the script executed successfully by examining the exit status of the command. If it was successful (i.e., `$?` is 0), it prints a success message; otherwise, it prints an error message along with the exit code.

You can save this script to a file, for example, `run_script.sh`, and run it using `bash run_script.sh`.
