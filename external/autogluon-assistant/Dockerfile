ARG AG_BENCH_BASE_IMAGE=nvidia/cuda:12.2.0-runtime-ubuntu22.04
FROM ${AG_BENCH_BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV RUNNING_IN_DOCKER=true

RUN apt-get update && \
    apt-get install -y software-properties-common build-essential && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.11 python3.11-dev python3.11-distutils python3.11-venv ffmpeg libsm6 libxext6 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Install utilities and AWS CLI
RUN apt-get install -y wget unzip curl git pciutils vim nano && \
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip -q awscliv2.zip && \
    ./aws/install && \
    rm awscliv2.zip && \
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.11 get-pip.py && \
    rm get-pip.py && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /usr/local/aws

# Install Miniconda
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh

# Add conda to PATH
ENV PATH="/opt/conda/bin:$PATH"

# Initialize conda and create mlzero and maab environments
RUN conda init bash && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    conda create -n mlzero python=3.11 -y && \
    conda create -n maab python=3.11 -y && \
    conda clean -a -y

# Make conda activate mlzero by default
RUN echo "conda activate mlzero" >> ~/.bashrc

# Set environment variables to use mlzero environment by default
ENV CONDA_DEFAULT_ENV=mlzero
ENV PATH="/opt/conda/envs/mlzero/bin:$PATH"

# Clone autogluon-assistant from GitHub
ARG BRANCH=main
RUN git clone --branch ${BRANCH} https://github.com/autogluon/autogluon-assistant.git /opt/autogluon-assistant

# Install autogluon-assistant in mlzero environment
RUN bash -c "source /opt/conda/etc/profile.d/conda.sh && \
    conda activate mlzero && \
    cd /opt/autogluon-assistant && \
    pip install uv && \
    uv pip install opencv-python-headless && \
    uv pip install -e ."

# Install MAAB in maab environment
RUN bash -c "source /opt/conda/etc/profile.d/conda.sh && \
    conda activate maab && \
    cd /opt/autogluon-assistant/maab && \
    pip install uv && \
    uv pip install opencv-python-headless && \
    uv pip install -r requirements.txt"

# Set working directory for users
WORKDIR /workspace

# Start bash shell by default
CMD ["/bin/bash"]
