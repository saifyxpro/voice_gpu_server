#!/usr/bin/env bash
# Lightning AI Studio setup — install into the persistent conda env (cloudspace).
#
# Lightning docs: Studios persist pip/conda packages automatically.
# Each Studio has ONE conda env — treat it like your laptop: pip install in terminal.
# https://lightning.ai/docs/platform/build/ai-studio
#
# Usage (on Lightning Studio terminal):
#   conda activate cloudspace
#   ./scripts/setup-lightning.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ -z "${CONDA_DEFAULT_ENV:-}" ]]; then
  echo "Activate Lightning conda env first: conda activate cloudspace" >&2
  exit 1
fi

PY="$(which python)"
PY_VER="$("${PY}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Lightning Studio setup"
echo "Conda env: ${CONDA_DEFAULT_ENV}"
echo "Python ${PY_VER} at ${PY}"

case "${PY_VER}" in
  3.11|3.12|3.13) ;;
  *)
    echo "Unsupported Python ${PY_VER}. Use 3.11–3.13 (not 3.14)." >&2
    exit 1
    ;;
esac

# uv run / uv sync create a separate .venv — avoid that on Lightning
rm -rf .venv
echo "Removed .venv (use conda cloudspace only)"

pip_install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "${PY}" "$@"
  else
    pip install "$@"
  fi
}

echo ""
echo "=== Base server (editable install) ==="
pip_install -e .

echo ""
echo "=== CUDA PyTorch stack (matched cu124 — includes torchvision) ==="
# Chatterbox/transformers import torchvision; torch+tv must share same CUDA build.
# Mismatch causes: RuntimeError: operator torchvision::nms does not exist
pip_install --force-reinstall \
  torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124

echo ""
echo "=== Verify PyTorch stack ==="
"${PY}" -c "import torch, torchvision; print('torch', torch.__version__, '| torchvision', torchvision.__version__, '| cuda', torch.cuda.is_available())"

echo ""
echo "=== Chatterbox TTS ==="
pip_install "chatterbox-tts>=0.1.3"

echo ""
echo "=== NeMo (Canary STT) ==="
pip_install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git"

echo ""
echo "=== Verify imports ==="
"${PY}" -c "from chatterbox.tts_turbo import ChatterboxTurboTTS; print('chatterbox ok')"
"${PY}" -c "import nemo; print('nemo ok')"
"${PY}" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

cat <<EOF

✅ Lightning Studio setup complete (${CONDA_DEFAULT_ENV})

Lightning persists this env across restarts — install once per Studio.

Start server (terminal 1):
  conda activate cloudspace
  ./scripts/run-server.sh

Start ngrok (terminal 2):
  ./scripts/start-ngrok.sh

Test:
  export VOICE_GPU_API_KEY=\$(grep '^VOICE_GPU_API_KEY=' .env | cut -d= -f2-)
  ./scripts/test-api.sh http://127.0.0.1:8765
EOF
