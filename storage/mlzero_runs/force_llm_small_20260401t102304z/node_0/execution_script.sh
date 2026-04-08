#!/bin/bash

# Set the path to your Conda environment folder
conda_env_folder="/Users/macbookpro/AI4ML/storage/mlzero_runs/force_llm_small_20260401t102304z/node_0"

# Create the conda environment if it doesn't exist
if [ ! -d "$conda_env_folder" ]; then
    echo "Creating Conda environment..."
    conda create --name myconda_env python=3.11
fi

# Activate the conda environment
source $conda_env_folder/bin/activate

# Install required packages using pip
echo "Installing required packages..."
pip install uv
pip install -r /Users/macbookpro/AI4ML/external/autogluon-assistant/src/autogluon/assistant/tools_registry/_common/requirements.txt
pip install -r /Users/macbookpro/AI4ML/external/autogluon-assistant/src/autogluon/assistant/tools_registry/autogluon.timeseries/requirements.txt

# Only install the exact packages specified in the requirements files with their dependencies
echo "Only installing specific packages..."
pip install --only-deps -r /Users/macbookpro/AI4ML/external/autogluon-assistant/src/autogluon/assistant/tools_registry/autogluon.timeseries/requirements.txt

# Execute the Python script
echo "Running Python script..."
python /Users/macbookpro/AI4ML/storage/mlzero_runs/force_llm_small_output/generated_code.py

# Deactivate the conda environment
deactivate