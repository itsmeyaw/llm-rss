FROM public.ecr.aws/lambda/python:3.12

# Install CPU-only torch first (avoids pulling CUDA wheels)
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu

# Install docling and its layout/table-structure models
RUN pip install --no-cache-dir \
    docling

# Bake model weights into the image so nothing is downloaded at cold start.
# docling fetches models on first DocumentConverter() instantiation.
RUN python -c "from docling.document_converter import DocumentConverter; DocumentConverter(); print('Models baked in.')"

# Install remaining Lambda dependencies
COPY requirements-worker.txt .
RUN pip install --no-cache-dir -r requirements-worker.txt

# Copy shared iacr module (signing module + worker handler + templates)
COPY functions/iacr/ ${LAMBDA_TASK_ROOT}/

CMD ["deep_dive_worker.lambda_handler"]
