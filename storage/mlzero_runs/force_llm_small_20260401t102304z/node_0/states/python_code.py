import os
from autogluon.timeseries import TimeSeriesPredictor, TimeSeriesDataFrame

# Define the path to the folder containing data and description files
data_folder = '/Users/macbookpro/AI4ML/storage/mlzero_runs/force_llm_small_20260401t102304z/node_0/output'
description_file = os.path.join(data_folder, 'task.txt')
tiny_csv_file = os.path.join(data_folder, 'tiny.csv')

# Load the data and description files
data_df = TimeSeriesDataFrame.from_file(description_file)
tiny_df = TimeSeriesDataFrame.from_file(tiny_csv_file)

# Define the model parameters
model_params = {
    'learning_rate': 0.01,
    'batch_size': 32,
    'epochs': 50
}

# Initialize the predictor with the specified parameters
predictor = TimeSeriesPredictor(model=model_params, target='mean')

# Train the predictor on the training data
predictor.fit(data_df)

# Make predictions on the test data
test_df = TimeSeriesDataFrame.from_file(tiny_csv_file)
predictions = predictor.predict(test_df)

# Save the predicted results to a file
output_folder = '/Users/macbookpro/AI4ML/storage/mlzero_runs/force_llm_small_output'
os.makedirs(output_folder, exist_ok=True)
results_file = os.path.join(output_folder, 'results')
validation_score_file = os.path.join(output_folder, 'validation_score.txt')

# Save the predictions and validation score to files
with open(results_file, 'w') as f:
    for row in predictions:
        f.write(f"{row}\n")

with open(validation_score_file, 'w') as f:
    f.write(f"Validation Score: {predictions.mean()}\n")