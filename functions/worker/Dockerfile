FROM public.ecr.aws/lambda/python:3.12

# Install CPU-only torch + torchvision from the same index so their ABIs match
# (a mismatched torchvision pulled later by docling breaks torchvision::nms).
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install docling and its layout/table-structure models
RUN pip install --no-cache-dir \
    docling

# docling pulls in rapidocr, which unconditionally requires the GUI build of
# opencv (opencv-python). That wheel's cv2 .so links against X11/GUI system
# libraries (libxcb.so.1, libGL.so.1, ...) that the Amazon Linux 2023 Lambda
# base image doesn't ship, so the layout pipeline crashes at runtime with
# "libxcb.so.1: cannot open shared object file". Swap in the headless wheel,
# which provides an identical cv2 module built without any GUI/X11 link deps.
# Then assert cv2 actually loads at build time so a missing-shared-object
# regression fails the build instead of surfacing as a runtime parse error.
RUN pip uninstall -y opencv-python opencv-contrib-python 2>/dev/null; \
    pip install --no-cache-dir opencv-python-headless && \
    python -c "import cv2; print('cv2', cv2.__version__, 'loads headless')"

# Bake model weights into a fixed path so nothing is downloaded at runtime.
# docling's default cache is $HOME/.cache/docling/models, but the build-time
# $HOME (/root) differs from the Lambda runtime $HOME (/home/sbx_userNNNN),
# which is read-only — so a $HOME-relative cache can't be found at runtime and
# docling tries to re-download, failing with EROFS. Pin the cache to an
# absolute path and point docling at it via DOCLING_ARTIFACTS_PATH so model
# resolution never depends on $HOME. OCR is disabled in the handler, so skip
# the EasyOCR models.
ENV DOCLING_ARTIFACTS_PATH=/opt/docling-models
RUN docling-tools models download -o /opt/docling-models && echo "Models baked in."

# Install remaining Lambda dependencies
COPY requirements-worker.txt .
RUN pip install --no-cache-dir -r requirements-worker.txt

# Copy shared iacr module (signing module + worker handler + templates)
COPY functions/iacr/ ${LAMBDA_TASK_ROOT}/

CMD ["deep_dive_worker.lambda_handler"]
